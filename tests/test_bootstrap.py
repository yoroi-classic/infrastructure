"""Exercise the CI bootstrap entry point without Cloudflare access."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]

# Commands model the externally observable outcomes, not Terraform internals.
FAKE = '''#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
case = os.environ["BOOTSTRAP_CASE"]
if name == "terraform":
    backend = pathlib.Path("terraform/bootstrap/backend.tf")
    args.append("backend_exists=" + str(backend.exists()).lower())
    backend_config = next((arg.split("=", 1)[1] for arg in args if arg.startswith("-backend-config=")), None)
    backend_key = None
    if backend_config is not None:
        config_path = pathlib.Path(backend_config)
        if config_path.exists():
            backend_key = json.loads(config_path.read_text()).get("key")
    args.append("backend_key=" + str(backend_key))
with open(os.environ["COMMAND_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
if name == "aws":
    if case in ("remote", "remote_replace"):
        sys.exit(0)
    print("An error occurred (403)" if case == "denied" else "An error occurred (404)", file=sys.stderr)
    sys.exit(1)
if name == "curl":
    print("200" if case == "recover" else "403" if case == "bucket_denied" else "404", end="")
if name == "terraform" and "show" in args:
    print(json.dumps({"resource_changes": [{"change": {"actions": ["delete", "create"] if case in ("replace", "remote_replace") else ["create"]}}]}))
if name == "terraform" and "plan" in args and "-detailed-exitcode" in args and case == "drift":
    sys.exit(2)
'''


class Bootstrap(unittest.TestCase):
    def run_case(self, case):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'terraform/bootstrap').mkdir(parents=True)
            shutil.copy(REPO / 'terraform/bootstrap/backend.tf.example', root / 'terraform/bootstrap')
            (root / 'bootstrap-backend.json').write_text(json.dumps({'key': 'bootstrap.tfstate'}))
            (root / 'backend.json').write_text(json.dumps({'key': 'application.tfstate'}))
            (root / 'bin').mkdir()
            for name in ('aws', 'curl', 'terraform'):
                command = root / 'bin' / name
                command.write_text(FAKE)
                command.chmod(0o755)
            (root / 'config.json').write_text(json.dumps({
                'terraform': {'backend': {'bucket': 'test-state', 'endpoints': {'s3': 'https://example.invalid'}},
                              'bootstrap': {'key': 'bootstrap.tfstate', 'jurisdiction': 'default'}},
                'cloudflare': {'account_id': '00000000000000000000000000000000'}}))
            env = dict(os.environ, PATH=f'{root}/bin:{os.environ["PATH"]}', RUNNER_TEMP=str(root),
                       BOOTSTRAP_CASE=case, COMMAND_LOG=str(root / 'commands'), CLOUDFLARE_API_TOKEN='test-only')
            result = subprocess.run(['bash', str(REPO / 'scripts/bootstrap-terraform.sh')],
                                    cwd=root, env=env, capture_output=True, text=True)
            commands = [json.loads(line) for line in (root / 'commands').read_text().splitlines()]
            return result, commands

    def test_create_then_migrate(self):
        result, commands = self.run_case('new')
        self.assertEqual(result.returncode, 0, result.stderr)
        apply = next(i for i, cmd in enumerate(commands) if 'apply' in cmd)
        migration = next(i for i, cmd in enumerate(commands) if '-migrate-state' in cmd)
        self.assertLess(apply, migration)
        self.assertIn('backend_exists=true', commands[migration])
        self.assertIn('backend_key=bootstrap.tfstate', commands[migration])
        self.assertFalse(any('import' in cmd for cmd in commands))

    def test_existing_remote_state_never_uses_local_bootstrap(self):
        result, commands = self.run_case('remote')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(cmd[0] == 'curl' or 'import' in cmd or '-migrate-state' in cmd for cmd in commands))
        remote_init = next(cmd for cmd in commands if 'init' in cmd)
        self.assertIn('backend_exists=true', remote_init)
        self.assertTrue(any(arg.startswith('-backend-config=') for arg in remote_init))
        self.assertIn('backend_key=bootstrap.tfstate', remote_init)

    def test_interrupted_bootstrap_imports_before_apply_and_migration(self):
        result, commands = self.run_case('recover')
        self.assertEqual(result.returncode, 0, result.stderr)
        adoption = next(i for i, cmd in enumerate(commands) if 'import' in cmd)
        apply = next(i for i, cmd in enumerate(commands) if 'apply' in cmd)
        migration = next(i for i, cmd in enumerate(commands) if '-migrate-state' in cmd)
        self.assertLess(adoption, apply)
        self.assertLess(apply, migration)
        self.assertIn('backend_exists=true', commands[migration])
        self.assertIn('backend_key=bootstrap.tfstate', commands[migration])

    def test_denied_state_access_stops_before_terraform(self):
        result, commands = self.run_case('denied')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([cmd[0] for cmd in commands], ['aws'])

    def test_bucket_replacement_is_rejected_before_apply(self):
        result, commands = self.run_case('replace')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('apply' in cmd or '-migrate-state' in cmd for cmd in commands))

    def test_remote_bucket_replacement_is_rejected_before_apply(self):
        result, commands = self.run_case('remote_replace')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('apply' in cmd for cmd in commands))

    def test_bucket_api_denial_stops_before_plan_or_apply(self):
        result, commands = self.run_case('bucket_denied')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any(
            cmd[0] == 'curl' and
            'https://api.cloudflare.com/client/v4/accounts/00000000000000000000000000000000/r2/buckets/test-state' in cmd
            for cmd in commands
        ))
        self.assertFalse(any('plan' in cmd or 'apply' in cmd for cmd in commands))

    def test_drift_plan_exit_two_fails_bootstrap(self):
        result, commands = self.run_case('drift')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any('plan' in cmd and '-detailed-exitcode' in cmd for cmd in commands))


if __name__ == '__main__':
    unittest.main()
