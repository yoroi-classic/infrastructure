#!/usr/bin/env python3
"""Check the rendered proxy boundary before accepting Helmfile changes."""
import argparse
from collections import Counter
from pathlib import Path
import yaml
from helmfile_config import require


def check_dns_ignore(annotations, resource):
    for prefix in ("external-dns.alpha.kubernetes.io", "external-dns.kubernetes.io"):
        require(annotations.get(prefix + "/controller") == "ignore", "Exclude " + resource + " from external-dns")


def check_ingress(config, network, route):
    hostname = config["deployments"][network]["hostname"]
    annotations = route["metadata"].get("annotations", {})
    check_dns_ignore(annotations, "backend Ingress " + network)
    for name, value in {"cert-manager.io/issuer": "morrowwallet-acme",
                        "konghq.com/protocols": "https",
                        "konghq.com/https-redirect-status-code": "308",
                        "konghq.com/strip-path": "false"}.items():
        require(annotations.get(name) == value, "Require Kong HTTPS annotation " + name + " for " + network)
    spec = route["spec"]
    require(spec.get("ingressClassName") == config["kong"]["ingressClass"], "Use the Kong ingress class for " + network)
    require(spec.get("tls") == [{"secretName": "morrowwallet-tls", "hosts": [hostname]}], "Bind the expected TLS certificate and hostname for " + network)
    paths = [{"path": "/", "pathType": "Prefix", "backend": {"service": {"name": "cardano-wallet-backend", "port": {"number": 80}}}}]
    require(spec.get("rules") == [{"host": hostname, "http": {"paths": paths}}] and not spec.get("defaultBackend"),
            "Route only the configured hostname to the backend Service for " + network)


def check_service(service, pod_labels):
    spec = service["spec"]
    require(service["metadata"]["name"] == "cardano-wallet-backend", "Use the Ingress backend Service name")
    require(spec.get("type", "ClusterIP") == "ClusterIP" and not spec.get("externalIPs"), "Expose the backend only through its internal ClusterIP Service")
    selector = spec["selector"]
    require(selector.get("app.kubernetes.io/instance") == pod_labels.get("app.kubernetes.io/instance") and
            all(pod_labels.get(key) == value for key, value in selector.items()), "Service must select the backend pods")
    require(spec["ports"] == [{"port": 80, "targetPort": "http", "protocol": "TCP", "name": "http"}], "Use the internal backend Service port")


def check(config, documents):
    expected = Counter({"Deployment": 2, "Service": 2, "ServiceAccount": 2,
                        "Ingress": 2, "NetworkPolicy": 2, "Issuer": 2})
    require(Counter(doc.get("kind") for doc in documents) == expected,
            "Render only the two backends and their approved supporting resources")
    deployments = [doc for doc in documents if doc.get("kind") == "Deployment"]
    policies = [doc for doc in documents if doc.get("kind") == "NetworkPolicy"]
    require(len(deployments) == 2 and len(policies) == 2, "Render both backend deployments and policies")
    services = [doc for doc in documents if doc.get("kind") == "Service"]
    require(len(services) == 2, "Render both backend Services")
    ingresses = [doc for doc in documents if doc.get("kind") == "Ingress"]
    issuers = [doc for doc in documents if doc.get("kind") == "Issuer" and doc["metadata"]["name"] == "morrowwallet-acme"]
    require(len(issuers) == 2, "Render both ACME issuers")
    for issuer in issuers:
        solvers = issuer["spec"]["acme"]["solvers"]
        require(len(solvers) == 1, "Use one HTTP-01 ACME solver")
        require(solvers[0]["http01"]["ingress"].get("ingressClassName") == config["kong"]["ingressClass"], "Use Kong for HTTP-01 certificate validation")
        annotations = solvers[0]["http01"]["ingress"]["ingressTemplate"]["metadata"].get("annotations", {})
        check_dns_ignore(annotations, "ACME solver")
    for network in ("mainnet", "preprod"):
        instance = "cardano-wallet-backend-" + network
        apps = [doc for doc in deployments if doc["metadata"]["labels"].get("app.kubernetes.io/instance") == instance]
        rules = [doc for doc in policies if doc["spec"]["podSelector"]["matchLabels"].get("app.kubernetes.io/instance") == instance]
        require(len(apps) == 1 and len(rules) == 1, "Render one backend and policy for " + network)
        selector = {"matchLabels": {"app.kubernetes.io/instance": instance}}
        require(rules[0]["spec"]["podSelector"] == selector, "Select only backend pods for " + network)
        pod_labels = apps[0]["spec"]["template"]["metadata"]["labels"]
        require(pod_labels.get("app.kubernetes.io/instance") == instance, "Policy must select backend pod-template labels for " + network)
        routes = [doc for doc in ingresses if doc["metadata"]["labels"].get("app.kubernetes.io/instance") == instance]
        require(len(routes) == 1, "Render one backend Ingress for " + network)
        check_ingress(config, network, routes[0])
        targets = [doc for doc in services if doc["metadata"]["labels"].get("app.kubernetes.io/instance") == instance]
        require(len(targets) == 1, "Render one backend Service for " + network)
        check_service(targets[0], pod_labels)
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
