#!/usr/bin/env bash
# Builds and ships a version: push image, migrate, roll out, smoke test. deploy.yml calls the same
# steps, so a laptop deploy and a CI deploy behave the same way.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/deploy.sh [all|build|migrate|rollout|smoke]

  all       Every step below, in order (default).
  build     Build the image and push it to ECR. Skipped if the tag already exists.
  migrate   Run `alembic upgrade head` as a one-off task. Fails if the migration fails.
  rollout   Update the api, then the worker. Fails if ECS rolls either one back.
  smoke     Poll BASE_URL/readyz until it returns 200.

Settings come from environment variables, falling back to `terraform output`:
  AWS_REGION ECR_REPOSITORY_URL ECS_CLUSTER API_SERVICE WORKER_SERVICE API_TASK_FAMILY
  WORKER_TASK_FAMILY MIGRATE_TASK_FAMILY MIGRATE_SUBNETS MIGRATE_SECURITY_GROUP BASE_URL

IMAGE_TAG defaults to the git SHA, with a -dirty suffix when the tree has local changes.

The first deploy also creates the ECS services with Terraform, so it must run from a machine
that holds the Terraform state, not from GitHub Actions.
USAGE
}

step="${1:-all}"
case "$step" in
  -h | --help)
    usage
    exit 0
    ;;
  all | build | migrate | rollout | smoke) ;;
  *)
    usage >&2
    exit 2
    ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tf_dir="$root/infra/terraform"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

die() {
  echo "error: $*" >&2
  exit 1
}

# aws.exe on Windows ends text output with CRLF, which would corrupt comparisons.
aws_text() {
  aws "$@" --output text | tr -d '\r'
}

# aws.exe cannot read Git Bash paths, so give it a Windows path when there is one.
file_uri() {
  if command -v cygpath >/dev/null 2>&1; then
    printf 'file://%s' "$(cygpath -m "$1")"
  else
    printf 'file://%s' "$1"
  fi
}

load_setting() {
  local env_name="$1" output_name="$2" value
  if [ -z "${!env_name:-}" ]; then
    value="$(terraform -chdir="$tf_dir" output -raw "$output_name" 2>/dev/null)" ||
      die "$env_name is not set and terraform has no output $output_name. Run scripts/bootstrap.sh."
    printf -v "$env_name" '%s' "$value"
  fi
  export "${env_name?}"
}

load_settings() {
  load_setting AWS_REGION aws_region
  load_setting ECR_REPOSITORY_URL ecr_repository_url
  load_setting ECS_CLUSTER ecs_cluster_name
  load_setting API_SERVICE api_service_name
  load_setting WORKER_SERVICE worker_service_name
  load_setting API_TASK_FAMILY api_task_family
  load_setting WORKER_TASK_FAMILY worker_task_family
  load_setting MIGRATE_TASK_FAMILY migrate_task_family
  load_setting MIGRATE_SUBNETS migrate_subnets
  load_setting MIGRATE_SECURITY_GROUP migrate_security_group
  load_setting BASE_URL base_url
}

resolve_image_tag() {
  if [ -n "${IMAGE_TAG:-}" ]; then
    return
  fi
  if [ -n "${GITHUB_SHA:-}" ]; then
    IMAGE_TAG="$GITHUB_SHA"
    return
  fi
  IMAGE_TAG="$(git -C "$root" rev-parse HEAD 2>/dev/null)" ||
    die "not a git checkout. Set IMAGE_TAG."
  if [ -n "$(git -C "$root" status --porcelain)" ]; then
    IMAGE_TAG="$IMAGE_TAG-dirty-$(date +%s)"
  fi
}

do_build() {
  local registry="${ECR_REPOSITORY_URL%%/*}"
  local repository="${ECR_REPOSITORY_URL#*/}"

  # Tags are immutable in ECR, so a rerun of the same commit reuses the image.
  if aws ecr describe-images --region "$AWS_REGION" --repository-name "$repository" \
    --image-ids "imageTag=$IMAGE_TAG" >/dev/null 2>&1; then
    echo "Image $IMAGE_TAG is already in ECR."
    return
  fi

  aws ecr get-login-password --region "$AWS_REGION" |
    docker login --username AWS --password-stdin "$registry"
  docker build --platform linux/amd64 --tag "$ECR_REPOSITORY_URL:$IMAGE_TAG" "$root"
  docker push "$ECR_REPOSITORY_URL:$IMAGE_TAG"
}

# Copies the family's latest revision with the new image. Prints the new revision's ARN.
register_task_definition() {
  local family="$1" current="$work_dir/current-$1.json" next="$work_dir/next-$1.json"

  aws ecs describe-task-definition --region "$AWS_REGION" --task-definition "$family" \
    --query taskDefinition --output json >"$current"

  jq --arg image "$ECR_REPOSITORY_URL:$IMAGE_TAG" '
    del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities,
        .registeredAt, .registeredBy, .deregisteredAt)
    | .containerDefinitions |= map(.image = $image)
  ' "$current" >"$next"

  aws_text ecs register-task-definition --region "$AWS_REGION" \
    --cli-input-json "$(file_uri "$next")" \
    --query taskDefinition.taskDefinitionArn
}

do_migrate() {
  local task_definition run_output task_arn exit_code reason

  task_definition="$(register_task_definition "$MIGRATE_TASK_FAMILY")"
  echo "Running migration with $task_definition"

  run_output="$(aws ecs run-task --region "$AWS_REGION" \
    --cluster "$ECS_CLUSTER" \
    --task-definition "$task_definition" \
    --launch-type FARGATE \
    --count 1 \
    --network-configuration "awsvpcConfiguration={subnets=[$MIGRATE_SUBNETS],securityGroups=[$MIGRATE_SECURITY_GROUP],assignPublicIp=ENABLED}" \
    --output json)"

  task_arn="$(printf '%s' "$run_output" | jq -r '.tasks[0].taskArn // empty' | tr -d '\r')"
  if [ -z "$task_arn" ]; then
    printf '%s' "$run_output" | jq '.failures' >&2
    die "migration task did not start"
  fi

  aws ecs wait tasks-stopped --region "$AWS_REGION" --cluster "$ECS_CLUSTER" --tasks "$task_arn" ||
    die "timed out waiting for migration task $task_arn"

  # The waiter also succeeds when the task fails, so the exit code has to be checked here.
  exit_code="$(aws_text ecs describe-tasks --region "$AWS_REGION" \
    --cluster "$ECS_CLUSTER" --tasks "$task_arn" \
    --query 'tasks[0].containers[0].exitCode')"
  if [ "$exit_code" != "0" ]; then
    reason="$(aws_text ecs describe-tasks --region "$AWS_REGION" \
      --cluster "$ECS_CLUSTER" --tasks "$task_arn" --query 'tasks[0].stoppedReason')"
    die "migration failed (exit code $exit_code, reason: $reason). See the migrate log group."
  fi
  echo "Migration finished."
}

# Rollout success has to be read from the deployment. The services-stable waiter passes after a
# circuit-breaker rollback too, because the service is stable again on the old version.
wait_for_rollout() {
  local service="$1" expected="$2" deadline deployments primary state
  deadline=$(($(date +%s) + 1200))

  while [ "$(date +%s)" -lt "$deadline" ]; do
    deployments="$(aws ecs describe-services --region "$AWS_REGION" \
      --cluster "$ECS_CLUSTER" --services "$service" \
      --query 'services[0].deployments' --output json)"
    primary="$(printf '%s' "$deployments" |
      jq -r '.[] | select(.status == "PRIMARY") | .taskDefinition' | tr -d '\r')"
    state="$(printf '%s' "$deployments" |
      jq -r '.[] | select(.status == "PRIMARY") | .rolloutState' | tr -d '\r')"

    if [ "$primary" != "$expected" ]; then
      die "$service was rolled back to $primary"
    fi
    case "$state" in
      COMPLETED)
        echo "$service is running $expected"
        return
        ;;
      FAILED) die "$service rollout failed" ;;
      *) echo "$service: $state" ;;
    esac
    sleep 15
  done
  die "timed out waiting for $service"
}

roll_out_service() {
  local service="$1" family="$2" task_definition
  task_definition="$(register_task_definition "$family")"
  aws ecs update-service --region "$AWS_REGION" --cluster "$ECS_CLUSTER" --service "$service" \
    --task-definition "$task_definition" --query 'service.serviceName' --output text >/dev/null
  wait_for_rollout "$service" "$task_definition"
}

api_service_exists() {
  [ "$(aws_text ecs describe-services --region "$AWS_REGION" --cluster "$ECS_CLUSTER" \
    --services "$API_SERVICE" --query 'services[0].status')" = "ACTIVE" ]
}

# Services are created only now, so they start on a migrated database with their secrets set.
# The tfvars file keeps later `terraform apply` runs from removing them.
create_services() {
  if [ -n "${GITHUB_ACTIONS:-}" ] || ! command -v terraform >/dev/null 2>&1; then
    die "ECS services do not exist yet. Run the first deploy with scripts/deploy.sh locally."
  fi

  printf 'enable_services = true\nimage_tag       = "%s"\n' "$IMAGE_TAG" \
    >"$tf_dir/services.auto.tfvars"
  terraform -chdir="$tf_dir" apply
}

current_task_definition() {
  aws_text ecs describe-services --region "$AWS_REGION" --cluster "$ECS_CLUSTER" \
    --services "$1" --query 'services[0].taskDefinition'
}

do_rollout() {
  if api_service_exists; then
    roll_out_service "$API_SERVICE" "$API_TASK_FAMILY"
    roll_out_service "$WORKER_SERVICE" "$WORKER_TASK_FAMILY"
  else
    create_services
    wait_for_rollout "$API_SERVICE" "$(current_task_definition "$API_SERVICE")"
    wait_for_rollout "$WORKER_SERVICE" "$(current_task_definition "$WORKER_SERVICE")"
  fi
}

do_smoke() {
  local attempt code
  for attempt in $(seq 1 20); do
    code="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 10 \
      "$BASE_URL/readyz" || true)"
    if [ "$code" = "200" ]; then
      echo "Smoke test passed: $BASE_URL/readyz"
      return
    fi
    echo "Attempt $attempt: /readyz returned $code"
    sleep 15
  done
  die "$BASE_URL/readyz never returned 200"
}

load_settings
resolve_image_tag
echo "Image tag: $IMAGE_TAG"

case "$step" in
  build) do_build ;;
  migrate) do_migrate ;;
  rollout) do_rollout ;;
  smoke) do_smoke ;;
  all)
    do_build
    do_migrate
    do_rollout
    do_smoke
    ;;
esac
