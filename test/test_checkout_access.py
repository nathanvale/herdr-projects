"""bin/checkout-access through its command line, against real git repositories in temporary folders."""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def run_tool(self, command, cwd=None, script=None, env=None):
        return subprocess.run([sys.executable, str(script or self.repo / "bin/checkout-access"), command], cwd=str(cwd or self.repo),
                              env={**ENV, **(env or {})}, capture_output=True, text=True)

    def loaded_tool(self):
        """The repository's own copy as a module, for what the command line can't time."""
        loader = importlib.machinery.SourceFileLoader("checkout_access", str(self.repo / "bin/checkout-access"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        tool = importlib.util.module_from_spec(spec)
        loader.exec_module(tool)
        return tool

    def refused_after_a_write_during(self, command):
        """Runs command while another writer changes the settings straight after its first read."""
        tool, reads = self.loaded_tool(), []
        real = tool.read_settings

        def racing(path):
            result = real(path)
            if not reads:
                reads.append(path)
                self.settings.write_text('{"model": "theirs"}')
            return result

        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(str(self.repo))
        with mock.patch.object(tool, "read_settings", racing), mock.patch.dict(os.environ, ENV):
            with self.assertRaises(tool.Refusal) as caught:
                getattr(tool, command)(None)
        self.assertIn("changed while this ran", str(caught.exception))

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

    def test_a_linked_claude_folder_is_refused(self):
        target = self.base / "real"
        (self.repo / ".claude").rename(target)
        (self.repo / ".claude").symlink_to(target)
        self.assert_refused(self.run_tool("apply"), "symbolic link")
        self.assertFalse((target / "settings.local.json").exists())

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

    def test_a_callers_git_variables_cant_redirect_it(self):
        other = self.make_repo(self.base / "other")
        result = self.run_tool("apply", env={"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.listed(), [str(self.worktrees)])
        self.assertFalse((other / ".claude/settings.local.json").exists())
        self.assertFalse((other / ".git/checkout-access.json").exists())

    def test_a_bare_repository_is_refused(self):
        for name, words in (("store.git", "isn't a checkout"), (".git", "isn't the checkout")):
            bare = self.base / "bare" / name
            git(self.base, "clone", "-q", "--bare", str(self.repo), str(bare))
            linked = self.base / "bare" / "linked" / name
            git(bare, "worktree", "add", "-q", str(linked), "HEAD")
            self.assert_refused(self.run_tool("apply", cwd=linked, script=linked / "bin/checkout-access"), words)
            self.assertFalse((bare.parent / ".claude").exists())

    def test_a_submodule_is_refused(self):
        outer = self.make_repo(self.base / "outer")
        git(outer, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(self.repo), "inner")
        inner = outer / "inner"
        self.assert_refused(self.run_tool("apply", cwd=inner, script=inner / "bin/checkout-access"), "isn't a checkout")
        self.assertFalse((outer / ".claude/settings.local.json").exists())

    def test_a_git_directory_kept_elsewhere_is_refused(self):
        repo = self.base / "separate"
        (repo / ".claude").mkdir(parents=True)
        (repo / ".worktrees").mkdir()
        (repo / "bin").mkdir()
        (self.base / "store/.worktrees").mkdir(parents=True)
        shutil.copy(ROOT / "bin/checkout-access", repo / "bin/checkout-access")
        (repo / ".claude/checkout-access.json").write_text(json.dumps({"version": 1, "directories": [".worktrees"]}))
        git(self.base, "init", "-q", f"--separate-git-dir={self.base / 'store/.git'}", str(repo))
        self.assert_refused(self.run_tool("apply", cwd=repo, script=repo / "bin/checkout-access"), "isn't the checkout")
        self.assertFalse((self.base / "store/.claude").exists())

    def test_a_global_ignore_is_enough_to_keep_the_file_out_of_git(self):
        git(self.repo, "rm", "-q", ".claude/.gitignore")
        git(self.repo, "commit", "-q", "-m", "no local ignore")
        self.assert_refused(self.run_tool("apply"), "Merge .claude/.gitignore")
        ignore, config = self.base / "ignore", self.base / "config"
        ignore.write_text("settings.local.json\n")
        config.write_text(f"[core]\n\texcludesFile = {ignore}\n")
        result = self.run_tool("apply", env={"GIT_CONFIG_GLOBAL": str(config)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.listed(), [str(self.worktrees)])

    def test_apply_keeps_the_files_mode(self):
        self.settings.write_text("{}")
        self.settings.chmod(0o644)
        self.applied()
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o644)

    def test_a_write_during_apply_leaves_the_record_as_it_was(self):
        self.refused_after_a_write_during("apply")
        self.assertEqual(self.settings.read_text(), '{"model": "theirs"}')
        self.assertFalse((self.repo / ".git/checkout-access.json").exists())

    def test_a_write_during_a_later_apply_restores_the_earlier_record(self):
        self.applied()
        record = self.repo / ".git/checkout-access.json"
        before = record.read_text()
        (self.repo / "sub/more").mkdir()
        contract = self.repo / ".claude/checkout-access.json"
        contract.write_text(json.dumps({"version": 1, "directories": [".worktrees", "sub/more"]}))
        self.refused_after_a_write_during("apply")
        self.assertEqual(record.read_text(), before)

    def test_a_write_during_rollback_keeps_the_file_and_the_record(self):
        self.applied()
        self.refused_after_a_write_during("rollback")
        self.assertEqual(self.settings.read_text(), '{"model": "theirs"}')
        self.assertTrue((self.repo / ".git/checkout-access.json").exists())

    def test_a_failed_write_leaves_no_temporary_file(self):
        tool = self.loaded_tool()
        with mock.patch.object(tool.os, "replace", side_effect=OSError("disk")), self.assertRaises(OSError):
            tool.replace(str(self.settings), None, {})
        self.assertEqual(sorted(p.name for p in self.settings.parent.iterdir()), [".gitignore", "checkout-access.json"])

    def test_a_moved_repository_names_its_repair(self):
        self.applied()
        moved = self.base / "moved"
        self.repo.rename(moved)
        before = (moved / ".claude/settings.local.json").read_text()
        for command in ("apply", "rollback"):
            result = self.run_tool(command, cwd=moved, script=moved / "bin/checkout-access")
            self.assert_refused(result, "by hand")
            self.assertIn(str(self.worktrees), result.stderr)
            self.assertIn(str(moved / ".git/checkout-access.json"), result.stderr)
        self.assertEqual((moved / ".claude/settings.local.json").read_text(), before)

    def test_a_record_it_cant_read_is_refused(self):
        self.applied()
        record = self.repo / ".git/checkout-access.json"
        for value in ("[]", '{"version": 2}', '{"version": 1, "settings": "x", "added": 1, "created": []}'):
            record.write_text(value)
            self.assert_refused(self.run_tool("rollback"), "isn't a version 1 record")
        self.assertEqual(self.listed(), [str(self.worktrees)])

    def test_rollback_with_nothing_applied_changes_nothing(self):
        self.assertIn("Nothing to roll back", self.run_tool("rollback").stdout)
        self.assertFalse(self.settings.exists())


if __name__ == "__main__":
    unittest.main()
