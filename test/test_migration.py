import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'docs/migration/upstream-v3.1.3.json'
INVENTORY = ROOT / 'docs/migration/upstream-v3.1.3-files.json'


class SourceCheckpoint(unittest.TestCase):
    def run_check(self, *args):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('SHEPHERDR_', 'ANTHROPIC_', 'CLAUDE_', 'AZURE_', 'OPENAI_'))}
        result = subprocess.run([sys.executable, str(ROOT / 'bin/check-migration'), *map(str, args)],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        return result, json.loads(result.stdout)

    def fixture(self, source, mutate, flag):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'contract.json'
            data = json.loads(source.read_text())
            mutate(data)
            path.write_text(json.dumps(data))
            return self.run_check(flag, path)

    def test_source_is_complete_without_claiming_candidate_readiness(self):
        result, observed = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr, '')
        self.assertEqual(observed['source_validation'], 'passed')
        self.assertEqual(observed['candidate_readiness'], 'blocked')
        self.assertEqual(observed['requirements'], 40)
        self.assertEqual(observed['file_dispositions'], 121)
        self.assertEqual((observed['phase'], observed['source_deltas']), ('S1', 8))

    def test_candidate_gate_refuses_even_when_source_validation_passes(self):
        result, observed = self.run_check('--require-ready')
        self.assertEqual(result.returncode, 3)
        self.assertEqual(observed['source_validation'], 'passed')
        self.assertEqual(observed['candidate_readiness'], 'blocked')
        self.assertIn('S1 is source-only', result.stderr)
        self.assertIn('Complete required ports', result.stderr)

    def test_existing_discovery_cannot_be_dropped(self):
        def remove(data):
            data['requirements'] = [row for row in data['requirements'] if row['id'] != 'azure-discovery']
        result, observed = self.fixture(MANIFEST, remove, '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(observed['source_validation'], 'failed')
        self.assertIn('Required behavior inventory', observed['error'])

    def test_required_pr3_source_cannot_be_substituted(self):
        result, observed = self.fixture(MANIFEST, lambda data: data['inputs'].update(P='0' * 40), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(observed['candidate_readiness'], 'blocked')
        self.assertIn('Fixed inputs', observed['error'])

    def test_original_source_hash_cannot_be_rewritten(self):
        def corrupt(data):
            next(row for row in data['files'] if row['after'])['after']['sha256'] = '0' * 64
        result, observed = self.fixture(INVENTORY, corrupt, '--inventory')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(observed['source_validation'], 'failed')
        self.assertIn('Original source hash', observed['error'])

    def test_admitted_phase_content_cannot_drift(self):
        def corrupt(data):
            next(row for row in data['source_deltas'] if row['path'].endswith('/forge.py'))['sha256'] = '0' * 64
        result, observed = self.fixture(MANIFEST, corrupt, '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(observed['candidate_readiness'], 'blocked')
        self.assertIn('admitted phase content at mods/tasks/bin/herdr_task/forge.py', observed['error'])

    def test_phase_cannot_roll_back_over_its_changes(self):
        result, observed = self.fixture(MANIFEST, lambda data: data.update(phase='S0'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase S0', observed['error'])

    def test_an_unadmitted_owner_cannot_join_the_phase(self):
        def widen(data):
            data['source_deltas'].append({'phase': 'S1', 'path': 'mods/tasks/bin/herdr_task/ghnews.py',
                                          'upstream_blob': None, 'sha256': '0' * 64})
        result, observed = self.fixture(MANIFEST, widen, '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase S1', observed['error'])

    def test_a_delta_cannot_drop_its_upstream_provenance(self):
        def rewrite(data):
            next(row for row in data['source_deltas'] if row['path'].endswith('/github.py'))['upstream_blob'] = None
        result, observed = self.fixture(MANIFEST, rewrite, '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('upstream provenance changed at mods/tasks/bin/herdr_task/github.py', observed['error'])
