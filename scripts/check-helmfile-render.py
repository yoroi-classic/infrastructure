#!/usr/bin/env python3
"""Check the rendered proxy boundary before accepting Helmfile changes."""
import argparse
from pathlib import Path
import yaml
from helmfile_config import require


def check(config, documents):
    deployments = [doc for doc in documents if doc.get("kind") == "Deployment"]
    policies = [doc for doc in documents if doc.get("kind") == "NetworkPolicy"]
    require(len(deployments) == 2 and len(policies) == 2, "Render both backend deployments and policies")
    for network in ("mainnet", "preprod"):
        instance = "cardano-wallet-backend-" + network
        apps = [doc for doc in deployments if doc["metadata"]["labels"].get("app.kubernetes.io/instance") == instance]
        rules = [doc for doc in policies if doc["spec"]["podSelector"]["matchLabels"].get("app.kubernetes.io/instance") == instance]
        require(len(apps) == 1 and len(rules) == 1, "Render one backend and policy for " + network)
        containers = apps[0]["spec"]["template"]["spec"]["containers"]
        backend = [container for container in containers if container["name"] == "cardano-wallet-backend"]
        require(len(backend) == 1, "Missing backend container for " + network)
        trust = [item for item in backend[0]["env"] if item["name"] == "TRUST_PROXY"]
        require(trust == [{"name": "TRUST_PROXY", "value": "single-hop"}], "Require single-hop proxy trust for " + network)
        expected = [{"from": [{
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": config["kong"]["namespace"]}},
            "podSelector": {"matchLabels": config["kong"]["podSelector"]},
        }], "ports": [{"protocol": "TCP", "port": config["backendPort"]}]}]
        require(rules[0]["spec"].get("policyTypes") == ["Ingress"] and rules[0]["spec"].get("ingress") == expected,
                "Restrict backend ingress to the configured Kong gateway pods for " + network)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("rendered")
    args = parser.parse_args()
    try:
        config = yaml.safe_load(Path(args.config).read_text())["helmfile"]
        documents = [doc for doc in yaml.safe_load_all(Path(args.rendered).read_text()) if doc]
        check(config, documents)
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit("Invalid Helmfile render: " + str(error)) from error
    print("Both networks preserve single-hop trust and gateway-only ingress")
