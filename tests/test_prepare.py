"""Exercise configuration checks through the CI preparation entry point."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CONFIG = {
    'terraform': {
        'enabled': True,
        'backend': {
            'bucket': 'test-state', 'key': 'app.tfstate', 'use_lockfile': True,
            'endpoints': {'s3': 'https://' + '0' * 32 + '.r2.cloudflarestorage.com'},
        },
        'bootstrap': {'key': 'bootstrap.tfstate', 'jurisdiction': 'default'},
    },
    'cloudflare': {'account_id': '0' * 32,
                   'zones': [{'name': 'morrowwallet.com', 'zone_id': '1' * 32}]},
}


class Prepare(unittest.TestCase):
    def run_config(self, config):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.yaml').write_text(json.dumps(config))
            sops = root / 'sops'
            sops.write_text('#!/bin/sh\nif [ "$2" = "--output-type" ]; then cat config.yaml; fi\n')
            sops.chmod(0o755)
            result = subprocess.run(['bash', str(REPO / 'scripts/prepare-terraform.sh')],
                cwd=root, env=dict(os.environ, RUNNER_TEMP=directory,
                                  PATH=directory + ':' + os.environ['PATH']),
                capture_output=True, text=True)
            backends = {name: json.loads((root / name).read_text())
                        for name in ('backend.json', 'bootstrap-backend.json') if (root / name).exists()}
            return result, backends

    def test_valid_configuration_generates_separate_backends(self):
        result, backends = self.run_config(CONFIG)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(backends['backend.json']['key'], 'app.tfstate')
        self.assertEqual(backends['bootstrap-backend.json']['key'], 'bootstrap.tfstate')

    def test_equal_state_keys_rejected(self):
        config = copy.deepcopy(CONFIG)
        config['terraform']['bootstrap']['key'] = config['terraform']['backend']['key']
        result, backends = self.run_config(config)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(backends, {})

    def test_ids_and_bucket_reject_trailing_newlines(self):
        for field in ('account_id', 'zone_id', 'bucket'):
            with self.subTest(field=field):
                config = copy.deepcopy(CONFIG)
                if field == 'bucket':
                    config['terraform']['backend']['bucket'] += '\n'
                elif field == 'zone_id':
                    config['cloudflare']['zones'][0]['zone_id'] += '\n'
                else:
                    config['cloudflare']['account_id'] += '\n'
                result, backends = self.run_config(config)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(backends, {})
