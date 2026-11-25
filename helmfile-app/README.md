# Backend deployment on bl-demeter

This Helmfile deploys the existing `cardano-wallet-backend` chart for mainnet and
preprod. Kong and cert-manager are shared cluster services. It creates no new
cluster, ingress controller, or external-dns deployment.

Traffic flows from Terraform-managed DNS to the existing Kong load balancer.
Kong terminates TLS using a cert-manager TLS Secret and forwards HTTP to the
backend's ClusterIP Service. A namespace-local HTTP-01 Issuer obtains each
certificate through Kong, without Cloudflare credentials in Kubernetes.
The application and ACME solver ingresses explicitly opt out of external-dns.

The small `morrowwallet-policy` chart supplies the HTTP-01 Issuer and a
NetworkPolicy admitting backend traffic only from the configured gateway pods
in the `kong` namespace. Confirm `kong.podSelector` against the existing gateway
labels; CI requires matching ready pods. bl-demeter does not currently enforce
NetworkPolicies, so the policy takes effect only once enforcement is enabled.
`backendPort` sets both the application port and the policy port (3010 for the
pinned chart).

The backend uses explicit `single-hop` proxy trust: only Kong's appended client
address owns the rate-limit bucket; earlier client-supplied entries are ignored,
even for private client addresses. This requires the published image to include
single-hop support from backend PR #262. Kong must append the real client
address and must not trust arbitrary incoming forwarding headers. Without
NetworkPolicy enforcement, other pods in the cluster can reach the backend
directly and choose their rate-limit bucket with a forged forwarding header;
internet traffic still passes through Kong. This in-cluster risk is accepted.

CI requires the Kong proxy LoadBalancer Service to use
`externalTrafficPolicy: Local`, preserving client addresses rather than sharing
a node's rate-limit bucket. Set `kong.proxyService` to the actual proxy Service.
If the shared service needs changing, do so through its owning infrastructure
review/apply workflow before deploying this application. Confirm Kong's trusted-IP
configuration as part of setup. Set
`gateway.env.trusted_ips: "127.0.0.1,::1"` in the shared Kong Helm values so a
concrete environment value overrides any config file. CI requires this literal
override on every matched gateway, the official Kong image and default entrypoint,
and rejects `envFrom`/custom entrypoints rather than reading shared credentials.
Review other custom Kong/nginx settings before enabling this application. See
[the Kong source-IP guide](https://developer.konghq.com/kubernetes-ingress-controller/preserve-client-ip/).
Review [backend #229](https://github.com/yoroi-classic/cardano-wallet-backend/issues/229)
before scaling beyond one backend replica.

## Artifacts

The backend's `publish-image` workflow publishes tested commit tags for
`linux/amd64` and `linux/arm64` to
`ghcr.io/yoroi-classic/cardano-wallet-backend:sha-<full-commit>`.
Its `helm-chart` workflow publishes the OCI chart. The initial chart pin is
`0.1.3`; the image commit must be copied from a successful publication run.
Configure both packages as public for anonymous pulls. If private packages are
required, configure chart authentication and namespace image-pull Secrets
before deployment; this initial setup assumes public packages.

PR validation runs on every pull request to `main`, so required checks are not
skipped by path filters. It renders against the exact chart source commit recorded in
`pr-helmfile.yml`, using the deployment settings in `values.yaml`. It never
accesses the shared cluster. Update that source pin together
with the OCI chart version. Credentialed diff/apply runs pull the OCI artifact.

## CI credentials and cluster access

Deployment jobs run only from `main` and need no repository secrets. Add these
repository Actions variables:

| Variable | Value |
| --- | --- |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full Google Cloud Workload Identity Provider resource name |
| `GCP_SERVICE_ACCOUNT_EMAIL` | Email address of the deployer service account |

GitHub Actions authenticates through Workload Identity Federation; do not create
or store a service-account JSON key. Configure the provider to trust this
repository's `refs/heads/main` workflow identity and allow it to impersonate the
designated deployer service account. The workflow fails before authentication
if either variable is unset. The identity needs GKE cluster discovery access
(`roles/container.clusterViewer`). The identity also needs Kubernetes permissions to manage Helm
releases and their Deployments, Services, ServiceAccounts, ConfigMaps, Ingresses,
NetworkPolicies, and cert-manager Issuers/Certificates in `morrowwallet-mainnet`
and `morrowwallet-preprod`. CI sets `HELM_DRIVER=configmap`, so release state
uses ConfigMaps rather than Secrets. Do not grant the deployer direct Secret
read/write access: provider Secrets are operator-managed, and cert-manager
manages TLS Secrets. A deployer able to change workloads remains a trusted identity.
The configured GKE project must match the project hosting the target cluster.

Provision these namespaces and the identity's access through the owning
infrastructure process tracked in
[infrastructure #8](https://github.com/yoroi-classic/infrastructure/issues/8).
The cluster operator must provision these permissions before deployment; this
repository's Terraform and Helmfile workflows do not create namespaces or
cluster RBAC. No cluster-admin grant is required. The prerequisite check reads
the cluster-scoped `ingressclasses/kong` and
`customresourcedefinitions/issuers.cert-manager.io`, so grant `get` on those
resources. It also reads Services and Pods in the `kong` namespace for
prerequisite checks and load-balancer address discovery: grant `get`/`list` on
Services and `get`/`list`/`watch` on Pods, since readiness checks use
`kubectl wait`.

Confirm that the shared Kong access-log configuration preserves wallet privacy:
request paths and query strings can contain wallet addresses. This application
configuration does not change logging for other applications on the cluster.

## Settings

Deployment settings live in plain `helmfile-app/values.yaml`; none of them are
credentials. Edit it through a normal pull request. Merging a change to it on
`main` deploys it: `run-helmfile` applies on every push to `main` that touches
`helmfile-app/`, the deployment scripts, or these workflows. A credential-free
job reads `helmfile.enabled` first and skips the deployment while it is false.
Concurrent runs queue in one group and are never cancelled, so two quick merges
apply in order.

While `helmfile.enabled` is false, a manually dispatched `diff` still runs, so
the first apply can be previewed. Merges and dispatched `apply` stay off.

Before enabling, set the ACME contact email and confirm the image tag is a
published commit tag. Keep the chart and image pins explicit. Set
`helmfile.enabled: true` only after the packages, deployer identity,
namespaces, cluster permissions, and DNS records are ready.

Both releases start with one replica and anonymous Koios access. Selecting
Blockfrost requires an operator-managed Secret named by `existingSecret` in
each namespace. The chart reads project IDs/tokens from Secret references; do
not place provider credentials in Helm values. Review provider quotas and
shared rate-limit/cache behavior before increasing replicas.

## Diff, DNS, and apply

1. With `helmfile.enabled: false`, merge the ACME contact email and the
   published image tag; nothing deploys. Then run **Actions → run-helmfile**
   with `arguments: diff` (or **test-helmfile**). It runs while disabled,
   previews the first apply, and its prerequisite step reports the existing
   Kong load-balancer address.
2. Add DNS records through `sops config.yaml` (the Terraform configuration
   stays encrypted) and the existing Terraform
   plan/apply workflow. For an IPv4 load balancer, add these to the existing
   `cloudflare.zones[0].a_records` list, replacing the content with its address:

   ```yaml
   - name: api
     record_name: api.morrowwallet.com
     content: REPLACE_WITH_KONG_PUBLIC_IPV4
     proxied: false
   - name: api-preprod
     record_name: api-preprod.morrowwallet.com
     content: REPLACE_WITH_KONG_PUBLIC_IPV4
     proxied: false
   ```

   For a load-balancer hostname, add the entries to
   `cloudflare.zones[0].cname_records` instead of `a_records`, using that hostname
   as `content` and keeping the same names and `proxied: false`.
   Adopt any pre-existing records using their IDs rather than creating duplicates.
   Keep proxying disabled so public TLS terminates at Kong. No external-dns
   annotations create or update these records.
3. Confirm both DNS names resolve to Kong before applying the Helmfile. HTTP-01
   validation requires public port 80 to reach Kong. The temporary ACME solver
   route handles its challenge path; the backend route redirects HTTP to HTTPS.
4. Merge the change setting `helmfile.enabled: true`; `run-helmfile` applies it.
   **run-helmfile** with `arguments: apply` reruns it manually. Releases wait for readiness
   and roll back individually on Helm failure. The post-apply step waits for
   backend rollouts and certificate readiness, then verifies HTTPS health and the
   expected network/provider with a healthy chain status. HTTPS startup and
   transient provider errors retry for a bounded period; a network/provider mismatch
   fails immediately. Post-deploy failure does not
   roll back an otherwise successful application release; inspect cert-manager
   status and fix DNS/issuer configuration before retrying.
5. Run the diff again and confirm no remaining changes. Verify HTTPS `/health`
   and `/v1/status` on both hosts, including the reported Cardano network.
   Confirm HTTP redirects to HTTPS, Kong presents the expected certificate, and
   backend Services remain ClusterIP-only. Run endpoint checks from a trusted
   terminal without including wallet data in logs.

All cluster deployment and DNS changes use their respective CI
workflows. No live apply is performed by PR validation. To roll back, revert
settings or image/chart pins through a PR; merging it deploys the previous
version; do not delete namespaces, TLS Secrets, or unrelated cluster releases.
