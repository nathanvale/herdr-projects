import home_guard  # noqa: F401  (first: every test on a throwaway home, never the real one)
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
LEDGER = ROOT / 'docs/migration/q-reconciliation.json'


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
        self.assertEqual((observed['phase'], observed['source_deltas']), ('Q', 114))  # A2 owns service/voice-data.ts and test/test_restart.py since v3.1.29, herdr_task/agents.py since v3.1.31's unknown-check policy, core/live-switch.js, its test and service/live-switch.test.ts since PR 60's review, and core/mentions.js, its test and copy, web/plugins/chat/client.tsx, composer.test.tsx, markdown.tsx, suggest.ts and its test, web/src/kernel.ts and service/chat-reach.test.ts since its six-claim fix; N1 owns bin/shepherdr and test/test_install.py since its review #8, bin/herdr-browser and test/test_herdr_browser_libs.py since the six-claim fix

    def test_candidate_gate_refuses_even_when_source_validation_passes(self):
        result, observed = self.run_check('--require-ready')
        self.assertEqual(result.returncode, 3)
        self.assertEqual(observed['source_validation'], 'passed')
        self.assertEqual(observed['candidate_readiness'], 'blocked')
        self.assertIn('Q reconciles every obligation on its candidate, but 40 required behaviors lack native qualification',
                      result.stderr)
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
        for name in ('github.py', 'providers.py', 'forge.py'):
            with self.subTest(name=name):
                def corrupt(data):
                    next(row for row in data['source_deltas'] if row['path'].endswith('/' + name))['sha256'] = '0' * 64
                result, observed = self.fixture(MANIFEST, corrupt, '--manifest')
                self.assertEqual(result.returncode, 1)
                self.assertEqual(observed['candidate_readiness'], 'blocked')
                self.assertIn('admitted phase content at mods/tasks/bin/herdr_task/' + name, observed['error'])

    def test_phase_cannot_roll_back_over_its_changes(self):
        result, observed = self.fixture(MANIFEST, lambda data: data.update(phase='S0'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase S0', observed['error'])

    def test_s1_cannot_be_named_back_to_h1(self):
        """H1 admits neither the forge seam nor its new tests, so its name can't hold S1's deltas."""
        result, observed = self.fixture(MANIFEST, lambda data: data.update(phase='H1'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase H1', observed['error'])

    def test_b1_cannot_be_named_back_to_s1(self):
        """S1 admits neither the Bitbucket adapter nor its transport, so its name can't hold B1's deltas."""
        result, observed = self.fixture(MANIFEST, lambda data: data.update(phase='S1'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase S1', observed['error'])

    def test_b2_cannot_be_named_back_to_b1(self):
        """B1 admits neither the claims owner nor its regressions, so its name can't hold B2's deltas."""
        result, observed = self.fixture(MANIFEST, lambda data: data.update(phase='B1'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase B1', observed['error'])

    def test_l1_cannot_be_named_back_to_b2(self):
        """B2 admits neither the launch owner, its start sites nor its regressions, so its name can't hold L1's deltas."""
        result, observed = self.fixture(MANIFEST, lambda data: data.update(phase='B2'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase B2', observed['error'])

    def test_a2_cannot_be_named_back_to_l1(self):
        """L1 admits neither the Provider settings, the selectors nor their regressions, so its name can't hold A2's deltas."""
        result, observed = self.fixture(MANIFEST, lambda data: data.update(phase='L1'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase L1', observed['error'])

    def test_l2_cannot_be_named_back_to_a2(self):
        """A2 admits neither the revival owner, the lost-session and restart sites' changes nor their regressions, so its
        name can't hold L2's deltas."""
        result, observed = self.fixture(MANIFEST, lambda data: data.update(phase='A2'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertIn('admitted owners of phase A2', observed['error'])

    def test_phase_cannot_roll_back_by_dropping_its_deltas_too(self):
        result, observed = self.fixture(MANIFEST, lambda data: data.update(phase='S0', source_deltas=[]), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(observed['candidate_readiness'], 'blocked')
        self.assertIn('Native foundation differs from exact U', observed['error'])

    def test_an_unadmitted_owner_cannot_join_the_phase(self):
        for phase in ('A1', 'N1', 'C1', 'W1', 'H1', 'S1', 'B1', 'B2', 'L1', 'A2', 'L2', 'Q'):
            with self.subTest(phase=phase):
                def widen(data):
                    data['source_deltas'].append({'phase': phase, 'path': 'mods/tasks/bin/herdr_task/archive.py',
                                                  'upstream_blob': None, 'sha256': '0' * 64})
                result, observed = self.fixture(MANIFEST, widen, '--manifest')
                self.assertEqual(result.returncode, 1)
                self.assertIn('admitted owners of phase Q', observed['error'])

    def test_a_delta_cannot_drop_its_upstream_provenance(self):
        for name in ('github.py', 'takeover.py'):
            with self.subTest(name=name):
                def rewrite(data):
                    next(row for row in data['source_deltas'] if row['path'].endswith('/' + name))['upstream_blob'] = None
                result, observed = self.fixture(MANIFEST, rewrite, '--manifest')
                self.assertEqual(result.returncode, 1)
                self.assertIn('upstream provenance changed at mods/tasks/bin/herdr_task/' + name, observed['error'])

    def test_a_ready_claim_stays_refused_in_an_admitted_phase(self):
        result, observed = self.fixture(MANIFEST, lambda data: data.update(candidate_readiness='ready'), '--manifest')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(observed['candidate_readiness'], 'blocked')
        self.assertIn('must remain a blocked', observed['error'])


class Reconciliation(unittest.TestCase):
    """Q's ledger through the checker's public process: every obligation is in it with native evidence or a hold,
    and nothing in it can quietly fall out, claim coverage it doesn't name, or outlive its candidate."""
    run_check = SourceCheckpoint.run_check
    fixture = SourceCheckpoint.fixture

    def refused(self, mutate, words, source=LEDGER, flag='--ledger'):
        result, observed = self.fixture(source, mutate, flag)
        self.assertEqual((result.returncode, observed['source_validation'], observed['candidate_readiness']),
                         (1, 'failed', 'blocked'), observed)
        self.assertIn(words, observed['error'])

    @staticmethod
    def row(data, kind, key, value):
        return next(row for row in data[kind] if row[key] == value)

    def test_every_obligation_is_counted_and_none_is_qualified(self):
        result, observed = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout)
        counted = observed['reconciliation']
        # 40 inventory requirements; 38 fork and PR 3 test files declaring 449 cases (the file inventory's static
        # counts); 43 test steps in the fork's three workflows at F; 4 of them ported as sensitivity checks.
        self.assertEqual((counted['requirements_unqualified'], counted['test_obligations'], counted['declared_cases'],
                          counted['workflow_steps'], counted['sensitivity_ported']), (40, 38, 449, 43, 4))
        self.assertEqual(counted['candidate'], 'd53e014bbaf74c0dfb3b750f402968d490eafcfb')
        self.assertEqual(counted['tests_covered'] + counted['tests_partial'] + counted['tests_held'], 38)
        self.assertEqual(observed['candidate_readiness'], 'blocked')

    def test_a_requirement_cannot_drop_out(self):
        self.refused(lambda data: data['requirements'].pop(), 'lacks or repeats a required behavior')

    def test_a_requirement_keeps_the_inventorys_status_and_says_what_is_missing(self):
        self.refused(lambda data: self.row(data, 'requirements', 'id', 'missing-history').update(status='pending'),
                     'Requirement missing-history has another status than the inventory')
        self.refused(lambda data: self.row(data, 'requirements', 'id', 'azure-bound-resume').update(missing=''),
                     'Requirement azure-bound-resume is unqualified but names no missing proof')
        self.refused(lambda data: self.row(data, 'requirements', 'id', 'azure-bound-resume').update(held_for=''),
                     'Requirement azure-bound-resume names no owner for its missing proof')

    def test_an_evidence_class_follows_its_regressions(self):
        self.refused(lambda data: self.row(data, 'requirements', 'id', 'bitbucket-reads').update(evidence_class='held'),
                     'Requirement bitbucket-reads has an evidence class its regressions do not support')
        self.refused(lambda data: self.row(data, 'requirements', 'id', 'bitbucket-reads').update(native=[]),
                     'Requirement bitbucket-reads names no native regression and is not a held decision')

    def test_a_named_native_test_must_be_in_its_file(self):
        def rename(data):
            self.row(data, 'requirements', 'id', 'launch-uncertainty')['native'][0]['tests'].append('test_nobody_wrote_this')
        self.refused(rename, 'names a test test/test_launch_admission.py does not hold: test_nobody_wrote_this')

        def prefix(data):
            # a prefix of a real test's name is not that test
            self.row(data, 'requirements', 'id', 'launch-uncertainty')['native'][0]['tests'].append('test_a_start_is_claimed')
        self.refused(prefix, 'names a test test/test_launch_admission.py does not hold: test_a_start_is_claimed')

    def test_a_removed_test_file_cannot_drop_out_or_change_its_count(self):
        def drop(data):
            data['test_obligations'] = [row for row in data['test_obligations'] if row['path'] != 'test/core-operator.test.ts']
        self.refused(drop, 'lacks or repeats a removed test obligation')
        self.refused(lambda data: self.row(data, 'test_obligations', 'path', 'test/core-operator.test.ts').update(declarations=1),
                     'Test obligation fork:test/core-operator.test.ts changed its declared case count')

    def test_covered_means_nothing_held_and_a_hold_says_why(self):
        def claim(data):
            self.row(data, 'test_obligations', 'path', 'test/core-launch-admission.test.ts').update(disposition='covered')
        self.refused(claim, 'is covered only with nothing held')
        self.refused(lambda data: self.row(data, 'test_obligations', 'path', 'test/core-protected-update.test.ts').update(held=''),
                     'is covered only with nothing held, and partial or held only with its hold said')

    def test_a_held_case_must_be_one_its_fixed_source_declares(self):
        def invent(data):
            self.row(data, 'test_obligations', 'path', 'test/core-protected-update.test.ts')['uncovered'].append('a case nobody wrote')
        self.refused(invent, 'holds a case its fixed source does not declare: a case nobody wrote')

    def test_a_fork_workflow_step_cannot_drop_out(self):
        def drop(data):
            data['workflow_obligations'] = [row for row in data['workflow_obligations']
                                            if row['step'] != 'Prove recovery rejects a different execution host']
        self.refused(drop, 'lacks or repeats a fork workflow test step')

    def test_a_named_test_is_a_declaration_not_any_quoted_text(self):
        def quoted(data):
            # "code-deployment" is quoted in the file (a fixture's deployment name), never a test's title
            self.row(data, 'requirements', 'id', 'azure-discovery')['native'][0]['tests'].append('code-deployment')
        self.refused(quoted, 'names a test service/azure-deployments.test.ts does not hold: code-deployment')

    def test_a_ported_step_proves_one_of_its_own_regressions(self):
        step = 'Prove the default-preservation regression detects a provider override'
        self.refused(lambda data: self.row(data, 'workflow_obligations', 'step', step)['mutation'].update(
            test='test_codex_on_azure_by_api_key'),
            'Sensitivity ' + step + ' removes a guard for a regression that is not one of its own native regressions')

    def test_a_ported_step_removes_exactly_one_guard_its_regression_names(self):
        step = 'Prove discovery rejects incompatible inventory'
        self.refused(lambda data: self.row(data, 'workflow_obligations', 'step', step)['mutation'].update(before='no such guard'),
                     'Sensitivity ' + step + ' does not remove exactly one guard in service/azure-deployments.ts')
        self.refused(lambda data: self.row(data, 'workflow_obligations', 'step', step)['mutation'].update(test='no such test'),
                     'Sensitivity ' + step + ' names a regression service/azure-deployments.test.ts does not hold')

    def test_a_held_step_says_why(self):
        step = 'Prove protected stop refuses live workers'
        self.refused(lambda data: self.row(data, 'workflow_obligations', 'step', step).update(held=''),
                     'Workflow step foundry.yml ' + step + ' is ported, or says what holds it')

    def test_the_evidence_belongs_to_its_candidate(self):
        self.refused(lambda data: data['candidate'].update(tree='0' * 40), 'Reconciled candidate commit, tree or CI tree differs')
        self.refused(lambda data: data['candidate'].update(commit='0' * 40), 'Reconciled candidate commit, tree or CI tree differs')

    def test_the_manifest_cannot_name_a_phase_before_q(self):
        self.refused(lambda data: data.update(phase='L2'), 'the manifest names a phase before Q', MANIFEST, '--manifest')


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
        for path in ('core/chat-log.js', 'mods/tasks/bin/herdr_task/github.py', 'mods/tasks/bin/herdr_task/launch.py',
                     'mods/tasks/bin/herdr_task/providers.py', 'service/jobs.ts', 'service/main.ts',
                     'test/test_native_publication.py', 'mods/tasks/bin/herdr_task/forge.py', 'test/test_forge.py',
                     'mods/tasks/bin/herdr_task/bitbucket_http.py', 'service/worktree.ts', 'test/test_bitbucket.py',
                     'mods/tasks/bin/herdr_task/publications.py', 'test/test_bitbucket_publication.py',
                     'mods/tasks/bin/herdr_task/launch_admission.py', 'mods/coordinator/restart.sh', 'service/spaces.ts',
                     'test/test_launch_admission.py', 'service/launch-sites.test.ts'):
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
        for path in ('mods/tasks/bin/herdr_task/providers.py', 'test/test_native_publication.py'):
            with self.subTest(path=path):
                code, observed = self.changed(path, link)
                self.assertEqual((code, observed['error']), (1, 'Admitted source path is a symbolic link at ' + path))
        code, observed = self.changed('keys.json', link)
        self.assertEqual((code, observed['error']), (1, 'Native foundation path is a symbolic link at keys.json'))

    def test_an_admitted_path_keeps_its_mode(self):
        for path in ('mods/tasks/bin/herdr_task/providers.py', 'test/test_native_publication.py', 'mods/tasks/bin/herdr_task/forge.py'):
            with self.subTest(path=path):
                code, observed = self.changed(path, lambda target: target.chmod(0o755))
                self.assertEqual((code, observed['error']), (1, 'Admitted source path is executable at ' + path))
        for path in ('mods/tasks/bin/herdr_task/github.py', 'mods/tasks/bin/herdr_task/launch.py'):
            with self.subTest(path=path):
                code, observed = self.changed(path, lambda target: target.chmod(0o755))
                self.assertEqual((code, observed['error']), (1, 'Native executable mode differs at ' + path))

    def added(self, path, words='Not in the shared table.\n'):
        """The checker's answer with one new file in the copy; it goes after."""
        target = self.copy / path
        assert not target.exists(), f'added() needs a path absent from the copy, not one it would overwrite and delete: {path}'
        made = [d for d in reversed(target.parents) if not d.exists()]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(words)
        try:
            return self.check()
        finally:
            target.unlink()
            for d in reversed(made):
                d.rmdir()

    def test_an_added_path_outside_the_table_refuses(self):
        """PR 19 decision D5's deferred enumeration, by name in the A1/S1 shared table (issue #7): a path
        no phase admits, no accepted change names and U doesn't have refuses, a document as much as source."""
        for path in ('docs/added-outside-the-table.md', 'mods/tasks/bin/herdr_task/added_outside_the_table.py'):
            with self.subTest(path=path):
                code, observed = self.added(path)
                self.assertEqual((code, observed['candidate_readiness']), (1, 'blocked'))
                self.assertEqual(observed['error'], 'Path outside the shared table of U, admitted owners and named additions: ' + path)

    def test_an_ignored_path_is_no_commit_of_this_one(self):
        """What git ignores here (dependencies, generated web sources, bytecode) can't be committed: not refused."""
        for path in ('node_modules/x/index.js', 'web/generated/client-plugins.ts', 'mods/tasks/bin/herdr_task/__pycache__/x.pyc'):
            with self.subTest(path=path):
                code, observed = self.added(path)
                self.assertEqual((code, observed['source_validation']), (0, 'passed'), observed)

    def test_a_source_change_since_the_reconciled_candidate_refuses(self):
        """Q's evidence is the candidate's: a tracked path changed since it, outside Q's own paths and documents,
        makes the record stale. bin/checkout-access is named, not pinned, so only this check sees it."""
        code, observed = self.changed('bin/checkout-access', lambda target: target.write_bytes(target.read_bytes() + b'\n'))
        self.assertEqual((code, observed['candidate_readiness']), (1, 'blocked'))
        self.assertEqual(observed['error'], 'Source differs from the reconciled candidate outside Q: bin/checkout-access'
                                            ' (a later unit names its paths in AFTER_Q)')

    def test_a_later_unit_that_names_its_path_after_q_passes(self):
        """The compliant route after Q merges: a later unit lists what it changes in AFTER_Q, in the checker."""
        checker = self.copy / 'bin/check-migration'
        text = checker.read_text()
        # AFTER_Q names the v3.1.29 merge's paths already: this unit's entry joins them.
        self.assertEqual(text.count('AFTER_Q = {\n'), 1)
        try:
            checker.write_text(text.replace('AFTER_Q = {\n', "AFTER_Q = {\n    'MIG-X': 'bin/checkout-access',\n"))
            code, observed = self.changed('bin/checkout-access', lambda target: target.write_bytes(target.read_bytes() + b'\n'))
        finally:
            checker.write_text(text)
        self.assertEqual((code, observed['source_validation']), (0, 'passed'), observed)

    def test_a_later_phase_keeps_the_reconciliation(self):
        """A phase row after Q (R) with the manifest naming it passes: Q's ledger stays valid for it."""
        checker, manifest = self.copy / 'bin/check-migration', self.copy / 'docs/migration/upstream-v3.1.3.json'
        text, data = checker.read_text(), manifest.read_text()
        self.assertEqual(text.count("    'Q': frozenset(),\n}"), 1)
        try:
            checker.write_text(text.replace("    'Q': frozenset(),\n}", "    'Q': frozenset(),\n    'R': frozenset(),\n}"))
            manifest.write_text(data.replace('"phase": "Q",', '"phase": "R",', 1))
            code, observed = self.check()
        finally:
            checker.write_text(text)
            manifest.write_text(data)
        self.assertEqual((code, observed['source_validation'], observed['phase']), (0, 'passed', 'R'), observed)

    def test_check_must_run_the_ported_sensitivity_checks(self):
        """Dropping the Check step, commenting it out, or letting it fail or skip would discharge the four ported
        obligations silently: each refused."""
        line = '        run: python3 bin/check-sensitivity'
        for name, instead in (('dropped', '        run: true'), ('commented', '        # run: python3 bin/check-sensitivity'),
                              ('allowed to fail', '        continue-on-error: true\n' + line),
                              ('skipped', '        if: false\n' + line)):
            with self.subTest(name=name):
                code, observed = self.changed('.github/workflows/check.yml', lambda target: target.write_text(
                    target.read_text().replace(line, instead)))
                self.assertEqual((code, observed['candidate_readiness']), (1, 'blocked'))
                self.assertIn('Check no longer runs bin/check-sensitivity unconditionally', observed['error'])

    def test_after_q_takes_one_string_of_paths_per_unit(self):
        checker = self.copy / 'bin/check-migration'
        text = checker.read_text()
        try:
            self.assertEqual(text.count('AFTER_Q = {\n'), 1)
            checker.write_text(text.replace('AFTER_Q = {\n', "AFTER_Q = {\n    'MIG-X': ['bin/checkout-access'],\n"))
            code, observed = self.check()
        finally:
            checker.write_text(text)
        self.assertEqual(code, 1)
        self.assertIn("AFTER_Q names each later unit's paths as one space-separated string", observed['error'])

    def test_a_document_change_keeps_the_reconciliation(self):
        code, observed = self.changed('docs/native-restart.md', lambda target: target.write_bytes(target.read_bytes() + b'\n'))
        self.assertEqual((code, observed['source_validation']), (0, 'passed'), observed)


class Sensitivity(unittest.TestCase):
    """bin/check-sensitivity through its process, in a throwaway copy with a guard and a regression of its own: a
    guard is proved only when its regression passes with it and fails without it, and the source is always put back."""

    GUARD = 'def admit(n):\n    if n < 0:\n        return False\n    return True\n'
    TESTS = ('import sys\nimport unittest\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n'
             'import q_probe_guard\n\n\nclass Probe(unittest.TestCase):\n'
             '    def test_probe_refuses_a_negative(self):\n        self.assertFalse(q_probe_guard.admit(-1))\n\n'
             '    def test_probe_admits_zero(self):\n        self.assertTrue(q_probe_guard.admit(0))\n\n'
             '    def test_probe_always_fails(self):\n        self.assertTrue(q_probe_guard.admit(-5))\n\n'
             '    @unittest.skip("not here")\n    def test_probe_skipped(self):\n        self.assertFalse(q_probe_guard.admit(-1))\n')

    @classmethod
    def setUpClass(cls):
        cls.copy = Path(tempfile.mkdtemp()) / 'copy'
        cls.addClassCleanup(shutil.rmtree, cls.copy.parent, True)
        subprocess.run(['git', 'clone', '-q', '--shared', str(ROOT), str(cls.copy)], check=True, capture_output=True, timeout=120)
        (cls.copy / 'q_probe_guard.py').write_text(cls.GUARD)
        (cls.copy / 'test/test_q_probe.py').write_text(cls.TESTS)

    def prove(self, test, before='if n < 0:', after='if n < -100:'):
        ledger = self.copy.parent / 'ledger.json'
        ledger.write_text(json.dumps({'workflow_obligations': [{
            'step': 'Prove the probe refuses a negative', 'disposition': 'ported',
            'mutation': {'runner': 'unittest', 'file': 'q_probe_guard.py', 'before': before, 'after': after,
                         'test_file': 'test/test_q_probe.py', 'test': test}}]}))
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('SHEPHERDR_', 'ANTHROPIC_', 'CLAUDE_', 'AZURE_', 'OPENAI_', 'HERDR_'))}
        result = subprocess.run([sys.executable, str(self.copy / 'bin/check-sensitivity'), '--ledger', str(ledger)],
                                cwd=self.copy, env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual((self.copy / 'q_probe_guard.py').read_text(), self.GUARD)  # put back byte for byte
        return result.returncode, json.loads(result.stdout.splitlines()[-1]), result.stderr

    def test_a_regression_that_catches_the_removed_guard_proves_it(self):
        code, observed, _ = self.prove('test_probe_refuses_a_negative')
        self.assertEqual((code, observed), (0, {'sensitivity': 'passed', 'ported': 1, 'proved': 1}))

    def test_a_regression_that_misses_the_removed_guard_refuses(self):
        code, observed, said = self.prove('test_probe_admits_zero')
        self.assertEqual((code, observed['proved']), (1, 0))
        self.assertIn('the regression did not fail with the guard removed', said)

    def test_a_regression_failing_with_its_guard_in_place_proves_nothing(self):
        code, observed, said = self.prove('test_probe_always_fails')
        self.assertEqual((code, observed['proved']), (1, 0))
        self.assertIn('the regression does not pass with the guard in place', said)

    def test_a_skipped_regression_proves_nothing(self):
        code, observed, said = self.prove('test_probe_skipped')
        self.assertEqual((code, observed['proved']), (1, 0))
        self.assertIn('the regression was skipped, so it proves nothing here', said)

    def test_a_regression_that_errors_without_its_guard_proves_nothing(self):
        """A change that breaks the code (here a name that doesn't exist) errors the test: not proof of the guard."""
        code, observed, said = self.prove('test_probe_refuses_a_negative', after='if n < undefined_name:')
        self.assertEqual((code, observed['proved']), (1, 0))
        self.assertIn('the regression errored instead of failing an assertion with the guard removed', said)

    def test_a_guard_that_isnt_there_exactly_once_is_never_changed(self):
        code, observed, said = self.prove('test_probe_refuses_a_negative', before='return')
        self.assertEqual((code, observed['proved']), (1, 0))
        self.assertIn('the guard is not exactly once in q_probe_guard.py', said)
