# MorrowWallet infrastructure

Terraform configuration for the existing `morrowwallet.com` Cloudflare zone.
Related to [clanker#34](https://github.com/yoroi-classic/clanker/issues/34).

This follows the `test-terraform` and `run-terraform` GitHub Actions workflows
in [Blink Labs infrastructure](https://github.com/blinklabs-io/infrastructure).
Configuration lives in `config.yaml`, SOPS uses age recipients from
`.sops.yaml`, and deployment credentials come from GitHub Actions secrets.
All accounts, state storage, credentials, and age recipients belong to MorrowWallet.

## Terraform and CI

Terraform 1.14.6 is recorded in `.terraform-version`. The Cloudflare provider
is locked in `terraform/.terraform.lock.hcl`. The zone module is pinned to
[`cloudflare_zone/v0.1.1`](https://github.com/blinklabs-io/terraform-modules/tree/cloudflare_zone/v0.1.1);
that release contains the module at the repository root.

- `test-terraform`: validates configuration and runs a live plan for pull
  requests from this repository or a manual workflow dispatch. Fork pull
  requests receive static validation without deployment credentials.
- `run-terraform`: manually dispatched on `main` with `arguments` set to
  `plan` or `apply`. It initializes remote state, saves and shows a plan, and
  applies that saved plan only when `apply` was selected. It then checks for drift.

Both live jobs install SOPS, decrypt configuration using `SOPS_AGE_KEY`,
derive backend configuration from `config.yaml`, and initialize Terraform with
the R2 credentials supplied by GitHub. Applications and configuration are
reviewed through pull requests; Terraform deployment runs in CI.

The first live run needs the account configuration, encrypted config, backend
bucket, and GitHub secrets described below.

## GitHub repository secrets

In this repository's **Settings → Secrets and variables → Actions**, add:

| Secret | Value and scope |
| --- | --- |
| `SOPS_AGE_KEY` | age private identity authorized by the public recipient in `.sops.yaml` |
| `CLOUDFLARE_API_TOKEN` | MorrowWallet API token: Zone → Zone → Read; Zone → Zone Settings → Edit; Zone → DNS → Edit. Scope all three to `morrowwallet.com` only. |
| `AWS_ACCESS_KEY_ID` | MorrowWallet R2 S3-compatible access key ID |
| `AWS_SECRET_ACCESS_KEY` | Matching R2 secret access key; Object Read & Write scoped only to the private state bucket |

Use the R2 dashboard to create the bucket-scoped Object Read & Write token.
These credentials are for R2, not an AWS account. A Global API Key is not
required. See Cloudflare's [R2 credentials](https://developers.cloudflare.com/r2/api/tokens/),
[zone settings permissions](https://developers.cloudflare.com/api/resources/zones/subresources/settings/methods/edit/),
and [DNS permissions](https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/create/).

Deployment tokens and age private keys are stored in GitHub secrets, never
committed to `config.yaml` or posted in issues.

## Complete config.yaml and SOPS

Enable R2 in the MorrowWallet account and create a private state bucket as an
account-setup prerequisite, following the [R2 backend guide](https://developers.cloudflare.com/terraform/advanced-topics/remote-backend/).
The state bucket is outside this root so application changes cannot delete
their own backend. Keep access restricted and arrange protected state backups.

Set the following values in `config.yaml`:

- `cloudflare.account_id`: MorrowWallet's account ID.
- `cloudflare.zones[0].zone_id`: the existing `morrowwallet.com` zone ID.
  Keep IDs quoted as strings.
- `cloudflare.zones[0].plan`: confirm the existing Free-plan assumption.
- `terraform.backend.bucket`: the private state bucket.
- `terraform.backend.endpoints.s3`: normally
  `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`; use the jurisdiction-specific
  endpoint if the bucket requires one.
- `terraform.backend.key`: a state key unique to this root; the default is
  `morrowwallet.tfstate`. Keep `use_lockfile` enabled.

Set the MorrowWallet operators' and CI public age recipients in `.sops.yaml`.
Encrypt the template before committing configuration:

```sh
sops --encrypt --in-place config.yaml
sops config.yaml
```

The SOPS rule follows Blink Labs' `auth`/`secret` field convention.
Infrastructure values remain readable for Terraform validation. There are no
secret-valued config fields initially; SOPS still protects the file's
integrity. Once encrypted, make every edit through SOPS to keep its MAC valid.
Keep the matching private CI identity only in `SOPS_AGE_KEY`.

## Existing DNS and zone settings

Inventory existing DNS records and settings before the first CI plan. Imports
adopt the existing zone and every setting managed by the pinned module. Empty
DNS lists leave existing records unmanaged.

To adopt a DNS record, add its current values and Cloudflare `id` together in
the appropriate list in `config.yaml`. Omit `id` only for a genuinely new
record. For example:

```yaml
cname_records:
  - name: api
    id: REPLACE_WITH_EXISTING_RECORD_ID
    record_name: api.morrowwallet.com
    content: actual-existing-ingress.example.net
    proxied: false
```

Use the actual target and proxy setting. A/CNAME entries require `name`,
`record_name`, and `content`; `proxied` defaults to true. TXT entries require
`name`, `record_name`, and `content`. MX entries require `value` and integer
`priority` and apply at the apex. Future Kubernetes ingress targets belong to
the deployment work.

The module enforces strict TLS, TLS 1.2 minimum, HTTPS redirects, HTTP/3,
caching settings, Rocket Loader, TLS 1.3 zero-RTT, and one-year HSTS with
preload and subdomains. HSTS affects every subdomain and outlives a Terraform
rollback. Proxied DNS TTLs become automatic; other TTLs become 60 seconds.
Review these changes before applying. The module does not configure request
logging or wallet API cache bypass rules.

## First deployment through GitHub Actions

After the Terraform PR and completed configuration are merged:

1. Open **Actions → run-terraform → Run workflow**, select `main`, choose
   `plan`, and run it.
2. Review the plan in the job log. The existing zone must be imported, not
   recreated or replaced. Review all deletions, DNS targets, TTL/proxy changes,
   and zone-setting changes.
3. Run the same workflow on `main` with `apply`. The job generates and shows
   a fresh saved plan and applies it.
4. Confirm the drift-check step exits 0 and verify affected DNS/HTTPS behavior.

There is no automatic apply on push. To roll back, revert configuration through
a PR, review the CI plan, and dispatch `run-terraform` with `apply`. Do not
destroy the imported domain as a rollback.

## Static validation

These checks need no credentials or remote state:

```sh
terraform fmt -check -recursive -diff
terraform -chdir=terraform init -backend=false -input=false -lockfile=readonly
terraform -chdir=terraform validate -no-color
actionlint .github/workflows/test-terraform.yml .github/workflows/run-terraform.yml
```

State, saved plans, and `.terraform/` are ignored by Git. Live plans and
deployment must use CI with the configured remote backend and state locking.
