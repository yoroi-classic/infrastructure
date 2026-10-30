"""Exercise configuration checks through the CI preparation entry point."""
import copy
import json
import os
from pathlib import Path
import shutil
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

    def test_second_zone_is_rejected(self):
        config = copy.deepcopy(CONFIG)
        config['cloudflare']['zones'].append({'name': 'other.example', 'zone_id': '2' * 32})
        result, backends = self.run_config(config)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(backends, {})

    def test_terraform_configuration_precondition_rejects_second_zone(self):
        terraform = shutil.which('terraform')
        if terraform is None:
            self.skipTest('terraform is installed in the CI validation job')

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terraform_root = root / 'terraform'
            terraform_root.mkdir()
            for source in (REPO / 'terraform').glob('*.tf'):
                if source.name != 'backend.tf':
                    shutil.copy(source, terraform_root / source.name)
            shutil.copy(REPO / 'terraform/.terraform.lock.hcl', terraform_root)
            cache = terraform_root / '.terraform'
            cache.mkdir()
            source_cache = REPO / 'terraform/.terraform'
            for name in ('modules', 'providers'):
                source = source_cache / name
                if source.exists():
                    (cache / name).symlink_to(source, target_is_directory=True)

            config = copy.deepcopy(CONFIG)
            config['cloudflare']['zones'].append({
                'name': 'other.example', 'zone_id': '2' * 32, 'plan': 'free',
                'a_records': [], 'cname_records': [], 'mx_records': [], 'txt_records': [],
            })
            (root / 'config.yaml').write_text(json.dumps(config))

            init = subprocess.run(
                [terraform, f'-chdir={terraform_root}', 'init', '-backend=false',
                 '-input=false', '-lockfile=readonly'],
                capture_output=True, text=True,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            plan = subprocess.run(
                [terraform, f'-chdir={terraform_root}', 'plan', '-input=false',
                 '-refresh=false', '-target=terraform_data.configuration'],
                capture_output=True, text=True,
            )
            self.assertNotEqual(plan.returncode, 0, plan.stdout + plan.stderr)
            self.assertIn('Only the existing morrowwallet.com zone is supported', plan.stderr)

    def test_endpoint_for_another_account_is_rejected(self):
        config = copy.deepcopy(CONFIG)
        config['terraform']['backend']['endpoints']['s3'] = (
            'https://' + '1' * 32 + '.r2.cloudflarestorage.com'
        )
        result, backends = self.run_config(config)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(backends, {})

    def test_eu_jurisdiction_rejects_the_default_endpoint(self):
        config = copy.deepcopy(CONFIG)
        config['terraform']['bootstrap']['jurisdiction'] = 'eu'
        result, backends = self.run_config(config)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(backends, {})

    def test_disabling_lockfile_is_rejected(self):
        config = copy.deepcopy(CONFIG)
        config['terraform']['backend']['use_lockfile'] = False
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
