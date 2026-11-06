"""Shared validation for the scoped MorrowWallet deployment settings."""
import re
from pathlib import Path

DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
LABEL_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,61}[A-Za-z0-9])?")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(config, complete=False, require_enabled=False, authenticated_project=None):
    require(isinstance(config, dict), "Add helmfile settings through SOPS; see helmfile-app/README.md")
    try:
        cluster = config["cluster"]
        require(cluster["context"] == "bl-demeter", "Only bl-demeter is supported")
        require(cluster["name"] == "dmtr-cluster", "Use the bl-demeter cluster name")
        require(cluster["location"] == "us-central1", "Use the bl-demeter cluster location")
        require(isinstance(config["deployments"], dict), "Configure deployments as a mapping")
        require(set(config["deployments"]) == {"mainnet", "preprod"}, "Configure mainnet and preprod")
        require(config["kong"]["namespace"] == "kong", "Use the shared Kong namespace")
        require(config["kong"]["ingressClass"] == "kong", "Use the shared Kong ingress class")
        require("trustedCidrs" not in config["kong"], "Forwarded-IP trust is disabled; remove trustedCidrs")
        labels = config["kong"]["podSelector"]
        require(isinstance(labels, dict) and bool(labels), "Set the Kong gateway pod selector")
        for key, value in labels.items():
            require(isinstance(key, str) and isinstance(value, str), "Use string Kong pod labels")
            parts = key.split("/")
            require(len(parts) <= 2 and LABEL_NAME.fullmatch(parts[-1]), "Invalid Kong label name")
            if len(parts) == 2:
                require(len(parts[0]) <= 253 and all(DNS_LABEL.fullmatch(x) for x in parts[0].split(".")), "Invalid Kong label prefix")
            require(LABEL_NAME.fullmatch(value), "Invalid Kong label value")
        require(type(config["backendPort"]) is int and 0 < config["backendPort"] < 65536, "Set an integer backend port")
        require(re.fullmatch(r"[0-9]+[.][0-9]+[.][0-9]+", config["chart"]["version"]), "Pin a chart version")
        require(config["chart"]["source"] == "oci://ghcr.io/yoroi-classic/charts/cardano-wallet-backend", "Use the published backend chart")
        require(config["image"]["repository"] == "ghcr.io/yoroi-classic/cardano-wallet-backend", "Use the backend image repository")
        require(re.fullmatch(r"sha-[0-9a-f]{40}", config["image"]["tag"]), "Pin a full image commit tag")
        hosts = set()
        for network, app in config["deployments"].items():
            require(app["namespace"] == "morrowwallet-" + network, "Use the MorrowWallet network namespace")
            host = app["hostname"]
            require(isinstance(host, str) and host.endswith(".morrowwallet.com") and DNS_LABEL.fullmatch(host[:-len(".morrowwallet.com")]), "Use a valid morrowwallet.com hostname")
            hosts.add(host)
            require(type(app["replicas"]) is int and app["replicas"] == 1, "Review quotas and shared state before scaling")
            require(app["provider"] in {"koios", "blockfrost"}, "Use a supported chart provider")
            require(isinstance(app["existingSecret"], str), "Use a Secret name, not credential values")
            require(app["provider"] != "blockfrost" or app["existingSecret"], "Blockfrost requires an existing Secret")
        require(len(hosts) == 2, "Use distinct mainnet and preprod hostnames")
        require(type(config["enabled"]) is bool, "Set a boolean Helmfile enabled flag")
        if require_enabled:
            require(config["enabled"] is True, "Enable Helmfile only after setup is complete")
        if complete:
            require(config["image"]["tag"] != "sha-" + "0" * 40, "Set a published image commit tag")
            require(re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", cluster["project"]), "Set the GKE project")
            require(re.fullmatch(r"[^@\s]+@[^@\s]+[.][^@\s]+", config["acme"]["email"]), "Set the ACME contact email")
        if authenticated_project is not None:
            require(bool(authenticated_project) and cluster["project"] == authenticated_project, "The configured project must match the authenticated deployment identity")
    except (KeyError, TypeError) as error:
        raise ValueError("Missing or malformed Helmfile configuration") from error


def write_github_env(config, path):
    values = {"GKE_" + key.upper(): config["cluster"][key] for key in ("project", "name", "location", "context")}
    values["KONG_POD_SELECTOR"] = ",".join(key + "=" + value for key, value in sorted(config["kong"]["podSelector"].items()))
    for value in values.values():
        require(isinstance(value, str) and "\n" not in value and "\r" not in value, "Invalid cluster setting")
    with Path(path).open("a") as output:
        for key, value in values.items():
            output.write(key + "=" + value + "\n")
