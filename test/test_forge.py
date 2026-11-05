"""The forge seam through the public commands, each as its own process, in a throwaway HOME and
store, with a real Git repository, its origin and the task's worktree, and a recording stand-in for
gh (HERDR_TASK_GH). hc is never reachable here (base.guard refuses it in this HOME), so publication
is driven by `herdr-task review --pass`: the hc-free command that reaches the same finalize() as
`ready` (ready asks hc for its agents first). Merging is driven by `herdr-task merge`.

Oracle: the gh argv this file writes out, the origin's branches, and the task list reopened from
disk after the process ends. Wrong implementations these catch: sending every saved pull request to
GitHub whatever its provider (gh is called for the Bitbucket one); trusting `--repo` without
checking which pull request GitHub answered for (a merge, push or comment goes to another
repository's or host's); pushing before the saved one is confirmed; adopting another repository's
pull request; qualifying or dropping legacy records (the saved record changes, or the unqualified
one is refused).

Runs only on CI, as test_herdr_task's command tests: herdr-task never runs with a changed HOME on
a person's machine."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "mods", "tasks", "bin")
CI = os.environ.get("CI") == "true"

LEGACY = {"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"}
VIEW = ["pr", "view", "7", "--repo", "o/r", "--json", "state,mergeable,headRefOid,statusCheckRollup,mergeCommit,url"]
REPO = ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]
LIST = ["pr", "list", "--repo", "o/r", "--head", "task/1", "--state", "open", "--json", "number,url,isCrossRepository,baseRefName,headRefOid"]
COMMENT = ["pr", "comment", "7", "--repo", "o/r", "--body", "Done."]
FOREIGN_HOST = {"provider": "github", "host": "github.example.com", "repo": "o/r", "number": 7, "url": "https://github.example.com/o/r/pull/7"}
FAKE_GH = """#!{python}
import json, os, sys
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
with open(os.environ["FAKE_GH_SCENE"]) as f:
    reply = json.load(f).get(" ".join(sys.argv[1:3]))
if reply is None:
    sys.stderr.write("fake gh: nothing for " + " ".join(sys.argv[1:3]))
    sys.exit(1)
print(reply if isinstance(reply, str) else json.dumps(reply))
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = os.path.join(self.root, "home")
        self.repo, self.wt = os.path.join(self.home, "repo"), os.path.join(self.home, "wt")
        origin = os.path.join(self.root, "origin.git")
        os.makedirs(self.home)
        self.git(self.root, "init", "-q", "--bare", "-b", "main", origin)
        self.git(self.root, "init", "-q", "-b", "main", self.repo)
        for k, v in (("user.name", "T"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            self.git(self.repo, "config", k, v)
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "base")
        self.git(self.repo, "remote", "add", "origin", origin)
        self.git(self.repo, "push", "-q", "-u", "origin", "main")
        self.start = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "worktree", "add", "-q", "-b", "task/1", self.wt, "HEAD")
        self.git(self.wt, "commit", "-q", "--allow-empty", "-m", "the task's own work")
        self.tip = self.git(self.wt, "rev-parse", "HEAD")
        tools = os.path.join(self.root, "tools")
        os.makedirs(tools)
        gh = os.path.join(tools, "gh")
        with open(gh, "w") as f:
            f.write(FAKE_GH.format(python=sys.executable))
        os.chmod(gh, 0o755)
        self.log, self.scene = os.path.join(self.root, "gh.log"), os.path.join(self.root, "scene.json")
        self.store = os.path.join(self.home, ".herdr", "tasks")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_", "SHEPHERDR_", "GH_")) and k != "GITHUB_TOKEN"}
        env.update(HOME=self.home, HERDR_TASK_STORE=self.store, HERDR_TASK_SETTINGS=os.path.join(self.home, "settings.json"),
                   HERDR_TASK_GH=gh, FAKE_GH_LOG=self.log, FAKE_GH_SCENE=self.scene, GIT_CONFIG_NOSYSTEM="1")
        self.env = env

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout.strip()

    def view(self, url="https://github.com/o/r/pull/7", checks=({"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"},)):
        return {"state": "OPEN", "mergeable": "MERGEABLE", "headRefOid": self.tip, "statusCheckRollup": list(checks), "url": url}

    def run_task(self, command, task, scene):
        """`herdr-task <command> FRG-1 --json` on `task` as saved, gh answering `scene` ("pr view": ...):
        (exit code, its JSON, gh's argv lists, the task as saved afterwards, the list saved)."""
        os.makedirs(self.store, exist_ok=True)
        task = {"id": 1, "title": "Forge seam", "mode": "worktree", "worktree": self.wt, "branch": "task/1",
                "base": "main", "start": self.start, "head": self.tip, "agents": [], **task}
        with open(os.path.join(self.store, "repo.json"), "w") as f:
            json.dump({"version": 1, "folder": self.repo, "kind": "repo", "name": "repo", "slug": "repo",
                       "prefix": "FRG", "next": 2, "tasks": [task]}, f)
        with open(self.scene, "w") as f:
            json.dump(scene, f)
        p = subprocess.run([sys.executable, os.path.join(BIN, "herdr-task"), *command, "FRG-1", "--folder", self.repo, "--json"],
                           capture_output=True, text=True, env=self.env, timeout=60)
        calls = []
        if os.path.exists(self.log):
            with open(self.log) as f:
                calls = [json.loads(line) for line in f if line.strip()]
        with open(os.path.join(self.store, "repo.json")) as f:
            saved = json.load(f)
        self.assertTrue(p.stdout.strip(), p.stderr)
        return p.returncode, json.loads(p.stdout), calls, saved["tasks"][0], saved


@unittest.skipUnless(CI, "runs only on CI: herdr-task never runs with a changed HOME on a person's machine")
class MergeThroughTheForge(Fixture):
    def merge(self, pr, view):
        """`herdr-task merge` on a Ready task saved with `pr`, gh answering `view`."""
        return self.run_task(["merge"], {"state": "ready", "pr": pr}, {"pr view": view, "pr merge": ""})

    def merge_call(self):
        return ["pr", "merge", "7", "--repo", "o/r", "--squash", "--delete-branch", "--match-head-commit", self.tip]

    def branch_here(self):
        return subprocess.run(["git", "-C", self.repo, "rev-parse", "--verify", "--quiet", "refs/heads/task/1"],
                              capture_output=True).returncode == 0

    def assert_untouched(self, saved, calls):
        self.assertNotIn(self.merge_call(), calls)
        self.assertEqual(saved["state"], "ready")
        self.assertNotIn("merged", saved)
        self.assertTrue(os.path.isdir(self.wt))
        self.assertTrue(self.branch_here())

    def test_a_legacy_pull_request_merges_on_github(self):
        code, out, calls, saved, data = self.merge(dict(LEGACY), self.view())
        self.assertEqual(code, 0, out)
        self.assertEqual((out["state"], out["merged"]), ("done", True))
        self.assertEqual(calls, [VIEW, self.merge_call()])
        self.assertEqual((saved["state"], saved["merged"]), ("done", True))
        self.assertEqual(saved["pr"], LEGACY)  # never qualified on the way: it stays GitHub's by meaning
        self.assertEqual(data["main_watch"]["main"]["repo"], "o/r")
        self.assertFalse(os.path.isdir(self.wt))  # local Git cleans up, as before
        self.assertFalse(self.branch_here())

    def test_a_qualified_github_pull_request_merges(self):
        pr = {**LEGACY, "provider": "github", "host": "github.com"}
        code, out, calls, saved, _ = self.merge(pr, self.view())
        self.assertEqual(code, 0, out)
        self.assertEqual(calls, [VIEW, self.merge_call()])
        self.assertEqual((saved["state"], saved["pr"]), ("done", pr))

    def test_a_failing_check_keeps_it_ready(self):
        code, out, calls, saved, _ = self.merge(dict(LEGACY), self.view(checks=[{"name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}]))
        self.assertEqual((code, out["error"]), (1, "Checks failing: ci."))
        self.assertEqual(calls, [VIEW])
        self.assert_untouched(saved, calls)
        self.assertEqual(saved["attention"], "Checks failing: ci.")

    def test_a_running_check_waits(self):
        code, out, calls, saved, _ = self.merge(dict(LEGACY), self.view(checks=[{"name": "ci", "status": "IN_PROGRESS", "conclusion": ""}]))
        self.assertEqual((code, out["error"]), (1, "Checks are still running. Merge again when they pass."))
        self.assertEqual(calls, [VIEW])
        self.assert_untouched(saved, calls)
        self.assertNotIn("attention", saved)

    def test_another_providers_pull_request_never_reaches_github(self):
        pr = {"provider": "bitbucket", "host": "bitbucket.org", "repo": "o/r", "number": 7, "url": "https://bitbucket.org/o/r/pull-requests/7"}
        code, out, calls, saved, _ = self.merge(pr, self.view())
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("bitbucket", out["error"])
        self.assertIn("nothing was sent", out["error"])
        self.assert_untouched(saved, calls)
        self.assertEqual((saved["attention"], saved["pr"]), (out["error"], pr))

    def test_github_answering_for_another_repository_is_refused(self):
        code, out, calls, saved, _ = self.merge(dict(LEGACY), self.view(url="https://github.com/o/fork/pull/7"))
        self.assertEqual(code, 1)
        self.assertEqual(calls, [VIEW])
        self.assertIn("not this task's pull request https://github.com/o/r/pull/7", out["error"])
        self.assert_untouched(saved, calls)

    def test_github_answering_from_another_host_is_refused(self):
        pr = {"provider": "github", "host": "github.example.com", "repo": "o/r", "number": 7, "url": "https://github.example.com/o/r/pull/7"}
        code, out, calls, saved, _ = self.merge(pr, self.view(url="https://github.com/o/r/pull/7"))
        self.assertEqual(code, 1)
        self.assertEqual(calls, [VIEW])
        self.assertIn("nothing was changed", out["error"])
        self.assert_untouched(saved, calls)


@unittest.skipUnless(CI, "runs only on CI: herdr-task never runs with a changed HOME on a person's machine")
class PublishThroughTheForge(Fixture):
    """A reviewed task's publication: its branch pushed and its pull request kept, adopted or refused."""

    def publish(self, pr=None, view=None, listed=()):
        """`herdr-task review --pass` on a working task (saved with `pr`, if any) whose summary is "Done.":
        GitHub knows this folder as o/r, answers `view` for the saved one and lists `listed` for its branch."""
        task = {"state": "running", "summary": "Done.", **({"pr": pr} if pr else {})}
        return self.run_task(["review", "--pass"], task, {"repo view": "o/r", "pr view": view, "pr list": list(listed), "pr comment": ""})

    def pushed(self):
        """The task branch's tip on the origin, or None when nothing was pushed."""
        p = subprocess.run(["git", "-C", self.repo, "ls-remote", "--heads", "origin", "task/1"], capture_output=True, text=True, check=True)
        return p.stdout.split()[0] if p.stdout.strip() else None

    def listed(self, url="https://github.com/o/r/pull/7"):
        return {"number": 7, "url": url, "isCrossRepository": False, "baseRefName": "main", "headRefOid": self.tip}

    def assert_refused(self, code, calls, saved, pr):
        self.assertEqual(code, 0)  # ready all the same; the person is told why it wasn't published
        self.assertEqual(calls, [REPO, VIEW])  # read only: no comment, no new pull request
        self.assertIsNone(self.pushed())
        self.assertEqual(saved["pr"], pr)
        self.assertIn("nothing was changed", saved["attention"])

    def test_its_open_pull_request_is_kept_and_told(self):
        code, out, calls, saved, _ = self.publish(dict(LEGACY), self.view())
        self.assertEqual(code, 0, out)
        self.assertEqual(calls, [REPO, VIEW, COMMENT])
        self.assertEqual(self.pushed(), self.tip)
        self.assertEqual((saved["state"], saved["pr"]), ("ready", {**LEGACY, "checked": 0}))
        self.assertNotIn("attention", saved)

    def test_an_open_one_for_its_branch_is_adopted(self):
        code, out, calls, saved, _ = self.publish(listed=[self.listed()])
        self.assertEqual(code, 0, out)
        self.assertEqual(calls, [REPO, LIST, COMMENT])
        self.assertEqual(self.pushed(), self.tip)
        self.assertEqual(saved["pr"], {**LEGACY, "checked": 0})  # recorded as before: unqualified, GitHub's

    def test_another_repositorys_pull_request_is_never_adopted(self):
        code, out, calls, saved, _ = self.publish(listed=[self.listed("https://github.com/o/fork/pull/7")])
        self.assertEqual(code, 0, out)
        self.assertEqual(calls[:2], [REPO, LIST])
        self.assertEqual([c[:2] for c in calls[2:]], [["pr", "create"]])  # opening one is tried instead
        self.assertNotIn("pr", saved)
        self.assertIn("Couldn't open a pull request", saved["attention"])

    def test_one_saved_for_another_host_is_never_published_on_this_one(self):
        code, _, calls, saved, _ = self.publish(dict(FOREIGN_HOST), self.view())
        self.assert_refused(code, calls, saved, FOREIGN_HOST)

    def test_github_answering_for_another_repository_publishes_nothing(self):
        code, _, calls, saved, _ = self.publish(dict(LEGACY), self.view("https://github.com/o/fork/pull/7"))
        self.assert_refused(code, calls, saved, LEGACY)
        self.assertIn("not this task's pull request https://github.com/o/r/pull/7", saved["attention"])


if __name__ == "__main__":
    unittest.main()
