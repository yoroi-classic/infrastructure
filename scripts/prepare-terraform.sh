#!/usr/bin/env bash
set -euo pipefail
umask 077

# Called only by the protected, main-only deployment workflow.
sops --decrypt --output-type json config.yaml > "$RUNNER_TEMP/config.json"
jq -e '
  .terraform.enabled == true and
  (.cloudflare.account_id | test("^[a-fA-F0-9]{32}$")) and
  (.cloudflare.zones | length == 1) and
  .cloudflare.zones[0].name == "morrowwallet.com" and
  (.cloudflare.zones[0].zone_id | test("^[a-fA-F0-9]{32}$")) and
  (.terraform.backend.endpoints.s3 | test("^https://[a-fA-F0-9]{32}([.](eu|fedramp))?[.]r2[.]cloudflarestorage[.]com$")) and
  (.terraform.backend.bucket | test("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")) and
  (.terraform.backend.key | endswith(".tfstate")) and
  (.terraform.bootstrap.key | endswith(".tfstate")) and
  .terraform.backend.key != .terraform.bootstrap.key and
  (.terraform.bootstrap.jurisdiction | IN("default", "eu", "fedramp")) and
  .terraform.backend.endpoints.s3 == ("https://" + .cloudflare.account_id +
    (if .terraform.bootstrap.jurisdiction == "default" then "" else "." + .terraform.bootstrap.jurisdiction end) +
    ".r2.cloudflarestorage.com") and
  .terraform.backend.use_lockfile == true
' "$RUNNER_TEMP/config.json" >/dev/null
jq '.terraform.backend' "$RUNNER_TEMP/config.json" > "$RUNNER_TEMP/backend.json"
jq '.terraform.backend + {key: .terraform.bootstrap.key}' "$RUNNER_TEMP/config.json" > "$RUNNER_TEMP/bootstrap-backend.json"
sops --decrypt --in-place config.yaml
