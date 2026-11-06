#!/usr/bin/env python3
"""Verify the configured MorrowWallet releases after a CI apply."""
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from urllib.request import urlopen
import yaml

config = yaml.safe_load(Path("config.yaml").read_text())["helmfile"]
for network, app in config["deployments"].items():
    command = ["kubectl", "--context", config["cluster"]["context"], "--namespace", app["namespace"]]
    subprocess.run(command + ["rollout", "status", "deployment/cardano-wallet-backend", "--timeout=300s"], check=True)
    subprocess.run(command + ["wait", "--for=condition=Ready", "certificate/morrowwallet-tls", "--timeout=600s"], check=True)
    for path in ("/health", "/v1/status"):
        with urlopen("https://" + app["hostname"] + path, timeout=30) as response:
            final = urlsplit(response.url)
            if response.status != 200 or final.scheme != "https" or final.hostname != app["hostname"]:
                raise SystemExit("Unexpected HTTPS endpoint response for " + network)
            if path == "/v1/status":
                status = json.load(response)
                if status.get("network") != network or status.get("provider") != app["provider"]:
                    raise SystemExit("Backend reports the wrong network or provider for " + network)
                if status.get("chain") != "ok":
                    raise SystemExit("Chain provider is not healthy for " + network)
    print("Verified HTTPS health and network for " + network)
