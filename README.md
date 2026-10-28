# MorrowWallet infrastructure

Terraform for the existing `morrowwallet.com` Cloudflare zone and its private R2
state bucket. Configuration lives in `config.yaml`; SOPS uses MorrowWallet age
recipients in `.sops.yaml`. All accounts, keys, buckets, and recipients belong
to MorrowWallet. Related: [clanker#34](https://github.com/yoroi-classic/clanker/issues/34).

## Terraform and CI

The `test-terraform` and `run-terraform` workflows follow
[Blink Labs infrastructure](https://github.com/blinklabs-io/infrastructure).
Terraform is pinned to 1.14.6; both roots lock the Cloudflare provider and pin
Blink Labs modules to immutable commits. Module-scoped release commits contain
the module at the repository root. The zone module uses
[`cloudflare_zone/v0.1.2`](https://github.com/blinklabs-io/terraform-modules/tree/cloudflare_zone/v0.1.2),
which excludes paid Enhanced HTTP/2 Prioritization on Free zones.

- `test-terraform` performs credential-free formatting, initialization,
  validation, and script checks on pull requests. It receives no deployment secrets.
- `run-terraform` runs manually on `main`, after deployment is enabled in
  `config.yaml`. Choose `bootstrap`, `plan`, or `apply`. A shared concurrency
  group serializes all operations without cancelling an active run.
- `bootstrap` uses the separate `terraform-bootstrap` environment. It creates
  the bucket with local state, then migrates its own state into that bucket,
  following [demeter-run/up](https://github.com/demeter-run/up/blob/main/bin/bootstrap-cloud).
- `plan` and `apply` use the `terraform` environment and the application state
  key. Apply creates, displays, and applies a fresh saved plan, then checks for drift.

Live Terraform operations run in GitHub Actions. There is no apply on push.

## Protected GitHub environments and credentials

Before adding any credentials, protect `main`: require pull requests, human
approval, and the Terraform validation check, and restrict direct pushes.
Create **Settings → Environments → terraform-bootstrap** and **terraform**.
Give each environment a deployment branch policy allowing only `main` and
required human reviewers. Store credentials as **environment secrets** only;
remove any copies from repository or organization secrets available to this repo.
The environment policy provides the credential boundary independently of the
workflow's ref guard.

Create these secrets in each environment:

| Secret | `terraform-bootstrap` | `terraform` |
| --- | --- | --- |
| `SOPS_AGE_KEY` | Private age identity authorized in `.sops.yaml` | Same authorization requirement |
| `CLOUDFLARE_API_TOKEN` | Account → Workers R2 Storage → Edit, scoped to the MorrowWallet account | Zone → Zone → Read; Zone → Zone Settings → Edit; Zone → DNS → Edit, scoped only to `morrowwallet.com` |
| `AWS_ACCESS_KEY_ID` | R2 Object Read & Write access key; temporarily allow all buckets if the dashboard cannot scope it to the not-yet-created bucket | R2 Object Read & Write access key scoped only to the state bucket |
| `AWS_SECRET_ACCESS_KEY` | Matching R2 secret | Matching bucket-scoped R2 secret |

Enable R2 in the MorrowWallet account, but **do not create the bucket manually**.
Create the bootstrap R2 credentials before running bootstrap. After the bucket
exists, rotate the bootstrap R2 credentials to bucket-scoped Object Read & Write
and revoke the temporary account-wide token. Retain the account-scoped Cloudflare
R2 management token only in `terraform-bootstrap` for bucket maintenance.
The AWS-named secrets are Cloudflare R2 credentials; no AWS account or Global
API Key is required.

References: [R2 credentials](https://developers.cloudflare.com/r2/api/tokens/),
[bucket API permissions](https://developers.cloudflare.com/api/resources/r2/subresources/buckets/methods/create/),
[zone settings permissions](https://developers.cloudflare.com/api/resources/zones/subresources/settings/methods/edit/),
and [DNS permissions](https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/create/).

## Complete config.yaml and SOPS

Keep `terraform.enabled: false` until configuration and protected environments
are ready. Static validation works with the initial public template.

Set these values in `config.yaml`:

- `cloudflare.account_id` and `cloudflare.zones[0].zone_id`: the MorrowWallet
  account and existing zone IDs, quoted as strings. Only `morrowwallet.com` is supported.
- `cloudflare.zones[0].plan`: the existing zone's actual plan.
- `terraform.backend.bucket`: the private state bucket name to create.
- `terraform.backend.endpoints.s3`: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`,
  or the corresponding `.eu`/`.fedramp` endpoint for that jurisdiction.
- `terraform.backend.key` and `terraform.bootstrap.key`: different `.tfstate`
  keys in the same bucket. Defaults are `morrowwallet.tfstate` and `bootstrap.tfstate`.
- `terraform.bootstrap.location`, `jurisdiction`, and `storage_class`: bucket
  settings. Defaults are automatic location, `default` jurisdiction, and `Standard`.
  Keep `use_lockfile` enabled for both roots.

Set MorrowWallet operators' and CI public age recipients in `.sops.yaml`.
Encrypt configuration before committing it:

```sh
sops --encrypt --in-place config.yaml
sops config.yaml
```

Use SOPS for every subsequent edit, including enabling deployment. The rule
follows Blink Labs' `auth`/`secret` convention. Infrastructure settings remain
readable for credential-free validation; SOPS metadata authenticates the file.
Private identities and API tokens belong only in the environment secrets.

## Existing DNS and zone settings

Inventory existing DNS before the first application plan. Imports adopt the
zone and all settings managed by the module. Empty DNS lists leave existing
records unmanaged. To adopt a record, add its current values and Cloudflare `id`
together. Omit `id` only for a new record. For example:

```yaml
cname_records:
  - name: api
    id: REPLACE_WITH_EXISTING_RECORD_ID
    record_name: api.morrowwallet.com
    content: actual-existing-ingress.example.net
    proxied: false
```

A/CNAME entries require `name`, `record_name`, and `content`; `proxied` defaults
to true. TXT entries require `name`, `record_name`, and `content`. MX entries
require `value` and integer `priority`, and apply at the apex.

The module enforces strict TLS, TLS 1.2 minimum, HTTPS redirects, HTTP/3,
caching, Rocket Loader, TLS 1.3 zero-RTT, and one-year HSTS with preload and
subdomains. HSTS affects every subdomain and outlives a rollback. Proxied DNS
TTLs become automatic; other TTLs become 60 seconds. Review these changes before
applying. Wallet API cache bypass and request logging are separate deployment work.

## First deployment and bootstrap recovery

After configuration is reviewed and merged, use **Actions → run-terraform →
Run workflow**, select `main`, and choose `bootstrap`. Approve the protected
environment deployment. The job creates the bucket, disables its public
`r2.dev` endpoint, migrates bootstrap state into R2, and checks for drift.
No custom domain is created for the bucket.

Bootstrap checks the remote bootstrap key first. If it exists, the job uses
remote state directly. If the bucket exists without that key after an interrupted
run, the job imports the bucket into temporary local state and retries migration.
Only confirmed missing bucket/key responses permit this recovery; authorization
and network failures stop the run. Bootstrap rejects any plan containing deletion
or replacement. Local state and temporary plans are removed from the runner.
Do not change bucket, jurisdiction, or state keys as a routine configuration edit;
those changes require a separately reviewed state migration. Keep protected state backups.

After bootstrap, narrow its R2 credentials as described above. Dispatch `plan`,
review zone imports and every setting/DNS change in the log, then dispatch
`apply`. Confirm the drift check exits 0 and verify DNS/HTTPS behavior.
To roll back, revert configuration through a PR and use the same CI plan/apply
process. Do not destroy the imported domain or state bucket as a rollback.

## Static validation

These checks need no credentials or remote state:

```sh
terraform fmt -check -recursive -diff
terraform -chdir=terraform init -backend=false -input=false -lockfile=readonly
terraform -chdir=terraform validate -no-color
terraform -chdir=terraform/bootstrap init -backend=false -input=false -lockfile=readonly
terraform -chdir=terraform/bootstrap validate -no-color
shellcheck scripts/*.sh
python3 -m unittest discover -s tests
actionlint .github/workflows/test-terraform.yml .github/workflows/run-terraform.yml
```

State, saved plans, and `.terraform/` are ignored. `backend.tf.example` declares
the bootstrap backend; CI creates `backend.tf` only after the local apply.
All backend values come from `config.yaml`.
