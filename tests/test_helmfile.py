"""Deployment guard and public-endpoint regression tests; no cluster credentials."""
import importlib.util
import copy
import json
import io
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from helmfile_config import validate, write_github_env

spec = importlib.util.spec_from_file_location("verify_helmfile", ROOT / "scripts/verify-helmfile.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def ready():
    config = yaml.safe_load((ROOT / "helmfile-app/config.yaml.example").read_text())["helmfile"]
    config["enabled"] = True
    config["kong"]["proxyService"] = "kong-gateway-proxy"
    config["cluster"]["project"] = "test-deployment-project"
    config["acme"]["email"] = "ops@example.invalid"
    config["image"]["tag"] = "sha-" + "1" * 40
    return config


class DeploymentGuards(unittest.TestCase):
    def test_ready_and_onboarding(self):
        validate(ready(), complete=True, require_enabled=True)
        config = ready()
        config["enabled"] = False
        validate(config, complete=True)
        with self.assertRaises(ValueError):
            validate(config, complete=True, require_enabled=True)

    def test_reject_unsafe_targets_and_settings(self):
        changes = [
            (("enabled",), False),
            (("deployments",), {"mainnet": {}}),
            (("kong", "namespace"), "default"),
            (("kong", "ingressClass"), "traefik"),
            (("kong", "proxyService"), "replace-with-kong-proxy-service"),
            (("chart", "version"), ">=0.1.0"),
            (("cluster", "context"), "default"),
            (("cluster", "name"), "another-cluster"),
            (("cluster", "location"), "us-east1"),
            (("cluster", "project"), "valid-project\nINJECTED=yes"),
            (("cluster", "project"), "REPLACE_WITH_GCP_PROJECT"),
            (("kong", "podSelector"), {}),
            (("kong", "podSelector"), {"bad,label": "gateway"}),
            (("kong", "trustedCidrs"), ["10.0.0.0/8"]),
            (("chart", "source"), "/tmp/untrusted-chart"),
            (("image", "repository"), "example.invalid/backend"),
            (("image", "tag"), "latest"),
            (("image", "tag"), "sha-" + "0" * 40),
            (("acme", "email"), "REPLACE_WITH_ACME_EMAIL"),
            (("backendPort",), True),
            (("deployments", "mainnet", "namespace"), "kong"),
            (("deployments", "mainnet", "hostname"), "api-preprod.morrowwallet.com"),
            (("deployments", "mainnet", "hostname"), "api.dmtr.demeter.run"),
            (("deployments", "mainnet", "hostname"), "-api.morrowwallet.com"),
            (("deployments", "mainnet", "hostname"), "a" * 64 + ".morrowwallet.com"),
            (("deployments", "mainnet", "replicas"), True),
            (("deployments", "mainnet", "replicas"), 3),
            (("deployments", "mainnet", "provider"), "unknown"),
            (("deployments", "mainnet", "provider"), "blockfrost"),
        ]
        for path, value in changes:
            with self.subTest(path=path, value=value):
                config = ready()
                target = config
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                result = self.run_cli(config)
                self.assertNotEqual(result.returncode, 0, result.stdout)

    def run_cli(self, config, *options):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump({"helmfile": config}))
            return subprocess.run([sys.executable, str(ROOT / "scripts/check-helmfile-config.py"),
                                   "--deploy", "--config", str(path), *options],
                                  capture_output=True, text=True)

    def test_cli_exports_and_identity_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "github-env"
            result = self.run_cli(ready(), "--github-env", str(env), "--authenticated-project", "test-deployment-project")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("GKE_CONTEXT=bl-demeter\n", env.read_text())
            self.assertIn("KONG_PROXY_SERVICE=kong-gateway-proxy\n", env.read_text())
            result = self.run_cli(ready(), "--authenticated-project", "another-project")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("authenticated deployment identity", result.stderr)
        config = ready()
        del config["chart"]["version"]
        result = self.run_cli(config)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("version", result.stderr)

    def test_identity_check_precedes_cluster_credentials(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/common-helmfile.yml").read_text())
        steps = workflow["jobs"]["helmfile"]["steps"]
        binding = next(i for i, step in enumerate(steps) if "--authenticated-project" in step.get("run", ""))
        credentials = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("google-github-actions/get-gke-credentials@"))
        self.assertLess(binding, credentials)
        self.assertIn("${{ steps.auth.outputs.project_id }}", steps[binding]["env"]["AUTHENTICATED_PROJECT"])

    def test_authenticated_project_binding(self):
        config = ready()
        validate(config, complete=True, authenticated_project=config["cluster"]["project"])
        for project in ("", "another-project"):
            with self.subTest(project=project), self.assertRaises(ValueError):
                validate(config, complete=True, authenticated_project=project)

    def test_env_write_is_atomic_on_newline_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "github-env"
            config = ready()
            config["cluster"]["project"] += "\nINJECTED=yes"
            with self.assertRaises(ValueError):
                write_github_env(config, path)
            self.assertFalse(path.exists())
            write_github_env(ready(), path)
            self.assertIn("GKE_CONTEXT=bl-demeter\n", path.read_text())


class GatewayPrerequisites(unittest.TestCase):
    def test_explicit_override_and_rejection_of_unverified_sources(self):
        proxy = {"name": "proxy", "image": "kong:3.9", "env": [
            {"name": "KONG_TRUSTED_IPS", "value": "127.0.0.1,::1"}]}
        def check(container):
            pods = {"items": [{"spec": {"containers": [container]}}]}
            return subprocess.run([sys.executable, str(ROOT / "scripts/check-kong.py")],
                                  input=json.dumps(pods), capture_output=True, text=True)
        self.assertEqual(check(proxy).returncode, 0)
        for change in ({"env": []},
                       {"env": [{"name": "KONG_TRUSTED_IPS", "value": "0.0.0.0/0"}]},
                       {"env": [{"name": "KONG_TRUSTED_IPS", "valueFrom": {"secretKeyRef": {"name": "test-only", "key": "trusted"}}}]},
                       {"envFrom": [{"configMapRef": {"name": "test-only"}}]},
                       {"command": ["sh", "-c", "kong start"]},
                       {"args": ["--conf", "/custom.conf"]},
                       {"image": "example.invalid/custom-kong:latest"}):
            with self.subTest(change=change):
                candidate = copy.deepcopy(proxy)
                candidate.update(change)
                self.assertNotEqual(check(candidate).returncode, 0)


class EndpointVerification(unittest.TestCase):
    def response(self, status=None, hostname="api.morrowwallet.com"):
        response = MagicMock()
        response.__enter__.return_value = response
        response.url = "https://" + hostname + "/v1/status"
        response.status = 200
        response.read.return_value = json.dumps(status or {"network": "mainnet", "provider": "koios", "chain": "ok"})
        return response

    def test_network_provider_and_redirect_mismatches_fail_without_retry(self):
        for status in ({"network": "preprod", "provider": "koios", "chain": "ok"},
                       {"network": "mainnet", "provider": "blockfrost", "chain": "ok"}):
            with self.subTest(status=status), patch.object(verify, "urlopen", return_value=self.response(status)) as get, patch.object(verify.time, "sleep"):
                with self.assertRaisesRegex(ValueError, "wrong network or provider"):
                    verify.check_endpoint("mainnet", ready()["deployments"]["mainnet"], "/v1/status")
                self.assertEqual(get.call_count, 1)
        with patch.object(verify, "urlopen", return_value=self.response(hostname="other.example")):
            with self.assertRaisesRegex(ValueError, "Unexpected HTTPS"):
                verify.check_endpoint("mainnet", ready()["deployments"]["mainnet"], "/health")

    def test_startup_tls_and_http_errors_retry_then_recover(self):
        errors = [URLError("certificate not ready"), HTTPError("https://api.morrowwallet.com", 503, "warming up", {}, None)]
        with patch.object(verify, "urlopen", side_effect=errors + [self.response()]) as get, patch.object(verify.time, "sleep") as sleep:
            verify.check_endpoint("mainnet", ready()["deployments"]["mainnet"], "/v1/status")
            self.assertEqual(get.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_stale_chain_fails_after_bounded_retries_with_context(self):
        with patch.object(verify, "urlopen", return_value=self.response({"network": "mainnet", "provider": "koios", "chain": "stale"})) as get, patch.object(verify.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "mainnet /v1/status: Chain provider"):
                verify.check_endpoint("mainnet", ready()["deployments"]["mainnet"], "/v1/status", attempts=2)
            self.assertEqual(get.call_count, 2)

    def test_rollout_and_certificate_waits_precede_https(self):
        calls = []
        config = ready()
        config["deployments"] = {"mainnet": config["deployments"]["mainnet"]}
        with patch.object(verify.subprocess, "run", side_effect=lambda command, **kwargs: calls.append(command)), patch.object(verify, "check_endpoint", side_effect=lambda *args: calls.append(args[-1])), patch("sys.stdout", new=io.StringIO()):
            verify.verify(config)
        self.assertIn("deployment/cardano-wallet-backend", calls[0])
        self.assertIn("certificate/morrowwallet-tls", calls[1])
        self.assertEqual(calls[2:], ["/health", "/v1/status"])
