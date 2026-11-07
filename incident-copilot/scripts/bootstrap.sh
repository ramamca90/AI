#!/usr/bin/env bash
# Creates the foundation: network, database, queue, registry, empty secrets and the deploy role.
# ECS services come later, from deploy.sh. Prompts before applying.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/bootstrap.sh

Runs `terraform init` and `terraform apply` in infra/terraform. AWS credentials must already be
configured, and infra/terraform/terraform.tfvars must exist (copied from the .example file).

Next steps are printed at the end. See docs/DEPLOYMENT.md.
USAGE
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
  "") ;;
  *)
    usage >&2
    exit 2
    ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tf_dir="$root/infra/terraform"

for tool in terraform aws docker jq; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "error: $tool is not installed" >&2
    exit 1
  }
done

if [ ! -f "$tf_dir/terraform.tfvars" ]; then
  echo "error: infra/terraform/terraform.tfvars is missing." >&2
  echo "Copy terraform.tfvars.example to it, set github_repo, and run this again." >&2
  exit 1
fi

account="$(aws sts get-caller-identity --query Account --output text | tr -d '\r')"
echo "AWS account: $account"

terraform -chdir="$tf_dir" init
terraform -chdir="$tf_dir" apply

cat <<'NEXT'

Foundation is up. Next:
  1. scripts/set-secrets.sh api-key
  2. scripts/set-secrets.sh anthropic     (only with llm_provider = "anthropic")
  3. scripts/deploy.sh                    (first deploy creates the ECS services)
NEXT
