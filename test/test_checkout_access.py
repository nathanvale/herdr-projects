"""bin/checkout-access through its command line, against real git repositories in temporary folders."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = {"PATH": os.environ["PATH"], "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(folder, *args):
    return subprocess.run(["git", "-C", str(folder), *args], env=ENV, check=True, capture_output=True, text=True).stdout.strip()


class CheckoutAccess(unittest.TestCase):
    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.repo = self.make_repo(self.base / "a repo")
        self.worktrees = self.repo / ".worktrees"
        self.settings = self.repo / ".claude/settings.local.json"

    def make_repo(self, repo, contract=None):
        (repo / ".claude").mkdir(parents=True)
        (repo / "sub").mkdir()
        (repo / "sub/keep").write_text("x\n")
        (repo / ".worktrees").mkdir()
        (repo / ".gitignore").write_text(".worktrees/\n")
        (repo / "bin").mkdir()
        shutil.copy(ROOT / "bin/checkout-access", repo / "bin/checkout-access")
        shutil.copy(ROOT / ".claude/.gitignore", repo / ".claude/.gitignore")
        (repo / ".claude/checkout-access.json").write_text(json.dumps(contract or {"version": 1, "directories": [".worktrees"]}))
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        return repo

    def run_tool(self, command, cwd=None, script=None):
        return subprocess.run([sys.executable, str(script or self.repo / "bin/checkout-access"), command], cwd=str(cwd or self.repo),
                              env=ENV, capture_output=True, text=True)

    def applied(self, **kw):
        result = self.run_tool("apply", **kw)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def listed(self):
        return json.loads(self.settings.read_text())["permissions"]["additionalDirectories"]

    def assert_refused(self, result, words):
        self.assertEqual(result.returncode, 1)
        self.assertIn(words, result.stderr)

    def test_preview_shows_the_scope_and_writes_nothing(self):
        result = self.run_tool("preview")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Would add: {self.worktrees}", result.stdout)
        self.assertIn("under any profile", result.stdout)
        self.assertFalse(self.settings.exists())
        self.assertFalse((self.repo / ".git/checkout-access.json").exists())

    def test_every_checkout_of_the_repository_writes_the_same_main_file(self):
        linked = self.worktrees / "linked"
        external = self.base / "elsewhere/wt"
        git(self.repo, "worktree", "add", "-q", str(linked), "-b", "l")
        git(self.repo, "worktree", "add", "-q", str(external), "-b", "e")
        for cwd, script in ((self.repo, None), (self.repo / "sub", None), (linked, linked / "bin/checkout-access"),
                            (linked / "sub", linked / "bin/checkout-access"), (external, external / "bin/checkout-access")):
            with self.subTest(cwd=str(cwd)):
                self.applied(cwd=cwd, script=script)
                self.assertEqual(self.listed(), [str(self.worktrees)])
                self.assertEqual(self.run_tool("rollback", cwd=cwd, script=script).returncode, 0)
                self.assertFalse(self.settings.exists())
        self.assertFalse((linked / ".claude/settings.local.json").exists())
        self.assertFalse((external / ".claude/settings.local.json").exists())

    def test_it_grants_only_the_contract_folder(self):
        self.applied()
        self.assertEqual(self.listed(), [str(self.worktrees)])
        self.assertNotIn(str(self.repo), [str(Path(d)) for d in self.listed()])
        self.assertNotIn(str(self.base), self.listed())

    def test_another_repository_is_refused(self):
        other = self.make_repo(self.base / "other")
        self.assert_refused(self.run_tool("apply", cwd=other), "Run this inside the repository it belongs to")
        self.assertFalse((other / ".claude/settings.local.json").exists())
        self.assertFalse(self.settings.exists())

    def test_a_folder_outside_git_is_refused(self):
        outside = self.base / "plain"
        outside.mkdir()
        self.assert_refused(self.run_tool("apply", cwd=outside), "Run this inside the repository it belongs to")

    def test_a_repeated_apply_changes_nothing(self):
        self.applied()
        before = self.settings.read_bytes()
        record = (self.repo / ".git/checkout-access.json").read_bytes()
        self.assertIn("Nothing to do", self.applied().stdout)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual((self.repo / ".git/checkout-access.json").read_bytes(), record)

    def test_other_settings_are_preserved(self):
        original = {"model": "m", "permissions": {"allow": ["Read(x)"], "deny": ["Read(y)"], "additionalDirectories": ["/kept"]}}
        self.settings.write_text(json.dumps(original))
        self.applied()
        data = json.loads(self.settings.read_text())
        self.assertEqual(data["model"], "m")
        self.assertEqual(data["permissions"]["allow"], ["Read(x)"])
        self.assertEqual(data["permissions"]["deny"], ["Read(y)"])
        self.assertEqual(data["permissions"]["additionalDirectories"], ["/kept", str(self.worktrees)])

    def test_settings_it_cant_understand_are_never_overwritten(self):
        for text, words in (("{not json", "isn't valid JSON"), ("[]", "isn't a JSON object"),
                            ('{"permissions": []}', "permissions section"),
                            ('{"permissions": {"additionalDirectories": "x"}}', "permissions section")):
            with self.subTest(text=text):
                self.settings.write_text(text)
                self.assert_refused(self.run_tool("apply"), words)
                self.assertEqual(self.settings.read_text(), text)
                self.assertFalse((self.repo / ".git/checkout-access.json").exists())

    @unittest.skipIf(os.geteuid() == 0, "root reads everything")
    def test_unreadable_settings_are_refused(self):
        self.settings.write_text("{}")
        self.settings.chmod(0)
        self.addCleanup(self.settings.chmod, 0o600)
        self.assert_refused(self.run_tool("apply"), "can't be read")

    def test_a_tracked_settings_file_is_refused(self):
        self.settings.write_text("{}")
        git(self.repo, "add", "-f", ".claude/settings.local.json")
        self.assert_refused(self.run_tool("apply"), "is tracked")

    def test_a_settings_file_git_would_add_is_refused(self):
        (self.repo / ".claude/.gitignore").unlink()
        self.assert_refused(self.run_tool("apply"), "Git doesn't ignore")
        self.assertFalse(self.settings.exists())

    def test_symbolic_links_to_the_settings_are_refused(self):
        target = self.base / "real.json"
        target.write_text("{}")
        self.settings.symlink_to(target)
        self.assert_refused(self.run_tool("apply"), "symbolic link")
        self.assertEqual(target.read_text(), "{}")

    def test_a_contract_that_reaches_outside_is_refused(self):
        for folder, words in (("..", "plain path"), ("../x", "plain path"), ("/etc", "plain path"), ("~/x", "plain path"),
                              (".", "plain path"), ("missing", "doesn't exist")):
            with self.subTest(folder=folder):
                (self.repo / ".claude/checkout-access.json").write_text(json.dumps({"version": 1, "directories": [folder]}))
                self.assert_refused(self.run_tool("apply"), words)
                self.assertFalse(self.settings.exists())

    def test_a_contract_folder_linked_out_of_the_repository_is_refused(self):
        (self.base / "out").mkdir()
        (self.repo / "escape").symlink_to(self.base / "out")
        (self.repo / ".claude/checkout-access.json").write_text(json.dumps({"version": 1, "directories": ["escape"]}))
        self.assert_refused(self.run_tool("apply"), "leaves the repository")

    def test_a_repository_reached_through_a_link_records_its_real_path(self):
        link = self.base / "link"
        link.symlink_to(self.repo)
        self.applied(cwd=link, script=link / "bin/checkout-access")
        self.assertEqual(self.listed(), [str(self.worktrees)])

    def test_rollback_removes_a_file_it_created_and_its_record(self):
        self.applied()
        result = self.run_tool("rollback")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.settings.exists())
        self.assertFalse((self.repo / ".git/checkout-access.json").exists())

    def test_rollback_keeps_edits_made_after_apply(self):
        self.applied()
        data = json.loads(self.settings.read_text())
        data["model"] = "m"
        data["permissions"]["allow"] = ["Read(x)"]
        data["permissions"]["additionalDirectories"].append("/added-later")
        self.settings.write_text(json.dumps(data))
        self.assertEqual(self.run_tool("rollback").returncode, 0)
        self.assertEqual(json.loads(self.settings.read_text()),
                         {"model": "m", "permissions": {"allow": ["Read(x)"], "additionalDirectories": ["/added-later"]}})

    def test_rollback_leaves_an_entry_that_was_there_first(self):
        self.settings.write_text(json.dumps({"permissions": {"additionalDirectories": [str(self.worktrees)]}}))
        self.assertIn("Nothing to do", self.applied().stdout)
        self.assertIn("Nothing to roll back", self.run_tool("rollback").stdout)
        self.assertEqual(self.listed(), [str(self.worktrees)])

    def test_rollback_refuses_settings_it_cant_understand(self):
        self.applied()
        self.settings.write_text("{not json")
        self.assert_refused(self.run_tool("rollback"), "isn't valid JSON")
        self.assertEqual(self.settings.read_text(), "{not json")
        self.assertTrue((self.repo / ".git/checkout-access.json").exists())

    def test_rollback_with_nothing_applied_changes_nothing(self):
        self.assertIn("Nothing to roll back", self.run_tool("rollback").stdout)
        self.assertFalse(self.settings.exists())


if __name__ == "__main__":
    unittest.main()
