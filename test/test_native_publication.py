"""Publishing a task through its pull request (herdr_task/github.py), across herdr-task's own command
line: `adopt` records an existing pull request only when the commits prove it is the task's, the
task's base follows it, a repo on GitHub never falls back to a local merge when gh can't answer, gh's
and git's failures say which one failed, and ready neither opens a second pull request nor merges.

These run on CI only, as herdr-task's other command-line tests: HOME stays the account's own, the
task lists and settings are throwaway ones (herdr-task's own overrides), hc is a stand-in first on
PATH and gh a recording stand-in behind HERDR_TASK_GH, the task's route to gh. The remote says
github.com but git reaches a local bare repo through url.insteadOf, so pushes and fetches are real
and no network is used. They prove what herdr-task does with gh's answers; they don't prove
GitHub's own answers, its sign-in or a real push's credentials.

The proof tests alone write outside the throwaway folder: one file in ~/.herdr/artifacts, the only
place herdr-task reads artifacts from, removed after."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "mods", "tasks", "bin")
CI = os.environ.get("CI") == "true"
ON_CI = unittest.skipUnless(CI, "runs only on CI: herdr-task's commands never run from a test on a person's machine")
URL = "https://github.com/o/r.git"
AUTH = "To get started with GitHub CLI, please run:  gh auth login"

FAKE_HC = '''#!/usr/bin/env python3
import json, sys
if sys.argv[1:2] == ["ls"]:
    print(json.dumps({"terminals": []}))
else:
    sys.exit(1)
'''

# GitHub as gh answers it: repository and pull requests from FAKE_GH_STATE, a branch's commit from
# the bare remote itself, every call logged. `fail` fails every call, or only those of `fail_on`.
FAKE_GH = '''#!/usr/bin/env python3
import json, os, subprocess, sys
path = os.environ["FAKE_GH_STATE"]
with open(path) as f:
    st = json.load(f)
argv = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps(argv) + "\\n")


def value(flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


def refuse(words):
    print(words, file=sys.stderr)
    sys.exit(1)


def show(d):
    d = {k: d.get(k) for k in value("--json").split(",")}
    query = value("-q")
    print(d[query.lstrip(".")] if query else json.dumps(d))


def pr():
    p = next((p for p in st["prs"] if str(p["number"]) == argv[2]), None)
    return p or refuse("GraphQL: Could not resolve to a PullRequest with the number of %s." % argv[2])


if st.get("fail") and st.get("fail_on") in (None, argv[0]):
    refuse(st["fail"])
if argv[:2] == ["repo", "view"]:
    show({"nameWithOwner": st["repo"]})
elif argv[:2] == ["pr", "list"]:
    fields = value("--json").split(",")
    print(json.dumps([{k: p.get(k) for k in fields} for p in st["prs"]
                      if p["state"] == "OPEN" and p["headRefName"] == value("--head")]))
elif argv[:2] == ["pr", "view"]:
    show(pr())
elif argv[:2] == ["pr", "create"]:
    print("https://github.com/o/r/pull/9")
elif argv[:2] == ["pr", "comment"]:
    pr()
elif argv[:2] == ["pr", "merge"]:
    pr().update(state="MERGED", mergeCommit={"oid": "f" * 40})
    with open(path, "w") as f:
        json.dump(st, f)
elif argv[0] == "api" and "/git/ref/heads/" in argv[1]:
    ref = "refs/heads/" + argv[1].split("/git/ref/heads/", 1)[1]
    r = subprocess.run(["git", "-C", os.environ["FAKE_GH_BARE"], "rev-parse", "--verify", "--quiet", ref],
                       stdout=subprocess.PIPE, universal_newlines=True)
    if r.returncode:
        refuse("gh: Not Found (HTTP 404)")
    print(r.stdout.strip())
else:
    refuse("gh stand-in: nothing answers " + " ".join(argv))
'''


class Fixture:
    """A repo with a commit `first`, then `start`, where task/1's worktree began; branches old-base
    (what the task recorded) and target (what its pull request targets) both at `start`; and one
    commit of the task's own, `tip`. The task is seeded as a started one, as folder_for() saves it."""

    def __init__(self, test, github=True):
        self.test = test
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.tmp, True)
        join = lambda name: os.path.join(self.tmp, name)
        self.repo, self.wt, self.bare, self.state = join("repo"), join("wt"), join("remote.git"), join("gh.json")
        self.log, self.gh_route = join("gh.log"), join("bin/gh-route")
        os.makedirs(join("bin"))
        for path, body in ((join("bin/hc"), FAKE_HC), (self.gh_route, FAKE_GH)):
            with open(path, "w") as f:
                f.write(body)
            os.chmod(path, 0o755)
        open(self.log, "w").close()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_"))}
        self.env.update(PATH=join("bin") + os.pathsep + os.environ.get("PATH", ""), SHELL="/bin/sh", GIT_TERMINAL_PROMPT="0",
                        FAKE_GH_STATE=self.state, FAKE_GH_LOG=self.log, FAKE_GH_BARE=self.bare, HERDR_TASK_GH=self.gh_route,
                        HERDR_TASK_STORE=join("tasks"), HERDR_TASK_SETTINGS=join("shepherdr.json"),
                        HERDR_TASK_TEMPLATES=join("templates"))
        self.github(prs=[])
        os.makedirs(self.repo)
        self.git(self.repo, "init", "-q", "-b", "main")
        for k, v in (("user.name", "T"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
            self.git(self.repo, "config", k, v)
        self.first = self.commit(self.repo, "first")
        self.start = self.commit(self.repo, "foundation")
        self.git(self.repo, "branch", "old-base")
        self.git(self.repo, "branch", "target")
        if github:
            self.git(self.tmp, "init", "-q", "--bare", "-b", "main", self.bare)
            self.git(self.repo, "remote", "add", "origin", URL)
            self.git(self.repo, "config", f"url.{self.bare}.insteadOf", URL)
            self.git(self.repo, "push", "-q", "origin", "main", "target")
        self.git(self.repo, "worktree", "add", "-q", "-b", "task/1", self.wt, "HEAD")
        self.tip = self.commit(self.wt, "the task's work")
        self.ok("add", "Fix login", "--folder", self.repo, "--space", "sp1")
        self.store = self.ok("where", "--folder", self.repo)["store"]
        self.seed(state="running", started=1, mode="worktree", worktree=self.wt, branch="task/1", start=self.start,
                  **({"base": "old-base", "base_set": True} if github else {"base": "main"}))

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True, env=self.env).stdout.strip()

    def commit(self, cwd, words):
        self.git(cwd, "commit", "-q", "--allow-empty", "-m", words)
        return self.git(cwd, "rev-parse", "HEAD")

    def rev(self, ref):
        return self.git(self.repo, "rev-parse", ref)

    def remote_tip(self, branch):
        r = subprocess.run(["git", "-C", self.bare, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                           capture_output=True, text=True, env=self.env)
        return r.stdout.strip() or None

    def refuse_pushes(self):
        """The remote turns every push away, as a push without the right credentials ends."""
        hook = os.path.join(self.bare, "hooks", "pre-receive")
        os.makedirs(os.path.dirname(hook), exist_ok=True)
        with open(hook, "w") as f:
            f.write("#!/bin/sh\necho 'Permission denied to this identity' >&2\nexit 1\n")
        os.chmod(hook, 0o755)

    def github(self, **state):
        with open(self.state, "w") as f:
            json.dump({"repo": "o/r", **state}, f)

    def pr(self, **over):
        return {"number": 7, "url": "https://github.com/o/r/pull/7", "state": "OPEN", "isCrossRepository": False,
                "headRefName": "task/1", "headRefOid": self.tip, "baseRefName": "target", "baseRefOid": self.start,
                "mergeable": "MERGEABLE", "statusCheckRollup": [], "mergeCommit": None, **over}

    def calls(self, *prefix):
        """gh's calls so far that start with these words."""
        with open(self.log) as f:
            rows = [json.loads(line) for line in f]
        return [r for r in rows if r[:len(prefix)] == list(prefix)]

    def run(self, *args):
        return subprocess.run([sys.executable, os.path.join(BIN, "herdr-task"), *args], capture_output=True, text=True,
                              env=self.env, timeout=120)

    def ok(self, *args):
        p = self.run(*args, "--json")
        self.test.assertEqual(p.returncode, 0, f"herdr-task {' '.join(args)}: {p.stdout}{p.stderr}")
        return json.loads(p.stdout)

    def refused(self, *args):
        """A refusal as --json gives it: exit 1, the reason on stdout, nothing on stderr."""
        p = self.run(*args, "--json")
        self.test.assertEqual((p.returncode, p.stderr), (1, ""), p.stdout)
        return json.loads(p.stdout)["error"]

    def saved(self):
        with open(self.store) as f:
            return f.read()

    def task(self):
        return json.loads(self.saved())["tasks"][0]

    def edit(self, change):
        d = json.loads(self.saved())
        change(d)
        with open(self.store, "w") as f:
            json.dump(d, f, indent=2)

    def seed(self, **fields):
        self.edit(lambda d: d["tasks"][0].update(fields))

    def adopt(self, pr="7"):
        return self.ok("adopt", "1", "--folder", self.repo, "--pr", pr)

    def ready(self, *more):
        return self.ok("ready", "1", "--folder", self.repo, "--summary", "Sign-in works again", *more)

    def no_ready(self, *more):
        return self.refused("ready", "1", "--folder", self.repo, "--summary", "Sign-in works again", *more)


@ON_CI
class Adoption(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.github(prs=[self.f.pr()])

    def refuses(self, words, pr="7"):
        """adopt refuses with these words and nothing moved: the task list, byte for byte, and the remote."""
        f = self.f
        before = f.saved()
        error = f.refused("adopt", "1", "--folder", f.repo, "--pr", pr)
        self.assertIn(words, error)
        self.assertEqual(f.saved(), before)
        self.assertEqual((f.remote_tip("task/1"), f.calls("pr", "create"), f.calls("pr", "merge")), (None, [], []))
        return error

    def test_a_pull_request_of_another_repository(self):
        self.refuses("is in other/r", "https://github.com/other/r/pull/7")
        self.assertEqual(self.f.calls("pr", "view"), [])
        self.f.github(prs=[self.f.pr(url="https://github.com/other/r/pull/7")])
        self.refuses("not a pull request of o/r")

    def test_a_fork(self):
        self.f.github(prs=[self.f.pr(isCrossRepository=True)])
        self.refuses("another repository")

    def test_another_branch(self):
        self.f.github(prs=[self.f.pr(headRefName="task/2")])
        self.refuses("is for branch task/2")

    def test_a_stale_head(self):
        self.f.github(prs=[self.f.pr(headRefOid=self.f.start)])
        self.refuses("Bring them to the same commit")

    def test_a_closed_pull_request(self):
        self.f.github(prs=[self.f.pr(state="CLOSED")])
        self.refuses("is closed, not open")

    def test_a_base_the_commits_dont_prove(self):
        """A base behind the task's start: the pull request would carry more than the task's work. Its
        name proves nothing, the recorded base's own name included."""
        for name in ("target", "old-base"):
            with self.subTest(name=name):
                self.f.github(prs=[self.f.pr(baseRefName=name, baseRefOid=self.f.first)])
                self.refuses("Can't prove")

    def test_a_branch_that_took_in_its_base_later_refuses(self):
        f = self.f
        moved = f.git(f.repo, "commit-tree", "HEAD^{tree}", "-p", f.start, "-m", "moved on")
        merged = f.git(f.repo, "commit-tree", "HEAD^{tree}", "-p", f.tip, "-p", moved, "-m", "took it in")
        f.git(f.wt, "merge", "-q", "--ff-only", merged)
        f.github(prs=[f.pr(headRefOid=merged, baseRefOid=moved)])
        self.refuses("Can't prove")

    def test_a_base_commit_not_here_can_be_fetched_first(self):
        self.f.github(prs=[self.f.pr(baseRefOid="a" * 40)])
        self.assertIn("git fetch origin target", self.refuses("isn't here"))

    def test_no_base_commit_from_gh_refuses(self):
        self.f.github(prs=[self.f.pr(baseRefOid=None)])
        self.refuses("no commit")

    def test_a_branch_with_nothing_of_its_own(self):
        self.f.seed(start=self.f.tip)
        self.f.github(prs=[self.f.pr()])
        self.refuses("no commits of its own")

    def test_only_a_started_worktree_task(self):
        self.f.seed(state="todo")
        self.refuses("isn't a started worktree task")
        self.f.seed(state="running", start=None)
        self.refuses("isn't a started worktree task")

    def test_not_a_number_or_a_link(self):
        self.refuses("give its number or its link", "seven")

    def test_an_equivalent_base_is_adopted_and_becomes_the_tasks(self):
        f = self.f
        out = f.adopt()
        self.assertTrue(out["adopted"])
        t = f.task()
        self.assertEqual((t["pr"]["number"], t["pr"]["url"], t["pr"]["repo"]), (7, "https://github.com/o/r/pull/7", "o/r"))
        self.assertEqual((t["base"], t["base_set"], t["state"]), ("target", True, "running"))
        self.assertEqual([(b["base"], b["pr"]) for b in t["base_history"]], [("old-base", 7)])
        # Only read: nothing created, pushed or merged, and the local branches stay.
        self.assertEqual((f.remote_tip("task/1"), f.calls("pr", "create"), f.calls("pr", "merge"), f.calls("pr", "comment")), (None, [], [], []))
        self.assertEqual((f.rev("target"), f.rev("old-base")), (f.start, f.start))
        shown = f.run("show", "1", "--folder", f.repo).stdout
        self.assertIn("merges into: target (its pull request's base)", shown)
        self.assertIn("was based on: old-base", shown)
        self.assertEqual(f.ok("show", "1", "--folder", f.repo, "--evidence")["evidence"]["scope"], "task/1 into target")

    def test_a_link_works_as_a_number_does(self):
        self.assertTrue(self.f.adopt("https://github.com/o/r/pull/7")["adopted"])
        self.assertEqual(self.f.task()["pr"]["number"], 7)

    def test_a_base_that_moved_on_since_is_still_equivalent(self):
        f = self.f
        moved = f.git(f.repo, "commit-tree", "HEAD^{tree}", "-p", f.start, "-m", "another task merged")
        f.git(f.repo, "update-ref", "refs/heads/target", moved)
        f.github(prs=[f.pr(baseRefOid=moved)])
        self.assertTrue(f.adopt()["adopted"])
        self.assertEqual(f.task()["base"], "target")

    def test_adopting_it_again_changes_nothing(self):
        f = self.f
        f.adopt()
        before = f.saved()
        self.assertFalse(f.adopt()["adopted"])
        self.assertEqual(f.saved(), before)
        self.assertEqual(len(f.calls("pr", "view")), 1)

    def test_another_pull_request_is_refused_once_one_is_recorded(self):
        f = self.f
        f.adopt()
        f.github(prs=[f.pr(), f.pr(number=8, url="https://github.com/o/r/pull/8")])
        before = f.saved()
        self.assertIn("already records pull request #7", f.refused("adopt", "1", "--folder", f.repo, "--pr", "8"))
        self.assertEqual(f.saved(), before)

    def test_a_pending_merge_goes_with_adoption(self):
        self.f.seed(auto_merge="checks")
        self.f.adopt()
        self.assertNotIn("auto_merge", self.f.task())

    def test_any_other_base_change_stays_refused(self):
        f = self.f
        self.assertIn("base can't change", f.refused("edit", "1", "--folder", f.repo, "--base", "main"))
        f.adopt()
        self.assertIn("base can't change", f.refused("edit", "1", "--folder", f.repo, "--base", "main"))
        self.assertEqual(f.task()["base"], "target")


@ON_CI
class TheRealTargetIsObserved(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.github(prs=[self.f.pr()])

    def test_a_merge_into_the_target_counts(self):
        f = self.f
        f.adopt()
        f.ready()
        f.git(f.repo, "branch", "-f", "target", f.tip)
        self.assertTrue(f.ok("done", "1", "--folder", f.repo)["merged"])

    def test_a_target_only_the_remote_has_counts_too(self):
        f = self.f
        f.git(f.repo, "fetch", "-q", "origin", "target:refs/remotes/origin/target")
        f.git(f.repo, "branch", "-D", "target")
        f.adopt()
        f.ready()
        f.git(f.repo, "update-ref", "refs/remotes/origin/target", f.tip)
        self.assertTrue(f.ok("done", "1", "--folder", f.repo)["merged"])

    def test_a_merge_into_the_old_base_no_longer_counts(self):
        f = self.f
        f.adopt()
        f.ready()
        f.git(f.repo, "branch", "-f", "old-base", f.tip)
        self.assertFalse(f.ok("done", "1", "--folder", f.repo).get("merged"))


@ON_CI
class FailsClosed(unittest.TestCase):
    """A repo on GitHub whose gh can't answer: nothing changes, and nothing merges here."""

    def setUp(self):
        self.f = Fixture(self)
        self.f.github(prs=[], fail=AUTH)

    def merged_nothing(self):
        f = self.f
        self.assertEqual((f.rev("old-base"), f.rev("main"), f.remote_tip("task/1")), (f.start, f.start, None))

    def test_ready_refuses_and_leaves_the_task_as_it_was(self):
        f = self.f
        before = f.saved()
        error = f.no_ready()
        self.assertIn("gh couldn't", error)
        self.assertIn("gh auth login", error)
        self.assertEqual(f.saved(), before)  # not Ready, no summary, and no answer saved
        self.assertEqual(f.task()["state"], "running")
        self.merged_nothing()

    def test_no_failed_answer_is_kept(self):
        f = self.f
        f.no_ready()
        f.github(prs=[])
        f.ready()
        self.assertEqual((f.task()["state"], f.task()["pr"]["number"]), ("ready", 9))
        self.assertEqual(f.remote_tip("task/1"), f.tip)

    def test_an_answer_saved_by_an_older_failure_counts_for_nothing(self):
        f = self.f
        f.edit(lambda d: d.update(github={"repo": None, "at": int(time.time() * 1000)}))
        self.assertIn("gh couldn't", f.no_ready())
        self.merged_nothing()

    def test_accept_never_reaches_a_local_merge(self):
        f = self.f
        f.seed(state="ready", ready_at=1)
        before = f.saved()
        self.assertIn("gh couldn't", f.refused("accept", "1", "--folder", f.repo))
        self.assertEqual(f.saved(), before)
        self.merged_nothing()

    def test_merge_never_asks_for_a_local_one(self):
        f = self.f
        f.seed(state="ready", ready_at=1)
        before = f.saved()
        self.assertIn("gh couldn't", f.refused("merge", "1", "--folder", f.repo))
        self.assertEqual(f.saved(), before)

    def test_accept_with_a_recorded_pull_request_waits_for_gh(self):
        f = self.f
        f.seed(state="ready", ready_at=1, pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})
        self.assertIn("Couldn't reach pull request #7", f.refused("accept", "1", "--folder", f.repo))
        self.assertEqual(f.task()["state"], "ready")
        self.merged_nothing()

    def test_a_working_gh_with_no_pull_request_still_never_merges_here(self):
        f = self.f
        f.github(prs=[])
        f.seed(state="ready", ready_at=1)
        self.assertIn("no pull request recorded", f.refused("accept", "1", "--folder", f.repo))
        self.merged_nothing()

    def test_adopt_refuses_too(self):
        f = self.f
        before = f.saved()
        self.assertIn("gh couldn't", f.refused("adopt", "1", "--folder", f.repo, "--pr", "7"))
        self.assertEqual(f.saved(), before)

    def test_gh_not_installed_on_a_github_remote_refuses(self):
        """As a caller without gh on its PATH would be: it can't say no pull request exists."""
        f = self.f
        f.env["HERDR_TASK_GH"] = os.path.join(f.tmp, "no-such-gh")
        before = f.saved()
        self.assertIn("isn't installed", f.no_ready())
        self.assertEqual(f.saved(), before)
        f.seed(state="ready", ready_at=1)
        self.assertIn("isn't installed", f.refused("accept", "1", "--folder", f.repo))
        self.merged_nothing()


@ON_CI
class SeparateFailures(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.github(prs=[self.f.pr()])

    def test_a_refused_push_is_gits_not_ghs(self):
        f = self.f
        f.github(prs=[])
        f.refuse_pushes()
        before = f.saved()
        error = f.no_ready()
        self.assertIn("git couldn't push task/1 to origin", error)
        self.assertIn("Permission denied to this identity", error)
        self.assertIn("apart from gh's sign-in", error)
        self.assertNotIn("gh couldn't", error)
        self.assertEqual(f.saved(), before)
        self.assertEqual((f.calls("pr", "create"), f.remote_tip("task/1")), ([], None))

    def test_a_gh_failure_is_ghs_not_gits(self):
        f = self.f
        f.github(prs=[], fail=AUTH)
        error = f.no_ready()
        self.assertIn("gh couldn't", error)
        self.assertNotIn("git couldn't push", error)

    def test_a_published_head_needs_no_push(self):
        """The remote turns every push away, so ready can only pass by not trying one."""
        f = self.f
        f.git(f.repo, "push", "-q", "origin", "task/1")
        f.refuse_pushes()
        f.adopt()
        f.ready()
        self.assertEqual((f.task()["state"], f.task()["pr"]["number"]), ("ready", 7))

    def test_a_head_past_the_remote_is_still_pushed(self):
        f = self.f
        f.git(f.repo, "push", "-q", "origin", "task/1")
        f.adopt()
        newer = f.commit(f.wt, "one more fix")
        f.ready()
        self.assertEqual(f.remote_tip("task/1"), newer)

    def test_no_answer_on_the_remote_tip_refuses(self):
        f = self.f
        f.adopt()
        f.github(prs=[f.pr()], fail="HTTP 502: Bad Gateway", fail_on="api")
        before = f.saved()
        error = f.no_ready()
        self.assertIn("gh couldn't read task/1 on GitHub", error)
        self.assertEqual(f.saved(), before)
        self.assertEqual(f.remote_tip("task/1"), None)


@ON_CI
class ReadyAfterAdoption(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.github(prs=[self.f.pr()])
        self.f.adopt()

    def published_only(self):
        f = self.f
        t = f.task()
        self.assertEqual((t["pr"]["number"], t["base"]), (7, "target"))
        self.assertEqual((f.calls("pr", "create"), f.calls("pr", "merge")), ([], []))

    def test_it_keeps_the_pull_request_and_asks_the_person(self):
        self.f.ready()
        self.published_only()
        self.assertEqual(self.f.task()["state"], "ready")
        self.assertNotIn("auto_merge", self.f.task())

    def test_a_merge_setting_doesnt_merge_it(self):
        for policy in ("auto", "checks"):
            with self.subTest(policy=policy):
                self.f.seed(state="running", set={"merge": policy})
                self.f.ready()
                self.published_only()
                self.assertEqual(self.f.task()["state"], "ready")
                self.assertNotIn("auto_merge", self.f.task())

    def test_a_pull_request_gh_cant_read_is_never_replaced(self):
        f = self.f
        f.github(prs=[f.pr()], fail="HTTP 401: Bad credentials", fail_on="pr")
        before = f.saved()
        self.assertIn("gh couldn't read pull request #7", f.no_ready())
        self.assertEqual(f.saved(), before)
        self.published_only()
        self.assertEqual(f.remote_tip("task/1"), None)

    def test_a_closed_pull_request_is_never_replaced(self):
        f = self.f
        f.github(prs=[f.pr(state="CLOSED")])
        before = f.saved()
        self.assertIn("adoption never opens another", f.no_ready())
        self.assertEqual(f.saved(), before)
        self.published_only()

    def test_the_persons_accept_merges_through_the_pull_request(self):
        f = self.f
        f.ready()
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        merges = f.calls("pr", "merge")
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0][merges[0].index("--match-head-commit") + 1], f.tip)
        self.assertEqual((f.task()["state"], f.task()["merged"]), ("done", True))
        self.assertEqual((f.rev("main"), f.rev("old-base")), (f.start, f.start))


@ON_CI
class OrdinaryPublication(unittest.TestCase):
    def test_a_task_with_no_pull_request_gets_one_at_its_own_base(self):
        f = Fixture(self)
        f.seed(base="target")
        f.ready()
        t = f.task()
        self.assertEqual((t["state"], t["pr"]["number"]), ("ready", 9))
        self.assertNotIn("adopted", t["pr"])
        made = f.calls("pr", "create")
        self.assertEqual((len(made), made[0][made[0].index("--base") + 1]), (1, "target"))
        self.assertEqual(f.remote_tip("task/1"), f.tip)
        self.assertEqual(f.calls("pr", "merge"), [])


@ON_CI
class NoGitHubRemote(unittest.TestCase):
    def merges_here(self, f):
        f.ready()
        self.assertEqual(f.task()["state"], "ready")
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "merged")
        self.assertEqual((f.task()["state"], f.task()["merged"], f.rev("main")), ("done", True, f.tip))
        self.assertEqual(f.calls("pr") + f.calls("api"), [])

    def test_a_repo_with_no_github_remote_merges_locally_whatever_gh_says(self):
        f = Fixture(self, github=False)
        f.github(prs=[], fail="none of the git remotes configured for this repository point to a known GitHub host")
        self.merges_here(f)

    def test_without_gh_too(self):
        f = Fixture(self, github=False)
        f.env["HERDR_TASK_GH"] = os.path.join(f.tmp, "no-such-gh")
        self.merges_here(f)

    def test_a_remote_elsewhere_merges_locally(self):
        f = Fixture(self, github=False)
        f.git(f.repo, "remote", "add", "origin", "https://bitbucket.org/o/r.git")
        f.github(prs=[], fail="none of the git remotes configured for this repository point to a known GitHub host")
        self.merges_here(f)


@ON_CI
class ProofStaysChecked(unittest.TestCase):
    """ready's proof rule on the adopted path: a custom panel refused before anything is published, a
    recipe taken, and no proof only warned of, as before."""

    def setUp(self):
        self.f = Fixture(self)
        self.f.github(prs=[self.f.pr()])
        self.f.adopt()

    def artifact(self, files):
        """An artifact of the repo's folder, where herdr-artifact keeps them (proof.artifacts_of())."""
        home, folder = os.path.expanduser("~"), self.f.repo
        rel = os.path.relpath(folder, home) if folder.startswith(home + "/") else folder
        path = os.path.join(home, ".herdr", "artifacts", re.sub(r"[^A-Za-z0-9._-]+", "-", rel.strip("/")).strip("-") + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"folder": folder, "artifacts": [{"id": "art-1", "title": "Proof", "files": files}]}, f)
        self.addCleanup(os.unlink, path)

    def test_a_custom_panel_is_refused_before_anything_is_published(self):
        f = self.f
        self.artifact(["main.js", "recipe.json"])
        before = f.saved()
        self.assertIn("custom panel", f.no_ready("--proof", "art-1"))
        self.assertEqual(f.saved(), before)
        self.assertEqual((f.remote_tip("task/1"), f.calls("pr", "comment")), (None, []))

    def test_a_recipe_is_accepted(self):
        self.artifact(["recipe.json"])
        self.f.ready("--proof", "art-1")
        self.assertEqual((self.f.task()["state"], self.f.task()["proof"]), ("ready", {"id": "art-1", "title": "Proof"}))

    def test_no_proof_only_warns(self):
        f = self.f
        p = f.run("ready", "1", "--folder", f.repo, "--summary", "Sign-in works again")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("No proof artifact found", p.stdout)
        self.assertEqual(f.task()["state"], "ready")


if __name__ == "__main__":
    unittest.main()
