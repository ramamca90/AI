#!/usr/bin/env bash
# Stores a secret value in Secrets Manager. The value is read from a silent prompt or a pipe, so
# it never appears on screen, in shell history or on a command line.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/set-secrets.sh <api-key|anthropic>

  api-key     API_KEY, the X-API-Key value for write endpoints.
              Generate one with: openssl rand -hex 32
  anthropic   ANTHROPIC_API_KEY, needed only with llm_provider = "anthropic".

Prompts without echo. Or pipe the value in:  pass show copilot/api-key | scripts/set-secrets.sh api-key
Running tasks read secrets at start, so restart the services after changing a value.
USAGE
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
  api-key) output_name="api_key_secret_name" ;;
  anthropic) output_name="anthropic_api_key_secret_name" ;;
  *)
    usage >&2
    exit 2
    ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tf_dir="$root/infra/terraform"

secret_name="$(terraform -chdir="$tf_dir" output -raw "$output_name")"
region="$(terraform -chdir="$tf_dir" output -raw aws_region)"

value=""
if [ -t 0 ]; then
  IFS= read -rs -p "Value for $secret_name (hidden): " value
  echo
else
  IFS= read -r value || true
fi

if [ -z "$value" ]; then
  echo "error: empty value, nothing stored" >&2
  exit 1
fi

# A private temp file keeps the value out of the process list, which `--secret-string "$value"`
# would expose. It also works with the native Windows aws.exe, which cannot read /dev/stdin.
umask 077
value_file="$(mktemp)"
trap 'rm -f "$value_file"' EXIT
printf '%s' "$value" >"$value_file"
unset value

if command -v cygpath >/dev/null 2>&1; then
  value_uri="file://$(cygpath -m "$value_file")"
else
  value_uri="file://$value_file"
fi

aws secretsmanager put-secret-value \
  --region "$region" \
  --secret-id "$secret_name" \
  --secret-string "$value_uri" \
  --query Name \
  --output text >/dev/null

echo "Stored a new value in $secret_name."
echo "If the services are already running, restart them to pick it up:"
echo "  aws ecs update-service --region $region --cluster <cluster> --service <service> --force-new-deployment"
