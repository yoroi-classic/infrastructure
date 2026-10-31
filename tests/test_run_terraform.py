"""Exercise the application Terraform workflow command with a fake CLI."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'scripts/run-terraform.sh'
FAKE_TERRAFORM = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if args and args[0] == "init":
    config_arg = next((arg for arg in args if arg.startswith("-backend-config=")), None)
    config_path = pathlib.Path(config_arg.split("=", 1)[1]) if config_arg else None
    key = json.loads(config_path.read_text()).get("key") if config_path and config_path.exists() else None
    with open(os.environ["COMMAND_LOG"], "a") as log:
        log.write(json.dumps({"args": args, "backend_key": key}) + "\\n")
else:
    with open(os.environ["COMMAND_LOG"], "a") as log:
        log.write(json.dumps({"args": args}) + "\\n")
    if args and args[0] == "plan" and "-detailed-exitcode" in args and os.environ.get("DRIFT") == "1":
        sys.exit(2)
'''


class RunTerraform(unittest.TestCase):
    def run_operation(self, operation, drift=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bin').mkdir()
            fake = root / 'bin/terraform'
            fake.write_text(FAKE_TERRAFORM)
            fake.chmod(0o755)
            (root / 'backend.json').write_text(json.dumps({'key': 'application.tfstate'}))
            (root / 'bootstrap-backend.json').write_text(json.dumps({'key': 'bootstrap.tfstate'}))
            log = root / 'commands.jsonl'
            env = dict(os.environ, PATH=f'{root}/bin:{os.environ["PATH"]}',
                       RUNNER_TEMP=str(root), OPERATION=operation, COMMAND_LOG=str(log))
            if drift:
                env['DRIFT'] = '1'
            result = subprocess.run(['bash', str(SCRIPT)], cwd=REPO / 'terraform', env=env,
                                    capture_output=True, text=True)
            commands = [json.loads(line) for line in log.read_text().splitlines()]
            return result, commands

    def test_plan_uses_application_state(self):
        result, commands = self.run_operation('plan')
        self.assertEqual(result.returncode, 0, result.stderr)
        init = next(command for command in commands if command['args'][0] == 'init')
        self.assertEqual(init['backend_key'], 'application.tfstate')
        self.assertFalse(any(command['args'][0] == 'apply' for command in commands))

    def test_apply_uses_application_state(self):
        result, commands = self.run_operation('apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        init = next(command for command in commands if command['args'][0] == 'init')
        self.assertEqual(init['backend_key'], 'application.tfstate')
        self.assertTrue(any(command['args'][0] == 'apply' for command in commands))

    def test_apply_fails_when_post_apply_drift_remains(self):
        result, commands = self.run_operation('apply', drift=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        drift_plans = [
            command for command in commands
            if command['args'][0] == 'plan' and '-detailed-exitcode' in command['args']
        ]
        self.assertEqual(len(drift_plans), 1)


if __name__ == '__main__':
    unittest.main()
