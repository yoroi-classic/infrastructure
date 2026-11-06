#!/usr/bin/env python3
"""Verify the configured MorrowWallet releases after a CI apply."""
import json
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen
import yaml


def check_endpoint(network, app, path, attempts=12):
    for attempt in range(attempts):
        try:
            with urlopen("https://" + app["hostname"] + path, timeout=10) as response:
                final = urlsplit(response.url)
                if final.scheme != "https" or final.hostname != app["hostname"]:
                    raise ValueError("Unexpected HTTPS endpoint for " + network)
                if response.status != 200:
                    raise OSError("Unexpected HTTP status " + str(response.status))
                if path == "/v1/status":
                    status = json.load(response)
                    if status.get("network") != network or status.get("provider") != app["provider"]:
                        raise ValueError("Backend reports the wrong network or provider for " + network)
                    if status.get("chain") != "ok":
                        raise OSError("Chain provider is not healthy")
                return
        except (URLError, OSError, json.JSONDecodeError) as error:
            if attempt == attempts - 1:
                raise RuntimeError("HTTPS verification failed for " + network + " " + path + ": " + str(error)) from error
            time.sleep(5)


def verify(config):
    for network, app in config["deployments"].items():
        command = ["kubectl", "--context", config["cluster"]["context"], "--namespace", app["namespace"]]
        subprocess.run(command + ["rollout", "status", "deployment/cardano-wallet-backend", "--timeout=300s"], check=True)
        subprocess.run(command + ["wait", "--for=condition=Ready", "certificate/morrowwallet-tls", "--timeout=600s"], check=True)
        for path in ("/health", "/v1/status"):
            check_endpoint(network, app, path)
        print("Verified HTTPS health and network for " + network)


if __name__ == "__main__":
    try:
        verify(yaml.safe_load(Path("config.yaml").read_text())["helmfile"])
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
