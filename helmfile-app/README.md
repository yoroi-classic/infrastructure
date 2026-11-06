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
labels; CI requires matching ready pods. The cluster must enforce NetworkPolicies.
`backendPort` sets both the application port and the policy port (3010 for the
pinned chart).

The backend uses explicit `single-hop` proxy trust: only Kong's appended client
address owns the rate-limit bucket; earlier client-supplied entries are ignored,
even for private client addresses. This requires the published image to include
single-hop support from backend PR #262. NetworkPolicy enforcement must restrict
all backend ingress to the selected gateway pods. Kong must append the real
client address and must not trust arbitrary incoming forwarding headers.

CI requires the Kong proxy LoadBalancer Service to use
`externalTrafficPolicy: Local`, preserving client addresses rather than sharing
a node's rate-limit bucket. Set `kong.proxyService` to the actual proxy Service.
If the shared service needs changing, do so through the Blink Labs infrastructure
review/apply workflow before deploying this application. Confirm Kong's trusted-IP
configuration and NetworkPolicy enforcement as part of setup. See
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
`pr-helmfile.yml`, using the readable deployment settings in `config.yaml`, or the public example
when those settings have not been added yet. It never decrypts production
configuration or accesses the shared cluster. Update that source pin together
with the OCI chart version. Credentialed diff/apply runs pull the OCI artifact.

## Protected CI environment and cluster access

Create the GitHub environment **helmfile**, restricted to deployments from
`main`, with required human reviewers. Add environment secrets:

| Secret | Value |
| --- | --- |
| `SOPS_AGE_KEY` | The existing MorrowWallet CI age identity authorized for `config.yaml` |
| `GCP_SERVICE_ACCOUNT` | JSON credentials for the identity used to deploy to `bl-demeter` |

Follow the existing Blink Labs GKE authentication pattern. The identity needs
GKE cluster discovery access, plus Kubernetes permissions to manage Helm
releases and their Deployments, Services, ServiceAccounts, ConfigMaps, Ingresses,
NetworkPolicies, and cert-manager Issuers/Certificates in `morrowwallet-mainnet`
and `morrowwallet-preprod`. CI sets `HELM_DRIVER=configmap`, so release state
uses ConfigMaps rather than Secrets. Do not grant the deployer direct Secret
read/write access: provider Secrets are operator-managed, and cert-manager
manages TLS Secrets. A deployer able to change workloads remains a trusted identity.
The configured GKE project must match the project in its service-account credentials.

Provision these namespaces and the identity's access using the existing Blink
Labs infrastructure workflow. This Helmfile does not create namespaces or
require cluster-admin. It also reads the `kong` IngressClass, the cert-manager
Issuer CRD, and Services/Pods in the `kong` namespace for prerequisite checks and
load-balancer address discovery. Grant `get`/`list` on those Services and
`get`/`list`/`watch` on those Pods, since readiness checks use `kubectl wait`.

Confirm that the shared Kong access-log configuration preserves wallet privacy:
request paths and query strings can contain wallet addresses. This application
configuration does not change logging for other applications on the cluster.

## Add settings through SOPS

Production settings live only under `helmfile` in the repository-root
`config.yaml`. The example is an onboarding/rendering fixture, not a second
production configuration file. The existing authenticated file must be updated
on a machine with an authorized age identity.

From the repository root on that machine:

```sh
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/morrowwallet-operator.txt"
morrow_settings=$(mktemp)
cp helmfile-app/config.yaml.example "$morrow_settings"
$EDITOR "$morrow_settings"
python3 scripts/configure-helmfile.py "$morrow_settings"
rm -f "$morrow_settings"
sops --decrypt config.yaml > /dev/null
```

Before running the helper, fill the GKE project and ACME contact email, replace
the zero image tag with a successfully published commit tag, set the real
`kong.proxyService` name and gateway pod selector, and confirm the
proposed hostnames `api.morrowwallet.com` and `api-preprod.morrowwallet.com`.
Keep the chart and image pins explicit. Set `helmfile.enabled: true` only after
the protected environment, packages, namespaces, and cluster permissions are
ready. The helper sets only the `helmfile` section through SOPS, preserving the
Terraform/Cloudflare settings and regenerating the file's integrity metadata.
Commit the resulting `config.yaml` through a reviewed PR. Subsequent edits use
`sops config.yaml`.

Both releases start with one replica and anonymous Koios access. Selecting
Blockfrost requires an operator-managed Secret named by `existingSecret` in
each namespace. The chart reads project IDs/tokens from Secret references; do
not place provider credentials in Helm values. Review provider quotas and
shared rate-limit/cache behavior before increasing replicas.

## Diff, DNS, and apply

1. Merge reviewed code and completed SOPS configuration. Run **Actions →
   test-helmfile** on `main`, or **run-helmfile** with `arguments: diff`.
   Approve the protected environment deployment. The prerequisite step reports
   the existing Kong load-balancer address.
2. Add DNS records through `sops config.yaml` and the existing Terraform
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
4. Run **Actions → run-helmfile** on `main`, choose `arguments: apply`, review
   the diff, and approve the protected deployment. Releases wait for readiness
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

All cluster deployment and DNS changes use their respective protected CI
workflows. No live apply is performed by PR validation. To roll back, revert
settings or image/chart pins through a reviewed PR and use the same diff/apply
workflow; do not delete namespaces, TLS Secrets, or unrelated cluster releases.
