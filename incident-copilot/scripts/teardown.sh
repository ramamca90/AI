#!/usr/bin/env bash
# Destroys the whole stack after typed confirmation. With the demo defaults this also deletes the
# database, its data, the images and the secrets, and none of that can be recovered.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/teardown.sh

Runs `terraform destroy` in infra/terraform after you type the stack name to confirm.
If deletion_protection is true, set it to false and apply first.
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

stack="$(terraform -chdir="$tf_dir" output -raw name_prefix)"

echo "This permanently deletes every resource in stack '$stack', including the database."
IFS= read -r -p "Type '$stack' to confirm: " answer

if [ "$answer" != "$stack" ]; then
  echo "Confirmation did not match. Nothing was changed." >&2
  exit 1
fi

terraform -chdir="$tf_dir" destroy -auto-approve
rm -f "$tf_dir/services.auto.tfvars"

echo "Stack '$stack' is destroyed. Check AWS Billing in a day or two to confirm spending stopped."
