#!/usr/bin/env bash
set -euo pipefail
umask 077

# Same sequence as demeter-run/up: local apply, then migrate into the new bucket.
# The GitHub Actions concurrency group serializes bootstrap and application runs.
config="$RUNNER_TEMP/config.json"
bucket=$(jq -r '.terraform.backend.bucket' "$config")
key=$(jq -r '.terraform.bootstrap.key' "$config")
endpoint=$(jq -r '.terraform.backend.endpoints.s3' "$config")
account=$(jq -r '.cloudflare.account_id' "$config")
jurisdiction=$(jq -r '.terraform.bootstrap.jurisdiction' "$config")
root=terraform/bootstrap
address=module.state_bucket.cloudflare_r2_bucket.this

reject_deletions() {
  # Never replace/delete the bucket that stores this root's own state.
  terraform -chdir="$root" show -json "$RUNNER_TEMP/bootstrap.tfplan" |
    jq -e '[.resource_changes[]? | .change.actions[] | select(. == "delete")] | length == 0' >/dev/null
}

# Only a confirmed missing bucket/key permits local bootstrap. Authentication,
# transport and other errors must fail rather than overwrite existing state.
if aws s3api head-object --endpoint-url "$endpoint" --bucket "$bucket" --key "$key" \
    > /dev/null 2> "$RUNNER_TEMP/state-head-error"; then
  cp "$root/backend.tf.example" "$root/backend.tf"
  terraform -chdir="$root" init -input=false -lockfile=readonly -backend-config="$RUNNER_TEMP/bootstrap-backend.json"
else
  if ! grep -Eq '\((404|NoSuchKey|NoSuchBucket|NotFound)\)' "$RUNNER_TEMP/state-head-error"; then
    echo 'Cannot determine whether bootstrap state exists; refusing local bootstrap.' >&2
    exit 1
  fi
  terraform -chdir="$root" init -input=false -lockfile=readonly

  # A failed earlier migration may have left the bucket without remote state.
  # Adopt it so a new CI runner can recover without a workstation state file.
  status=$(curl --silent --show-error --output "$RUNNER_TEMP/bucket.json" --write-out '%{http_code}' \
    --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    --header "cf-r2-jurisdiction: $jurisdiction" \
    "https://api.cloudflare.com/client/v4/accounts/$account/r2/buckets/$bucket")
  case "$status" in
    200)
      terraform -chdir="$root" import -input=false "$address" "$account/$bucket/$jurisdiction"
      ;;
    404) ;;
    *) echo "Cannot inspect state bucket (HTTP $status); refusing bootstrap." >&2; exit 1 ;;
  esac
  terraform -chdir="$root" plan -input=false -out="$RUNNER_TEMP/bootstrap.tfplan"
  reject_deletions
  terraform -chdir="$root" apply -input=false "$RUNNER_TEMP/bootstrap.tfplan"
  cp "$root/backend.tf.example" "$root/backend.tf"
  terraform -chdir="$root" init -input=false -lockfile=readonly -migrate-state -force-copy \
    -backend-config="$RUNNER_TEMP/bootstrap-backend.json"
fi
terraform -chdir="$root" plan -input=false -out="$RUNNER_TEMP/bootstrap.tfplan"
reject_deletions
terraform -chdir="$root" apply -input=false "$RUNNER_TEMP/bootstrap.tfplan"
terraform -chdir="$root" plan -input=false -detailed-exitcode -no-color
