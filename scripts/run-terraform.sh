#!/usr/bin/env bash
set -euo pipefail

terraform init -input=false -lockfile=readonly -backend-config="$RUNNER_TEMP/backend.json"
terraform plan -input=false -out="$RUNNER_TEMP/terraform.tfplan"
terraform show -no-color "$RUNNER_TEMP/terraform.tfplan"
if [[ "$OPERATION" == apply ]]; then
  terraform apply -input=false "$RUNNER_TEMP/terraform.tfplan"
  terraform plan -input=false -detailed-exitcode -no-color
fi
