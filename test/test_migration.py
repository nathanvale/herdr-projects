import json
import os
from pathlib import Path
import shutil
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
        self.assertEqual((observed['phase'], observed['source_deltas']), ('C1', 24))

    def test_candidate_gate_refuses_even_when_source_validation_passes(self):
        result, observed = self.run_check('--require-ready')
        self.assertEqual(result.returncode, 3)
        self.assertEqual(observed['source_validation'], 'passed')
        self.assertEqual(observed['candidate_readiness'], 'blocked')
        self.assertIn('C1 is source-only', result.stderr)
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
            next(row for row in data['source_deltas'] if row['path'].endswith('/providers.py'))['sha256'] = '0' * 64
        result, observed = self.fixture(MANIFEST, corrupt, '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(observed['candidate_readiness'], 'blocked')
        self.assertIn('admitted phase content at mods/tasks/bin/herdr_task/providers.py', observed['error'])

    def test_phase_cannot_roll_back_over_its_changes(self):
        result, observed = self.fixture(MANIFEST, lambda data: data.update(phase='S0'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase S0', observed['error'])

    def test_an_unadmitted_owner_cannot_join_the_phase(self):
        def widen(data):
            data['source_deltas'].append({'phase': 'C1', 'path': 'mods/tasks/bin/herdr_task/revive.py',
                                          'upstream_blob': None, 'sha256': '0' * 64})
        result, observed = self.fixture(MANIFEST, widen, '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase C1', observed['error'])

    def test_a_delta_cannot_drop_its_upstream_provenance(self):
        def rewrite(data):
            next(row for row in data['source_deltas'] if row['path'].endswith('/takeover.py'))['upstream_blob'] = None
        result, observed = self.fixture(MANIFEST, rewrite, '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('upstream provenance changed at mods/tasks/bin/herdr_task/takeover.py', observed['error'])

    def test_a_ready_claim_stays_refused_in_an_admitted_phase(self):
        result, observed = self.fixture(MANIFEST, lambda data: data.update(candidate_readiness='ready'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(observed['candidate_readiness'], 'blocked')
        self.assertIn('must remain a blocked', observed['error'])


class NativeFoundation(unittest.TestCase):
    """The checker over a throwaway copy of this commit (a clone borrowing this repository's
    objects, so the fixed inputs are there): only the admitted phase paths may differ from exact
    U, and only as the manifest pins them."""

    @classmethod
    def setUpClass(cls):
        cls.copy = Path(tempfile.mkdtemp()) / 'copy'
        cls.addClassCleanup(shutil.rmtree, cls.copy.parent, True)
        subprocess.run(['git', 'clone', '-q', '--shared', str(ROOT), str(cls.copy)], check=True, capture_output=True, timeout=120)

    def check(self):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('SHEPHERDR_', 'ANTHROPIC_', 'CLAUDE_', 'AZURE_', 'OPENAI_'))}
        result = subprocess.run([sys.executable, str(self.copy / 'bin/check-migration')],
                                cwd=self.copy, env=env, capture_output=True, text=True, timeout=120)
        return result.returncode, json.loads(result.stdout)

    def changed(self, path, change):
        """The checker's answer with one file of the copy changed; the file is put back after."""
        target = self.copy / path
        data, mode = target.read_bytes(), target.stat().st_mode
        try:
            change(target)
            return self.check()
        finally:
            if target.is_symlink():
                target.unlink()
            target.write_bytes(data)
            target.chmod(mode)

    def test_the_copy_passes_as_committed(self):
        code, observed = self.check()
        self.assertEqual((code, observed['source_validation'], observed['candidate_readiness']), (0, 'passed', 'blocked'), observed)

    def test_an_unadmitted_upstream_path_still_refuses(self):
        code, observed = self.changed('keys.json', lambda target: target.write_bytes(target.read_bytes() + b'\n'))
        self.assertEqual((code, observed['candidate_readiness']), (1, 'blocked'))
        self.assertEqual(observed['error'], 'Native foundation differs from exact U at keys.json')

    def test_an_admitted_path_refuses_any_content_but_the_pinned_one(self):
        for path in ('core/chat-log.js', 'mods/tasks/bin/herdr_task/launch.py', 'mods/tasks/bin/herdr_task/providers.py'):
            with self.subTest(path=path):
                code, observed = self.changed(path, lambda target: target.write_bytes(target.read_bytes() + b'\n'))
                self.assertEqual(code, 1)
                self.assertEqual(observed['error'], 'Source differs from its admitted phase content at ' + path)

    def test_a_symbolic_link_to_the_same_content_is_refused(self):
        def link(target):
            twin = self.copy.parent / 'twin'
            twin.write_bytes(target.read_bytes())
            target.unlink()
            target.symlink_to(twin)
        code, observed = self.changed('mods/tasks/bin/herdr_task/providers.py', link)
        self.assertEqual((code, observed['error']), (1, 'Admitted source path is a symbolic link at mods/tasks/bin/herdr_task/providers.py'))
        code, observed = self.changed('keys.json', link)
        self.assertEqual((code, observed['error']), (1, 'Native foundation path is a symbolic link at keys.json'))

    def test_an_admitted_path_keeps_its_mode(self):
        code, observed = self.changed('mods/tasks/bin/herdr_task/providers.py', lambda target: target.chmod(0o755))
        self.assertEqual((code, observed['error']), (1, 'Admitted source path is executable at mods/tasks/bin/herdr_task/providers.py'))
        code, observed = self.changed('mods/tasks/bin/herdr_task/launch.py', lambda target: target.chmod(0o755))
        self.assertEqual((code, observed['error']), (1, 'Native executable mode differs at mods/tasks/bin/herdr_task/launch.py'))
