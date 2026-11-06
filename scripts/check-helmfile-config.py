#!/usr/bin/env python3
"""Validate the target boundary before credentialed Helmfile operations."""
import argparse
import ipaddress
import re
from pathlib import Path
import yaml

parser = argparse.ArgumentParser()
parser.add_argument("--deploy", action="store_true")
parser.add_argument("--config", default="config.yaml")
args = parser.parse_args()


def require(condition, message):
    if not condition:
        raise SystemExit(message)


config = yaml.safe_load(Path(args.config).read_text()).get("helmfile")
if not isinstance(config, dict):
    raise SystemExit("Add the helmfile settings to config.yaml through SOPS; see helmfile-app/README.md")

require(config["cluster"]["context"] == "bl-demeter", "Only bl-demeter is supported")
require(set(config["deployments"]) == {"mainnet", "preprod"}, "Configure mainnet and preprod")
require(config["kong"]["namespace"] == "kong", "Use the shared Kong namespace")
require(config["kong"]["ingressClass"] == "kong", "Use the shared Kong ingress class")
require(re.fullmatch(r"[0-9]+[.][0-9]+[.][0-9]+", config["chart"]["version"]), "Pin a chart version")
require(config["image"]["repository"] == "ghcr.io/yoroi-classic/cardano-wallet-backend", "Use the backend image repository")
require(re.fullmatch(r"sha-[0-9a-f]{40}", config["image"]["tag"]), "Pin a full image commit tag")
for cidr in config["kong"]["trustedCidrs"].split(","):
    require(ipaddress.ip_network(cidr, strict=False).is_private, "Trust only private Kong source CIDRs")
require(len({app["hostname"] for app in config["deployments"].values()}) == 2, "Use distinct mainnet and preprod hostnames")
for network, app in config["deployments"].items():
    require(app["namespace"] == "morrowwallet-" + network, "Use the MorrowWallet network namespace")
    require(re.fullmatch(r"[a-z0-9-]+[.]morrowwallet[.]com", app["hostname"]), "Use a morrowwallet.com hostname")
    require(app["replicas"] == 1, "Review provider quotas and shared state before scaling")
    require(app["provider"] in {"koios", "blockfrost"}, "Use a supported chart provider")
    require(app["provider"] != "blockfrost" or app["existingSecret"], "Blockfrost requires an existing Secret")

if args.deploy:
    require(config["enabled"] is True, "Enable Helmfile only after deployment setup is complete")
    require(config["chart"]["source"] == "oci://ghcr.io/yoroi-classic/charts/cardano-wallet-backend", "Use the published backend chart")
    require(config["image"]["tag"] != "sha-" + "0" * 40, "Set a published image commit tag")
    require(re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", config["cluster"]["project"]), "Set the GKE project")
    require(re.fullmatch(r"[^@\s]+@[^@\s]+[.][^@\s]+", config["acme"]["email"]), "Set the ACME contact email")
print("Helmfile configuration validated")
