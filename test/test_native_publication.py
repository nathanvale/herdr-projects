"""Publishing a task through its pull request (herdr_task/github.py), across herdr-task's own command
line: `adopt` records an existing pull request only when the commits prove it is the task's, the
task's base follows it, a repo on GitHub never falls back to a local merge when gh can't answer, gh's
and git's failures say which one failed, and ready neither opens a second pull request nor merges.

These run on CI only, as herdr-task's other command-line tests: HOME is the run's throwaway one
(test/home_guard.py), as are the task lists and settings (herdr-task's own overrides), hc is a stand-in first on
PATH and gh a recording stand-in behind HERDR_TASK_GH, the task's route to gh. The remote says
github.com but git reaches a local bare repo through url.insteadOf, so pushes and fetches are real
and no network is used. They prove what herdr-task does with gh's answers; they don't prove
GitHub's own answers, its sign-in or a real push's credentials.

The proof tests write one file in the throwaway home's artifacts folder, the only place herdr-task
reads artifacts from, removed after."""
import home_guard  # noqa: F401  (first: every test on a throwaway home, never the real one)
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
# SHEP-147 (test/home_guard.py): every test runs on a throwaway HOME, where herdr-task refuses hc
# (base.not_real) and launch admission sends nothing (launch_admission.py's guard). A fixture whose hc is
# its own stand-in lifts that refusal for the processes it starts and for nothing else, as upstream's own
# tests do in a subprocess (test_herdr_task.py: base.not_real = lambda: None). Python runs this
# sitecustomize.py first in each of them; it patches whichever herdr_task.base that process imports, so a
# negative control's older herdr-task is lifted too, never replaced by this tree's.
LIFT = """import importlib.machinery, sys


class _Lift:
    def find_spec(self, name, path=None, target=None):
        if name != "herdr_task.base":
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is not None and spec.loader is not None:
            run = spec.loader.exec_module

            def exec_module(module):
                run(module)
                module.not_real = lambda: None
            spec.loader.exec_module = exec_module
        return spec


sys.meta_path.insert(0, _Lift())
"""


def stand_in_hc(env, folder):
    """env for the processes a fixture starts when its hc is a stand-in: herdr-task's real-home refusal
    lifted there alone (LIFT)."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "sitecustomize.py"), "w") as f:
        f.write(LIFT)
    return {**env, "PYTHONPATH": os.pathsep.join(p for p in (folder, env.get("PYTHONPATH")) if p)}
URL = "https://github.com/o/r.git"
AUTH = "To get started with GitHub CLI, please run:  gh auth login"
# gh 2.101.0's words, read from a repo signed in to github.com with an Enterprise, alias or Bitbucket
# remote; a github.com remote signed in only to an Enterprise host gets the 401 instead.
NOT_GITHUB = ("none of the git remotes configured for this repository point to a known GitHub host. "
              "To tell gh about a new GitHub host, please use `gh auth login`")
SIGNED_IN_ELSEWHERE = "HTTP 401: Requires authentication (https://api.github.com/graphql)"
# Another forge's remote, which stays local: GitLab's. A Bitbucket remote publishes since B2
# (test_bitbucket_publication.py), and never merges here.
ELSEWHERE = "https://gitlab.com/o/r.git"
ALIAS = "git@work-alias:o/r.git"
ENTERPRISE = "https://git.example.com/o/r.git"
LOOKALIKE = "https://bitbucket.org.example.com/o/r.git"
HANDOFF = "say why in your chat and end your turn"
SECRET = "secret-marker"
TOKEN_URL = f"https://x-access-token:{SECRET}@github.com/o/r.git"

FAKE_HC = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_HC_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:2] == ["ls"]:
    print(json.dumps({"terminals": []}))
else:
    sys.exit(1)
'''

# GitHub as gh answers it: repository and pull requests from FAKE_GH_STATE, a branch's commit from
# the bare remote itself, every call logged. `fail` fails every call, or only those of `fail_on`;
# `create` and `merge` refuse those two; `answer` is what `pr view` prints instead of a pull request;
# `merge_moves` is what `pr merge` does to the pull request, in place of merging it, before any refusal.
# `repo view` links the repository on the host gh resolves from the folder's remote, or on `host`, as gh
# resolves an SSH alias; `repo_url` replaces that link (None: none).
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
    # As gh: its link is on the host gh resolves from this folder's remote (`host` stands in for an
    # SSH alias's, which gh resolves through ssh's configuration).
    remote = subprocess.run(["git", "config", "--get", "remote.origin.url"], stdout=subprocess.PIPE,
                            universal_newlines=True).stdout.strip()
    import re
    m = re.match(r"(?:[a-z][a-z0-9+.-]*://)?(?:[^@/]+@)?([^/:]+)", remote)
    host = st.get("host") or (m.group(1).lower() if m else "github.com")
    host = "github.com" if host == "ssh.github.com" else host
    show({"nameWithOwner": st["repo"], "url": st["repo_url"] if "repo_url" in st else "https://%s/%s" % (host, st["repo"])})
elif argv[:2] == ["pr", "list"]:
    # As gh v2.101.0 (pkg/cmd/pr/shared/lister.go): --state defaults to open, and closed includes merged.
    states = {"open": ["OPEN"], "closed": ["CLOSED", "MERGED"], "merged": ["MERGED"],
              "all": ["OPEN", "CLOSED", "MERGED"]}.get((value("--state") or "open").lower())
    if states is None:
        refuse("gh stand-in: no such --state " + str(value("--state")))
    fields = value("--json").split(",")
    print(json.dumps([{k: p.get(k) for k in fields} for p in st["prs"]
                      if p["state"] in states and p["headRefName"] == value("--head")]))
elif argv[:2] == ["pr", "view"]:
    print(st["answer"]) if "answer" in st else show(pr())
elif argv[:2] == ["pr", "create"]:
    if st.get("create"):
        refuse(st["create"])
    print("https://%s/o/r/pull/9" % (os.environ.get("GH_HOST") or "github.com"))  # on the host gh is sent to
elif argv[:2] == ["pr", "comment"]:
    pr()
elif argv[:2] == ["pr", "merge"]:
    pr().update(st.get("merge_moves") or ({} if st.get("merge") else {"state": "MERGED", "mergeCommit": {"oid": "f" * 40}}))
    with open(path, "w") as f:
        json.dump(st, f)
    if st.get("merge"):
        refuse(st["merge"])
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
        self.log, self.hc_log, self.gh_route = join("gh.log"), join("hc.log"), join("bin/gh-route")
        os.makedirs(join("bin"))
        for path, body in ((join("bin/hc"), FAKE_HC), (self.gh_route, FAKE_GH)):
            with open(path, "w") as f:
                f.write(body)
            os.chmod(path, 0o755)
        open(self.log, "w").close()
        open(self.hc_log, "w").close()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_"))}
        self.env.update(PATH=join("bin") + os.pathsep + os.environ.get("PATH", ""), SHELL="/bin/sh", GIT_TERMINAL_PROMPT="0",
                        FAKE_HC_LOG=self.hc_log, FAKE_GH_STATE=self.state, FAKE_GH_LOG=self.log, FAKE_GH_BARE=self.bare,
                        HERDR_TASK_GH=self.gh_route,
                        HERDR_TASK_STORE=join("tasks"), HERDR_TASK_SETTINGS=join("shepherdr.json"),
                        HERDR_TASK_TEMPLATES=join("templates"))
        self.env = stand_in_hc(self.env, join("lift"))
        self.github(prs=[])
        self.made = 0  # commit()'s files so far, each named for its own
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
        """A commit that adds a file of its own, as real work does: an empty one would read as already
        merged to SHEP-59's landed(), whose merge of it into any base changes nothing."""
        self.made += 1
        name = f"work-{self.made}.txt"
        with open(os.path.join(cwd, name), "w") as f:
            f.write(words + "\n")
        self.git(cwd, "add", "--", name)
        self.git(cwd, "commit", "-q", "-m", words)
        return self.git(cwd, "rev-parse", "HEAD")

    def rev(self, ref):
        return self.git(self.repo, "rev-parse", ref)

    def sibling(self, words):
        """A commit beside the task's own, on `start`; on no branch yet."""
        return self.git(self.repo, "commit-tree", "HEAD^{tree}", "-p", self.start, "-m", words)

    def publish(self, commit, branch):
        """GitHub's branch moves to this commit; this clone's stays where it was."""
        self.git(self.repo, "push", "-q", "origin", f"{commit}:refs/heads/{branch}")

    def remote_tip(self, branch):
        r = subprocess.run(["git", "-C", self.bare, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                           capture_output=True, text=True, env=self.env)
        return r.stdout.strip() or None

    def refuse_pushes(self, words="Permission denied to this identity"):
        """The remote turns every push away, as a push without the right credentials ends."""
        hook = os.path.join(self.bare, "hooks", "pre-receive")
        os.makedirs(os.path.dirname(hook), exist_ok=True)
        with open(hook, "w") as f:
            f.write(f"#!/bin/sh\necho '{words}' >&2\nexit 1\n")
        os.chmod(hook, 0o755)

    def without_gh(self):
        """As a machine with no gh: HERDR_TASK_GH unset, and a PATH holding only what these commands
        run, as CI's own PATH has a real gh."""
        tools = os.path.join(self.tmp, "tools")
        os.makedirs(tools)
        os.symlink(shutil.which("git"), os.path.join(tools, "git"))
        os.symlink(sys.executable, os.path.join(tools, "python3"))
        del self.env["HERDR_TASK_GH"]
        self.env["PATH"] = os.path.dirname(self.gh_route) + os.pathsep + tools

    def program(self, path, body, mode=0o755):
        with open(path, "w") as f:
            f.write(body)
        os.chmod(path, mode)
        return path

    def github(self, **state):
        with open(self.state, "w") as f:
            json.dump({"repo": "o/r", **state}, f)

    def pr(self, **over):
        return {"number": 7, "url": "https://github.com/o/r/pull/7", "state": "OPEN", "isCrossRepository": False,
                "headRefName": "task/1", "headRefOid": self.tip, "baseRefName": "target",
                "mergeable": "MERGEABLE", "statusCheckRollup": [], "mergeCommit": None, **over}

    def calls(self, *prefix):
        """gh's calls so far that start with these words."""
        with open(self.log) as f:
            rows = [json.loads(line) for line in f]
        return [r for r in rows if r[:len(prefix)] == list(prefix)]

    def hc(self, *verbs):
        """hc's calls so far with these verbs."""
        with open(self.hc_log) as f:
            rows = [json.loads(line) for line in f]
        return [r for r in rows if r[:1] and r[0] in verbs]

    def run(self, *args):
        return subprocess.run([sys.executable, os.path.join(BIN, "herdr-task"), *args], capture_output=True, text=True,
                              env=self.env, timeout=120)

    def ok(self, *args):
        p = self.run(*args, "--json")
        self.test.assertEqual(p.returncode, 0, f"herdr-task {' '.join(args)}: {p.stdout}{p.stderr}")
        return json.loads(p.stdout)

    def refusal(self, *args):
        """A refusal as --json gives it: exit 1, its object on stdout, nothing on stderr."""
        p = self.run(*args, "--json")
        self.test.assertEqual((p.returncode, p.stderr), (1, ""), p.stdout)
        return json.loads(p.stdout)

    def refused(self, *args):
        return self.refusal(*args)["error"]

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

    def merges_here(self, into="main"):
        """ready, then Accept, end in a local merge into this branch."""
        self.ready()
        self.test.assertEqual(self.task()["state"], "ready")
        self.test.assertEqual(self.ok("accept", "1", "--folder", self.repo)["accepted"], "merged")
        self.test.assertEqual((self.task()["state"], self.task()["merged"], self.rev(into)), ("done", True, self.tip))


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
        for name in ("behind", "old-base"):
            with self.subTest(name=name):
                self.f.publish(self.f.first, name)
                self.f.github(prs=[self.f.pr(baseRefName=name)])
                self.refuses("Can't prove")

    def test_a_branch_that_took_in_its_base_later_refuses(self):
        f = self.f
        moved = f.sibling("moved on")
        merged = f.git(f.repo, "commit-tree", "HEAD^{tree}", "-p", f.tip, "-p", moved, "-m", "took it in")
        f.git(f.wt, "merge", "-q", "--ff-only", merged)
        f.publish(moved, "target")
        f.github(prs=[f.pr(headRefOid=merged)])
        self.refuses("Can't prove")

    def test_a_base_commit_not_here_can_be_fetched_first(self):
        f = self.f
        only = f.git(f.bare, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit-tree",
                     f"{f.start}^{{tree}}", "-p", f.start, "-m", "only on GitHub")
        f.git(f.bare, "update-ref", "refs/heads/target", only)
        self.assertIn("git fetch origin target", self.refuses("isn't here"))

    def test_a_base_branch_github_doesnt_have_refuses(self):
        self.f.github(prs=[self.f.pr(baseRefName="gone")])
        self.refuses("isn't on GitHub")

    def test_no_answer_on_the_base_branch_refuses(self):
        self.f.github(prs=[self.f.pr()], fail="HTTP 502: Bad Gateway", fail_on="api")
        self.refuses("gh couldn't read target on GitHub")

    def test_the_base_is_read_from_the_branch_never_from_the_pull_request(self):
        """A pull request's own base commit is history: GitHub's branch decides, either way."""
        f = self.f
        f.github(prs=[f.pr(baseRefOid=f.first)])
        self.assertTrue(f.adopt()["adopted"])
        self.assertEqual([c for c in f.calls("pr", "view") if "baseRefOid" in " ".join(c)], [])
        self.assertTrue(f.calls("api", "repos/o/r/git/ref/heads/target"))

    def test_a_recorded_base_that_went_its_own_way_refuses(self):
        """Both descend from the start, so the start rule holds; the target would still lose it."""
        f = self.f
        f.git(f.repo, "update-ref", "refs/heads/old-base", f.sibling("on the recorded base"))
        f.publish(f.sibling("on the target"), "target")
        self.assertIn("silently replace", self.refuses("isn't in target"))

    def test_a_recorded_base_that_moved_only_on_github_refuses(self):
        f = self.f
        f.publish(f.sibling("on the recorded base"), "old-base")
        f.publish(f.sibling("on the target"), "target")
        self.refuses("isn't in target")
        self.assertEqual(f.rev("old-base"), f.start)

    def test_a_recorded_base_nobody_has_refuses(self):
        self.f.git(self.f.repo, "branch", "-D", "old-base")
        self.refuses("isn't on GitHub or here")

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
        for given in ("seven", "\u00b2", "\u0663", "1" * 5000, "https://github.com/o/r/pull/" + "1" * 5000):
            with self.subTest(given=given[:40]):
                self.refuses("give its number or its link", given)
        self.assertEqual(self.f.calls("pr", "view"), [])

    def test_an_answer_gh_garbled_refuses(self):
        for field, value in (("baseRefName", None), ("baseRefName", 7), ("headRefName", None), ("headRefOid", None),
                             ("state", None), ("isCrossRepository", None), ("url", None)):
            with self.subTest(field=field, value=value):
                self.f.github(prs=[self.f.pr(**{field: value})])
                self.refuses("an answer it couldn't read")
        for answer in ("not json", "[]", "null", "7", "{}"):
            with self.subTest(answer=answer):
                self.f.github(prs=[], answer=answer)
                self.refuses("an answer it couldn't read")

    def test_a_name_that_isnt_a_branch_refuses(self):
        for field, name in (("baseRefName", "-x"), ("baseRefName", "a b"), ("baseRefName", ""), ("headRefName", "-x")):
            with self.subTest(field=field, name=name):
                self.f.github(prs=[self.f.pr(**{field: name})])
                self.refuses("isn't a branch name")

    def test_an_equivalent_base_is_adopted_and_becomes_the_tasks(self):
        f = self.f
        out = f.adopt()
        self.assertTrue(out["adopted"])
        t = f.task()
        self.assertEqual((t["pr"]["number"], t["pr"]["url"], t["pr"]["repo"]), (7, "https://github.com/o/r/pull/7", "o/r"))
        self.assertEqual((t["base"], t["base_set"], t["state"]), ("target", True, "running"))
        self.assertEqual((t["adopted_from"]["base"], t["adopted_from"]["pr"]), ("old-base", 7))
        self.assertEqual(out["adopted_from"]["base"], "old-base")
        # Only read: nothing created, pushed or merged, and the local branches stay.
        self.assertEqual((f.remote_tip("task/1"), f.calls("pr", "create"), f.calls("pr", "merge"), f.calls("pr", "comment")), (None, [], [], []))
        self.assertEqual((f.rev("target"), f.rev("old-base")), (f.start, f.start))
        shown = f.run("show", "1", "--folder", f.repo).stdout
        self.assertIn("merges into: target (its pull request's base)", shown)
        self.assertIn("was based on: old-base", shown)
        self.assertEqual(f.ok("show", "1", "--folder", f.repo, "--evidence")["evidence"]["scope"], "task/1 into target")

    def test_it_says_the_old_and_new_base(self):
        p = self.f.run("adopt", "1", "--folder", self.f.repo, "--pr", "7")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("its base moves from old-base to target", p.stdout)

    def test_a_link_works_as_a_number_does(self):
        self.assertTrue(self.f.adopt("https://github.com/o/r/pull/7")["adopted"])
        self.assertEqual(self.f.task()["pr"]["number"], 7)

    def test_a_base_that_moved_on_since_is_still_equivalent(self):
        f = self.f
        f.publish(f.sibling("another task merged"), "target")
        self.assertTrue(f.adopt()["adopted"])
        self.assertEqual(f.task()["base"], "target")

    def test_adopting_it_again_changes_nothing(self):
        f = self.f
        f.adopt()
        before = f.saved()
        self.assertFalse(f.adopt()["adopted"])
        self.assertEqual(f.saved(), before)
        self.assertEqual(len(f.calls("pr", "view")), 1)
        self.assertIn("is already recorded", f.run("adopt", "1", "--folder", f.repo, "--pr", "7").stdout)

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
        self.assertIn(HANDOFF, error)
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
        self.for_the_person(f.refused("accept", "1", "--folder", f.repo))
        self.assertEqual(f.saved(), before)
        self.merged_nothing()

    def for_the_person(self, error):
        """gh's failure as the person reads it: what to repair, and no turn to end."""
        self.assertIn("gh couldn't", error)
        self.assertIn("then try again", error)
        self.assertNotIn("end your turn", error)

    def test_merge_never_asks_for_a_local_one(self):
        f = self.f
        f.seed(state="ready", ready_at=1)
        before = f.saved()
        self.for_the_person(f.refused("merge", "1", "--folder", f.repo))
        self.assertEqual(f.saved(), before)

    def test_accept_with_a_recorded_pull_request_waits_for_gh(self):
        f = self.f
        f.seed(state="ready", ready_at=1, pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})
        error = f.refused("accept", "1", "--folder", f.repo)
        self.assertIn("Couldn't reach pull request #7", error)
        self.assertIn("gh auth login", error)  # gh's own reason
        self.assertIn("Nothing merged", error)
        self.assertIn("then try again", error)
        self.assertNotIn("end your turn", error)
        self.assertEqual(f.task()["state"], "ready")
        self.merged_nothing()

    def test_the_tick_waits_quietly_for_gh(self):
        f = self.f
        f.seed(state="ready", ready_at=1, pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})
        self.assertEqual(f.ok("tick", "--folder", f.repo)["attention"], [])
        self.assertNotIn("attention", f.task())
        self.assertEqual(f.task()["state"], "ready")

    def test_a_working_gh_with_no_pull_request_still_never_merges_here(self):
        f = self.f
        f.github(prs=[])
        f.seed(state="ready", ready_at=1)
        self.assertIn("no pull request recorded", f.refused("accept", "1", "--folder", f.repo))
        self.merged_nothing()

    def test_adopt_refuses_too(self):
        f = self.f
        before = f.saved()
        self.for_the_person(f.refused("adopt", "1", "--folder", f.repo, "--pr", "7"))
        self.assertEqual(f.saved(), before)

    def test_gh_not_installed_on_a_github_remote_refuses(self):
        """As a caller without gh on its PATH would be: it can't say no pull request exists."""
        f = self.f
        f.without_gh()
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
        self.assertIn(HANDOFF, error)
        self.assertNotIn("gh couldn't", error)
        self.assertNotIn("tracking ref", error)
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

    def test_a_lease_refused_on_the_tracking_ref_says_so(self):
        """A branch published without a push from here: git's lease has no tracking ref to go on."""
        f = self.f
        f.git(f.repo, "push", "-q", "origin", "task/1")
        f.adopt()
        f.git(f.repo, "update-ref", "-d", "refs/remotes/origin/task/1")
        f.commit(f.wt, "one more fix")
        before = f.saved()
        error = f.no_ready()
        self.assertIn("stale info", error)
        self.assertIn(f"tracking ref origin/task/1 is at nothing and GitHub has {f.tip[:7]}", error)
        self.assertEqual(f.saved(), before)
        self.assertEqual(f.remote_tip("task/1"), f.tip)

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

    def test_one_already_merged_leaves_the_task_to_the_tick(self):
        f = self.f
        f.github(prs=[f.pr(state="MERGED")])
        before = f.saved()
        error = f.no_ready()
        self.assertIn("The tick finishes the task if that was into target", error)
        self.assertIn("holds it for the person if it wasn't", error)
        self.assertEqual(f.saved(), before)
        self.published_only()
        self.assertEqual(f.remote_tip("task/1"), None)

    def refused_accept(self, words):
        """Accept refuses with these words: nothing merged, and it stays Ready with why."""
        f = self.f
        self.assertIn(words, f.refused("accept", "1", "--folder", f.repo))
        self.published_only()
        self.assertEqual(f.task()["state"], "ready")
        self.assertIn(words, f.task()["attention"])

    def test_accept_refuses_a_retargeted_pull_request_until_it_is_back(self):
        f = self.f
        f.ready()
        f.github(prs=[f.pr(baseRefName="other")])
        self.refused_accept("now targets other, not target")
        f.github(prs=[f.pr()])
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")

    def test_accept_refuses_a_head_pushed_since(self):
        f = self.f
        f.ready()
        f.github(prs=[f.pr(headRefOid=f.first)])
        self.refused_accept("isn't what adoption verified")

    def test_accept_refuses_a_branch_that_moved_here_since(self):
        f = self.f
        f.ready()
        f.commit(f.wt, "one more fix")
        self.refused_accept("isn't what adoption verified")

    def test_the_tick_never_merges_a_retargeted_pull_request(self):
        f = self.f
        f.ready()
        f.seed(auto_merge="checks")  # as Accept leaves it while checks run
        f.github(prs=[f.pr(baseRefName="other")])
        f.ok("tick", "--folder", f.repo)
        self.published_only()
        self.assertEqual(f.task()["state"], "ready")
        self.assertIn("now targets other", f.task()["attention"])

    def tick(self):
        """A tick that reads the pull request now: it reads one at most once a minute."""
        self.f.edit(lambda d: d["tasks"][0]["pr"].update(checked=0))
        return self.f.ok("tick", "--folder", self.f.repo)

    def test_the_tick_shows_a_move_and_clears_it_once_put_back(self):
        f = self.f
        f.ready()
        for moved, words in (({"baseRefName": "other"}, "now targets other"), ({"headRefOid": f.first}, "isn't what adoption verified")):
            with self.subTest(words=words):
                f.github(prs=[f.pr(**moved)])
                self.assertEqual(self.tick()["attention"], [1])
                self.assertIn(words, f.task()["attention"])
                f.github(prs=[f.pr()])
                self.assertEqual(self.tick()["attention"], [])
                self.assertNotIn("attention", f.task())
        self.assertEqual((f.task()["state"], f.calls("pr", "merge")), ("ready", []))

    def test_the_tick_clears_a_refused_accept_once_put_back(self):
        f = self.f
        f.ready()
        f.github(prs=[f.pr(baseRefName="other")])
        self.refused_accept("now targets other")
        f.github(prs=[f.pr()])
        self.tick()
        self.assertNotIn("attention", f.task())

    def test_the_tick_finishes_one_merged_into_its_real_base(self):
        f = self.f
        f.ready()
        f.publish(f.tip, "target")
        f.github(prs=[f.pr(state="MERGED", mergeCommit={"oid": f.tip})])
        self.assertEqual(f.ok("tick", "--folder", f.repo)["done"], [1])
        t = f.task()
        self.assertEqual((t["state"], t["merged"], t["pr"]["number"], t["base"]), ("done", True, 7, "target"))
        self.assertEqual(list(json.loads(f.saved())["main_watch"]), ["target"])
        self.assertFalse(os.path.isdir(f.wt))
        self.assertEqual((f.rev("main"), f.rev("old-base"), f.calls("pr", "merge")), (f.start, f.start, []))

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

    def test_a_pull_request_gh_wont_open_hands_over(self):
        """One into its own base that GitHub still shows at an older commit: gh's own words, and adopt
        wouldn't take it either, so none is named."""
        f = Fixture(self)
        f.github(prs=[f.pr(baseRefName="old-base", headRefOid=f.first)],
                 create='a pull request for branch "task/1" into branch "old-base" already exists')
        before = f.saved()
        error = f.no_ready()
        self.assertIn("Couldn't open a pull request", error)
        self.assertIn("already exists", error)
        self.assertNotIn("herdr-task adopt", error)
        self.assertIn(HANDOFF, error)
        self.assertEqual(f.saved(), before)


@ON_CI
class NoRemotes(unittest.TestCase):
    def merges_here(self, f):
        f.merges_here()
        self.assertEqual(f.calls(), [])  # gh was never asked

    def test_a_repo_with_no_remotes_merges_locally_whatever_gh_would_say(self):
        f = Fixture(self, github=False)
        f.github(prs=[], fail=AUTH)
        self.merges_here(f)

    def test_without_gh_too(self):
        f = Fixture(self, github=False)
        f.without_gh()
        f.merges_here()


@ON_CI
class OnlyGhsOwnNoIsANo(unittest.TestCase):
    def elsewhere(self, url, **answers):
        f = Fixture(self, github=False)
        f.git(f.repo, "remote", "add", "origin", url)
        f.github(prs=[], **answers)
        return f

    def test_any_other_failure_refuses_for_a_repo_with_a_remote(self):
        """saved: gh confirmed this repo for these remotes an hour or more ago, so it's asked again."""
        for url, failure, saved in ((ALIAS, AUTH, False), (ENTERPRISE, AUTH, False), (LOOKALIKE, AUTH, False),
                                    (ALIAS, "error connecting to api.github.com", False), (URL, SIGNED_IN_ELSEWHERE, False),
                                    (ENTERPRISE, "HTTP 503: Service Unavailable", False), (ENTERPRISE, NOT_GITHUB, True)):
            with self.subTest(url=url, failure=failure, saved=saved):
                f = self.once_on_github(url) if saved else self.elsewhere(url)
                if saved:
                    f.edit(lambda d: d["github"].update(at=1))
                f.github(prs=[], fail=failure)
                before = f.saved()
                self.assertIn("gh couldn't", f.no_ready())
                self.assertEqual(f.saved(), before)
                f.seed(state="ready", ready_at=1)
                before = f.saved()
                self.assertIn("gh couldn't", f.refused("accept", "1", "--folder", f.repo))
                self.assertEqual((f.saved(), f.rev("main"), f.rev("old-base")), (before, f.start, f.start))

    def test_a_name_saved_before_remotes_were_kept_overrules_ghs_no_too(self):
        f = self.elsewhere(ENTERPRISE, fail=NOT_GITHUB)
        f.edit(lambda d: d.update(github={"repo": "o/r", "at": 1}))
        before = f.saved()
        self.assertIn("gh couldn't", f.no_ready())
        self.assertEqual(f.saved(), before)

    def test_another_forge_stays_local_with_gh_signed_out_and_never_asks_it(self):
        for url in (ELSEWHERE, "git@gitlab.com:o/r.git", "ssh://git@gitlab.com/o/r.git",
                    "https://o@dev.azure.com/o/p/_git/r", "git@ssh.dev.azure.com:v3/o/p/r"):
            with self.subTest(url=url):
                f = self.elsewhere(url, fail=AUTH)
                f.merges_here()
                self.assertEqual(f.calls(), [])

    def test_github_beside_another_forge_is_still_github(self):
        f = Fixture(self)
        f.git(f.repo, "remote", "add", "mirror", ELSEWHERE)
        f.github(prs=[], fail=AUTH)
        before = f.saved()
        self.assertIn("gh couldn't", f.no_ready())
        self.assertEqual(f.saved(), before)
        f.github(prs=[])
        f.ready()
        self.assertEqual((f.task()["state"], f.task()["pr"]["number"], f.remote_tip("task/1")), ("ready", 9, f.tip))

    def test_an_unknown_host_beside_another_forge_still_refuses(self):
        f = self.elsewhere(ELSEWHERE, fail=AUTH)
        f.git(f.repo, "remote", "add", "work", ENTERPRISE)
        self.assertIn("gh couldn't", f.no_ready())

    def test_ghs_own_no_is_saved_and_merges_locally(self):
        f = self.elsewhere(ENTERPRISE, fail=NOT_GITHUB)
        f.merges_here()
        self.assertEqual(json.loads(f.saved())["github"]["repo"], None)
        self.assertEqual(len(f.calls("repo", "view")), 2)  # ready's, then Accept rechecks GitHub before merging here
        self.assertEqual(f.calls("pr") + f.calls("api"), [])

    def test_a_remote_added_since_a_saved_no_is_asked_about(self):
        f = self.elsewhere(ENTERPRISE, fail=NOT_GITHUB)
        f.ready()
        f.seed(state="running")
        f.git(f.repo, "remote", "add", "work", ALIAS)
        f.github(prs=[], fail=AUTH)
        self.assertIn("gh couldn't", f.no_ready())

    def test_a_github_remote_overrules_that_answer(self):
        f = Fixture(self)
        f.github(prs=[], fail=NOT_GITHUB)
        before = f.saved()
        self.assertIn("gh couldn't", f.no_ready())
        self.assertEqual(f.saved(), before)

    def once_on_github(self, url=URL):
        """A task whose ready saved gh's answer for this remote, with no pull request now: the name
        is what's tested. Any remote but github.com's reaches the same bare repo."""
        f = Fixture(self)
        if url != URL:
            f.git(f.repo, "remote", "set-url", "origin", url)
            f.git(f.repo, "config", "--add", f"url.{f.bare}.insteadOf", url)
            # gh sent to that host, as one set up for an Enterprise remote is (GH_HOST: S1's forge reaches only it).
            f.env["GH_HOST"] = url.split("/")[2]
        f.ready()
        self.assertEqual(json.loads(f.saved())["github"]["repo"], "o/r")
        f.edit(lambda d: (d["tasks"][0].pop("pr"), d["tasks"][0].update(state="running")))
        return f

    def test_removing_the_remote_clears_the_saved_name(self):
        f = self.once_on_github()
        f.git(f.repo, "remote", "remove", "origin")
        f.github(prs=[], fail=AUTH)
        f.merges_here("old-base")
        self.assertNotIn("github", json.loads(f.saved()))

    def test_moving_the_remote_to_another_forge_clears_the_saved_name(self):
        f = self.once_on_github()
        f.git(f.repo, "remote", "set-url", "origin", ELSEWHERE)
        f.github(prs=[], fail=AUTH)
        f.merges_here("old-base")
        self.assertNotIn("github", json.loads(f.saved()))

    def test_moving_the_remote_to_a_host_gh_doesnt_know_clears_the_saved_name(self):
        f = self.once_on_github()
        f.git(f.repo, "remote", "set-url", "origin", ENTERPRISE)
        f.github(prs=[], fail=NOT_GITHUB)
        f.merges_here("old-base")
        self.assertEqual(json.loads(f.saved())["github"]["repo"], None)

    def test_a_name_saved_by_an_older_version_clears_too(self):
        f = Fixture(self)
        f.edit(lambda d: d.update(github={"repo": "o/r", "at": int(time.time() * 1000)}))
        f.git(f.repo, "remote", "remove", "origin")
        f.merges_here("old-base")
        self.assertNotIn("github", json.loads(f.saved()))

    def test_gh_not_installed_on_a_remote_elsewhere_stays_local(self):
        for url in (ELSEWHERE, ENTERPRISE):
            with self.subTest(url=url):
                f = self.elsewhere(url)
                f.without_gh()
                f.merges_here()

    def test_adopt_after_ghs_no_doesnt_claim_there_is_no_github_remote(self):
        f = self.elsewhere(ENTERPRISE, fail=NOT_GITHUB)
        self.assertIn("no remote gh can place on GitHub", f.refused("adopt", "1", "--folder", f.repo, "--pr", "7"))

    def test_gh_not_installed_with_a_saved_name_refuses(self):
        f = self.elsewhere(ALIAS)
        f.without_gh()
        f.edit(lambda d: d.update(github={"repo": "o/r", "at": 1}))
        before = f.saved()
        self.assertIn("isn't installed", f.no_ready())
        self.assertEqual(f.saved(), before)


@ON_CI
class AWorktreeThatIsGone(unittest.TestCase):
    """Settings that merge on their own, so a local merge would be asked of its agent at once."""

    def gone(self, github=True):
        f = Fixture(self, github=github)
        f.seed(set={"merge": "auto"})
        shutil.rmtree(f.wt)
        return f

    def test_ready_refuses_before_anything_else(self):
        for github in (True, False):
            with self.subTest(github=github):
                f = self.gone(github)
                before = f.saved()
                self.assertIn("is gone", f.no_ready())
                self.assertEqual(f.saved(), before)
                self.assertEqual(f.hc("send", "run"), [])

    def test_a_reviewers_pass_is_refused_too(self):
        f = self.gone()
        error = f.refused("review", "1", "--folder", f.repo, "--pass")
        self.assertIn("is gone", error)
        self.assertIn("Review round 1 is recorded", error)
        self.assertNotIn("stays as it was", error)
        self.assertEqual((f.task()["state"], f.task()["reviews"][-1]["result"]), ("running", "pass"))
        self.assertEqual(f.task()["attention"], error)
        self.assertEqual(f.hc("send", "run"), [])


@ON_CI
class AReviewersPass(unittest.TestCase):
    def test_a_refused_publication_keeps_the_round_and_ends_the_reviewer(self):
        f = Fixture(self)
        f.seed(review={"round": 1, "of": 1, "reviewer": "t9"})
        f.github(prs=[], fail=AUTH)
        f.env["HC_TERMINAL_ID"] = "t9"
        error = f.refused("review", "1", "--folder", f.repo, "--pass")
        self.assertIn("gh couldn't", error)
        self.assertIn("Review round 1 is recorded and nothing merged here", error)
        self.assertNotIn("stays as it was", error)
        t = f.task()
        self.assertEqual((t["state"], t["reviews"][-1]["result"], t["reviews"][-1]["round"]), ("running", "pass", 1))
        self.assertNotIn("review", t)
        self.assertIn("gh couldn't", t["attention"])  # with its reviewer gone, it waits for the person
        self.assertEqual(f.ok("show", "1", "--folder", f.repo)["status"], "needs")
        self.assertNotIn("github", json.loads(f.saved()))  # no failed answer rode along
        ends = time.time() + 20  # the reviewer ends a moment after the command returns
        while time.time() < ends and not f.hc("kill"):
            time.sleep(0.2)
        self.assertEqual(f.hc("kill"), [["kill", "t9"]])

    def test_a_refusal_with_nothing_on_the_task_says_the_round_is_recorded_too(self):
        f = Fixture(self)
        f.github(prs=[f.pr()])
        f.adopt()
        f.github(prs=[f.pr(state="MERGED")])
        error = f.refused("review", "1", "--folder", f.repo, "--pass")
        self.assertIn("The tick finishes the task", error)
        self.assertTrue(error.endswith("Review round 1 is recorded."), error)


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
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"folder": folder, "artifacts": [{"id": "art-1", "title": "Proof", "files": files}]}, f)

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

    def test_json_carries_the_same_warning(self):
        out = self.f.ready()
        self.assertIn("No proof artifact found", out["message"])
        self.assertEqual(out["state"], "ready")

    def test_json_carries_a_proofs_line_too(self):
        self.artifact(["recipe.json"])
        out = self.f.ready("--proof", "art-1")
        self.assertIn("Proof: Proof.", out["message"])
        self.assertNotIn("No proof artifact found", out["message"])


@ON_CI
class AnOpenPullRequestIntoAnotherBase(unittest.TestCase):
    """ready refuses and names adopt, with nothing published, whether the recorded base is on GitHub
    (gh would open a second pull request) or isn't (gh would fail with no way forward)."""

    def refused(self, recorded):
        f = Fixture(self)
        f.seed(base=recorded)
        f.github(prs=[f.pr()])
        before = f.saved()
        error = f.no_ready()
        self.assertEqual(f.saved(), before)
        self.assertEqual((f.calls("pr", "create"), f.calls("pr", "comment"), f.remote_tip("task/1")), ([], [], None))
        self.assertIn(f"herdr-task adopt {f.ok('show', '1', '--folder', f.repo)['ref']} --pr 7", error)
        self.assertIn("into target, not " + recorded, error)
        self.assertIn(HANDOFF, error)
        return f

    def test_a_recorded_base_github_has(self):
        self.assertTrue(self.refused("main").remote_tip("main"))

    def test_a_recorded_base_github_doesnt_have(self):
        self.assertIsNone(self.refused("old-base").remote_tip("old-base"))

    def test_the_command_it_names_gets_the_task_through(self):
        f = self.refused("old-base")
        f.adopt()
        f.ready()
        t = f.task()
        self.assertEqual((t["state"], t["pr"]["number"], t["base"], f.calls("pr", "create")), ("ready", 7, "target", []))

    def test_one_into_its_own_base_is_kept_beside_it(self):
        f = Fixture(self)
        f.github(prs=[f.pr(), f.pr(number=8, url="https://github.com/o/r/pull/8", baseRefName="old-base")])
        f.ready()
        self.assertEqual((f.task()["state"], f.task()["pr"]["number"], f.calls("pr", "create")), ("ready", 8, []))

    def test_a_forks_stays_ignored(self):
        f = Fixture(self)
        f.github(prs=[f.pr(isCrossRepository=True)])
        f.ready()
        self.assertEqual((f.task()["pr"]["number"], len(f.calls("pr", "create"))), (9, 1))

    def test_accept_goes_on_waiting_for_the_person(self):
        """Saved by an older version: Accept takes only one into the task's own base."""
        f = Fixture(self)
        f.github(prs=[f.pr()])
        f.seed(state="ready", ready_at=1, attention='Couldn\'t open a pull request: for branch "task/1" already exists')
        before = f.saved()
        self.assertIn("needs attention first", f.refused("accept", "1", "--folder", f.repo))
        self.assertEqual(f.saved(), before)
        self.assertEqual((f.calls("pr", "create"), f.calls("pr", "merge")), ([], []))


@ON_CI
class TheCause(unittest.TestCase):
    """--json's one added key says whether gh or git failed, and nothing else gets it."""

    def setUp(self):
        self.f = Fixture(self)

    def says(self, cause, *args):
        out = self.f.refusal(*args, "--folder", self.f.repo)
        self.assertEqual((out.get("cause"), type(out["error"])), (cause, str))
        return out

    def ready(self):
        return ("ready", "1", "--summary", "Sign-in works again")

    def recorded(self):
        self.f.seed(state="ready", ready_at=1, pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})

    def test_a_gh_failure_is_ghs(self):
        self.f.github(prs=[], fail=AUTH)
        self.assertEqual(set(self.says("gh", *self.ready())), {"error", "cause"})

    def test_a_refused_push_is_gits(self):
        self.f.github(prs=[])
        self.f.refuse_pushes()
        self.assertEqual(set(self.says("git", *self.ready())), {"error", "cause"})

    def test_a_pull_request_gh_wont_open_is_ghs(self):
        self.f.github(prs=[], create="HTTP 422: Validation Failed")
        self.says("gh", *self.ready())

    def test_the_persons_wording_keeps_it(self):
        self.f.seed(state="ready", ready_at=1)
        self.f.github(prs=[], fail=AUTH)
        self.assertIn("then try again", self.says("gh", "accept", "1")["error"])

    def test_a_reviewers_pass_keeps_it(self):
        self.f.github(prs=[], fail=AUTH)
        self.says("gh", "review", "1", "--pass")

    def test_a_pull_request_gh_cant_read_at_accept(self):
        self.recorded()
        self.f.github(prs=[], fail=AUTH)
        self.says("gh", "accept", "1")

    def test_a_merge_gh_refused(self):
        self.recorded()
        self.f.github(prs=[self.f.pr()], merge="GraphQL: Something went wrong")
        self.says("gh", "accept", "1")

    def test_any_other_refusal_keeps_its_old_shape(self):
        self.f.github(prs=[self.f.pr()])
        self.assertEqual(set(self.says(None, "adopt", "1", "--pr", "seven")), {"error"})
        self.recorded()
        self.f.github(prs=[self.f.pr(state="CLOSED")])
        self.says(None, "accept", "1")


@ON_CI
class NoCredentialIsShownOrKept(unittest.TestCase):
    """gh's or git's words holding a remote URL with a token: the URL stays, its user and password go,
    in what's said and in what's saved."""

    def setUp(self):
        self.f = Fixture(self)

    def clean(self, error):
        self.assertIn("https://github.com/o/r.git", error)
        self.assertNotIn(SECRET, error)
        self.assertNotIn("x-access-token", error)
        self.assertNotIn(SECRET, self.f.saved())

    def recorded(self):
        self.f.seed(state="ready", ready_at=1, pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})

    def test_ghs_words(self):
        self.f.github(prs=[], fail=f"fatal: unable to access '{TOKEN_URL}/': 403")
        self.clean(self.f.no_ready())

    def test_ghs_words_for_the_person(self):
        self.f.seed(state="ready", ready_at=1)
        self.f.github(prs=[], fail=f"fatal: unable to access '{TOKEN_URL}/': 403")
        self.clean(self.f.refused("accept", "1", "--folder", self.f.repo))

    def test_gits_words(self):
        self.f.github(prs=[])
        self.f.refuse_pushes(f"denied for {TOKEN_URL}")
        self.clean(self.f.no_ready())

    def test_a_pull_request_gh_wont_open(self):
        self.f.github(prs=[], create=f"HTTP 403 for {TOKEN_URL}")
        self.clean(self.f.no_ready())

    def test_what_a_reviewers_pass_keeps(self):
        self.f.github(prs=[], fail=f"fatal: unable to access '{TOKEN_URL}/': 403")
        self.clean(self.f.refused("review", "1", "--folder", self.f.repo, "--pass"))
        self.clean(self.f.task()["attention"])

    def test_a_pull_request_gh_cant_read(self):
        self.recorded()
        self.f.github(prs=[], fail=f"fatal: unable to access '{TOKEN_URL}/': 403")
        self.clean(self.f.refused("accept", "1", "--folder", self.f.repo))

    def test_what_a_refused_merge_keeps(self):
        self.recorded()
        self.f.github(prs=[self.f.pr()], merge=f"HTTP 403 for {TOKEN_URL}")
        self.clean(self.f.refused("accept", "1", "--folder", self.f.repo))
        self.clean(self.f.task()["attention"])


@ON_CI
class AMergeOffTheTasksBase(unittest.TestCase):
    """An adopted pull request merged anywhere but the task's base: Accept, merge and the tick finish
    nothing, and the task says so until the person acts. `target` moves on GitHub first, so
    update_main() would show here."""

    WORDS = "merged into other, not target"
    UNSAID = "doesn't say into which branch"

    def setUp(self):
        self.f = f = Fixture(self)
        f.github(prs=[f.pr()])
        f.adopt()
        self.moved = f.sibling("another task merged")
        f.publish(self.moved, "target")

    def merged(self, **over):
        f = self.f
        f.github(prs=[f.pr(**{"state": "MERGED", "baseRefName": "other", "mergeCommit": {"oid": "e" * 40}, **over})])

    def tick(self):
        """A tick that reads the pull request now: it reads one at most once a minute."""
        self.f.edit(lambda d: d["tasks"][0]["pr"].update(checked=0))
        return self.f.ok("tick", "--folder", self.f.repo)

    def held(self, words=WORDS, state="ready"):
        """None of what finishing a task does, and the attention that says why."""
        f, t = self.f, self.f.task()
        self.assertEqual(t["state"], state)
        self.assertIn(words, t["attention"])
        for key in ("merged", "done_at"):
            self.assertNotIn(key, t)
        self.assertNotIn("main_watch", json.loads(f.saved()))
        self.assertTrue(os.path.isdir(f.wt))
        self.assertEqual((f.rev("refs/heads/task/1"), f.rev("refs/heads/target")), (f.tip, f.start))
        self.assertEqual(f.ok("show", "1", "--folder", f.repo)["status"], "needs")

    def finished(self):
        f, t = self.f, self.f.task()
        self.assertEqual((t["state"], t["merged"]), ("done", True))
        self.assertNotIn("attention", t)
        self.assertEqual(list(json.loads(f.saved())["main_watch"]), ["target"])
        self.assertFalse(os.path.isdir(f.wt))

    def test_accept_and_merge_refuse_and_finish_nothing(self):
        f = self.f
        f.ready()
        self.merged()
        for verb in ("accept", "merge"):
            with self.subTest(verb=verb):
                out = f.refusal(verb, "1", "--folder", f.repo)
                self.assertIn(self.WORDS, out["error"])
                self.assertNotIn("cause", out)  # GitHub answered: neither gh nor git failed
                self.held()
        self.assertEqual(f.calls("pr", "merge"), [])

    def test_without_json_it_exits_non_zero_too(self):
        f = self.f
        f.ready()
        self.merged()
        for verb in ("accept", "merge"):
            with self.subTest(verb=verb):
                p = f.run(verb, "1", "--folder", f.repo)
                self.assertEqual((p.returncode, p.stdout), (1, ""))
                self.assertIn(self.WORDS, p.stderr)

    def test_a_repeat_accept_says_the_same(self):
        f = self.f
        f.ready()
        self.merged()
        first = f.refused("accept", "1", "--folder", f.repo)
        said = f.task()["attention"]
        self.assertEqual(f.refused("accept", "1", "--folder", f.repo), first)
        self.assertEqual(f.task()["attention"], said)
        self.held()

    def test_a_merge_that_errs_and_went_through_elsewhere(self):
        """gh pr merge fails, and the read after it finds the pull request merged off the base."""
        f = self.f
        f.ready()
        for n, verb in enumerate(("accept", "merge"), 1):
            with self.subTest(verb=verb):
                f.github(prs=[f.pr()], merge="HTTP 502: Bad Gateway", merge_moves={"state": "MERGED", "baseRefName": "other"})
                self.assertIn(self.WORDS, f.refused(verb, "1", "--folder", f.repo))
                self.assertEqual(len(f.calls("pr", "merge")), n)
                self.held()

    def test_a_merge_that_errs_with_no_word_on_its_base_holds(self):
        f = self.f
        f.ready()
        f.github(prs=[f.pr()], merge="HTTP 502: Bad Gateway", merge_moves={"state": "MERGED", "baseRefName": None})
        self.assertIn(self.UNSAID, f.refused("accept", "1", "--folder", f.repo))
        self.held(self.UNSAID)

    def test_a_merge_that_errs_and_went_through_on_the_base_finishes_as_before(self):
        f = self.f
        f.ready()
        f.github(prs=[f.pr()], merge="HTTP 502: Bad Gateway", merge_moves={"state": "MERGED"})
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        self.finished()
        self.assertEqual(f.rev("refs/heads/target"), self.moved)  # update_main() ran

    def test_the_tick_holds_a_ready_task_and_reports_it_once(self):
        f = self.f
        f.ready()
        self.merged()
        first = self.tick()
        self.assertEqual((first["attention"], first["done"]), ([1], []))
        self.held()
        said = f.task()["attention"]
        for _ in range(2):
            again = self.tick()
            self.assertEqual((again["attention"], again["done"]), ([], []))
            self.assertEqual(f.task()["attention"], said)
        self.held()
        self.assertEqual(f.calls("pr", "merge"), [])

    def test_the_tick_holds_a_running_task_and_reports_it_once(self):
        f = self.f
        self.merged()
        first = self.tick()
        self.assertEqual((first["attention"], first["done"]), ([1], []))
        self.held(state="running")
        again = self.tick()
        self.assertEqual((again["attention"], again["done"]), ([], []))
        self.held(state="running")

    def test_a_refused_accept_isnt_reported_again_by_the_tick(self):
        f = self.f
        f.ready()
        self.merged()
        f.refused("accept", "1", "--folder", f.repo)
        self.assertEqual(self.tick()["attention"], [])
        self.held()

    def test_the_hold_outlasts_what_the_tick_clears(self):
        """MOVED's words go once the pull request is put back. These never do, whatever gh says next."""
        f = self.f
        f.ready()
        self.merged()
        self.tick()
        f.github(prs=[f.pr()])
        self.tick()
        self.held()
        f.github(prs=[], fail=AUTH)
        self.assertEqual(self.tick()["attention"], [])
        self.held()

    def test_ready_changes_nothing_and_says_what_is_true(self):
        f = self.f
        f.ready()
        self.merged()
        self.tick()
        before = f.saved()
        self.assertIn("holds it for the person", f.no_ready())
        self.assertEqual(f.saved(), before)

    def test_the_step_it_names_works_and_leaves_the_work(self):
        f = self.f
        f.ready()
        self.merged()
        self.tick()
        ref = f.ok("show", "1", "--folder", f.repo)["ref"]
        self.assertIn(f"`herdr-task done {ref}`", f.task()["attention"])
        f.ok("done", ref, "--folder", f.repo)
        t = f.task()
        self.assertEqual(t["state"], "done")
        self.assertNotIn("merged", t)  # the task's base never got it
        self.assertNotIn("attention", t)
        self.assertTrue(os.path.isdir(f.wt))
        self.assertEqual(f.rev("refs/heads/task/1"), f.tip)
        self.assertEqual(self.tick()["done"], [])

    def test_that_step_counts_the_work_once_it_is_in_the_base(self):
        f = self.f
        f.ready()
        self.merged()
        self.tick()
        f.git(f.repo, "branch", "-f", "target", f.tip)
        self.assertTrue(f.ok("done", "1", "--folder", f.repo)["merged"])

    def test_an_answer_that_doesnt_say_where_holds(self):
        f = self.f
        f.ready()
        for value in (None, "", 7):
            with self.subTest(value=value):
                self.merged(baseRefName=value)
                self.assertEqual(self.tick()["done"], [])
                self.held(self.UNSAID)
                self.assertIn(self.UNSAID, f.refused("accept", "1", "--folder", f.repo))
                self.held(self.UNSAID)

    def test_an_answer_with_no_base_at_all_holds_until_one_says(self):
        f = self.f
        f.ready()
        # As gh answers: which pull request it is, and no base at all.
        f.github(prs=[f.pr()], answer=json.dumps({"state": "MERGED", "url": "https://github.com/o/r/pull/7"}))
        self.assertEqual(self.tick()["attention"], [1])
        self.held(self.UNSAID)
        self.merged(baseRefName="target")
        self.assertEqual(self.tick()["done"], [1])
        self.finished()

    def test_merged_into_its_base_accept_and_merge_finish_as_before(self):
        for verb in ("accept", "merge"):
            with self.subTest(verb=verb):
                self.setUp()
                f = self.f
                f.ready()
                self.merged(baseRefName="target")
                f.ok(verb, "1", "--folder", f.repo)
                self.finished()
                self.assertEqual(json.loads(f.saved())["main_watch"]["target"]["merged"][0]["sha"], "e" * 40)
                self.assertEqual((f.rev("refs/heads/target"), f.calls("pr", "merge")), (self.moved, []))


@ON_CI
class AnUnadoptedMergeIsAsItWas(unittest.TestCase):
    """No adoption, no check: a pull request herdr-task opened finishes on any merge, as it always has."""

    def recorded(self):
        f = Fixture(self)
        f.seed(state="ready", ready_at=1, base="target", pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})
        f.github(prs=[f.pr(state="MERGED", baseRefName="other", mergeCommit={"oid": "e" * 40})])
        return f

    def test_the_tick(self):
        f = self.recorded()
        self.assertEqual(f.ok("tick", "--folder", f.repo)["done"], [1])
        self.assertEqual((f.task()["state"], f.task()["merged"]), ("done", True))

    def test_accept(self):
        f = self.recorded()
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        self.assertEqual((f.task()["state"], f.task()["merged"]), ("done", True))


@ON_CI
class AdoptionClearsWhatItAnswers(unittest.TestCase):
    """A reviewer's refused pass is what leaves publishing's words on a task; adoption takes those it
    answers, and only those."""

    def refused_pass(self, f, words):
        f.refused("review", "1", "--folder", f.repo, "--pass")
        self.assertIn(words, f.task()["attention"])
        self.assertIn("Review round 1 is recorded", f.task()["attention"])

    def adopted(self, f):
        f.github(prs=[f.pr()])
        self.assertTrue(f.adopt()["adopted"])

    def test_no_second_pull_request(self):
        f = Fixture(self)
        f.github(prs=[f.pr()])
        self.refused_pass(f, "no second pull request")
        self.adopted(f)
        self.assertNotIn("attention", f.task())

    def test_a_refused_push(self):
        f = Fixture(self)
        f.github(prs=[])
        f.refuse_pushes()
        self.refused_pass(f, "git couldn't push task/1 to origin")
        self.adopted(f)
        self.assertNotIn("attention", f.task())

    def test_a_pull_request_gh_wouldnt_open(self):
        f = Fixture(self)
        f.github(prs=[], create="HTTP 422: Validation Failed")
        self.refused_pass(f, "Couldn't open a pull request")
        self.adopted(f)
        self.assertNotIn("attention", f.task())

    def test_what_is_kept_from_elsewhere_and_earlier(self):
        """A local merge asked of its agent goes through the pull request now; the other is an older
        version's refused push."""
        for words in ("Couldn't ask for the merge: no agent", "Couldn't push task/1: denied"):
            with self.subTest(words=words):
                f = Fixture(self)
                f.seed(attention=words, auto_merge="checks")
                self.adopted(f)
                self.assertNotIn("attention", f.task())

    def test_gh_failing_stays(self):
        """gh answering this adopt says nothing of the access that failed for whoever ran the review."""
        f = Fixture(self)
        f.github(prs=[], fail=AUTH)
        self.refused_pass(f, "gh couldn't")
        self.adopted(f)
        self.assertIn("gh couldn't", f.task()["attention"])

    def test_a_worktree_thats_gone_stays(self):
        f = Fixture(self)
        shutil.rmtree(f.wt)
        self.refused_pass(f, "is gone")
        self.adopted(f)
        self.assertIn("is gone", f.task()["attention"])

    def test_anything_else_stays(self):
        f = Fixture(self)
        f.seed(attention="Couldn't start: no such agent")
        self.adopted(f)
        self.assertEqual(f.task()["attention"], "Couldn't start: no such agent")


@ON_CI
class ATagNamedLikeABranch(unittest.TestCase):
    """git reads a bare name's tag before its branch, and git push refuses a bare name that is both.
    Branches go by their full names, so the tag changes nothing."""

    def tagged(self, *more):
        f = Fixture(self, *more)
        f.git(f.repo, "tag", "task/1", f.sibling("only a tag"))
        return f

    def test_a_published_head_is_still_read_as_the_branch(self):
        """The remote turns every push away, so ready can only pass by reading the branch's own tip."""
        f = Fixture(self)
        f.github(prs=[f.pr()])
        f.git(f.repo, "push", "-q", "origin", "task/1")
        f.adopt()
        f.refuse_pushes()
        f.git(f.repo, "tag", "task/1", f.start)
        f.ready()
        self.assertEqual((f.task()["state"], f.task()["pr"]["number"]), ("ready", 7))

    def test_the_branch_is_pushed_and_tracked_and_the_tag_stays_here(self):
        f = self.tagged()
        f.ready()
        self.assertEqual((f.task()["state"], f.remote_tip("task/1")), ("ready", f.tip))
        self.assertEqual((f.git(f.repo, "config", "branch.task/1.remote"), f.git(f.repo, "config", "branch.task/1.merge")),
                         ("origin", "refs/heads/task/1"))
        self.assertEqual((f.rev("refs/remotes/origin/task/1"), f.git(f.bare, "tag", "--list")), (f.tip, ""))

    def test_the_lease_still_refuses_on_the_tracking_ref(self):
        f = Fixture(self)
        f.github(prs=[f.pr()])
        f.git(f.repo, "push", "-q", "origin", "task/1")
        f.adopt()
        f.git(f.repo, "update-ref", "-d", "refs/remotes/origin/task/1")
        f.commit(f.wt, "one more fix")
        f.git(f.repo, "tag", "task/1", f.start)
        self.assertIn("stale info", f.no_ready())
        self.assertEqual(f.remote_tip("task/1"), f.tip)

    def test_ready_finds_the_open_pull_request_by_the_branch(self):
        f = self.tagged()
        f.github(prs=[f.pr(baseRefName="old-base")])
        f.ready()
        self.assertEqual((f.task()["pr"]["number"], f.calls("pr", "create")), (7, []))

    def test_accept_finds_the_open_pull_request_by_the_branch(self):
        """Accept's own route to pr_adopt(): nothing read by publish() first."""
        f = self.tagged()
        f.github(prs=[f.pr(baseRefName="old-base")])
        f.seed(state="ready", ready_at=1, attention='Couldn\'t open a pull request: for branch "task/1" already exists')
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        self.assertEqual((f.task()["state"], f.task()["pr"]["number"]), ("done", 7))

    def test_a_tag_holding_the_work_isnt_the_base_holding_it(self):
        """ready would say nothing to merge and finish the task, taking its branch."""
        f = Fixture(self)
        f.github(prs=[f.pr()])
        f.adopt()
        f.git(f.repo, "tag", "target", f.tip)
        f.ready()
        t = f.task()
        self.assertEqual((t["state"], t["own"], f.rev("refs/heads/task/1")), ("ready", f.tip, f.tip))
        self.assertNotIn("nothing_to_merge", t)
        self.assertFalse(f.ok("done", "1", "--folder", f.repo).get("merged"))

    def test_the_remote_copy_of_the_base_still_counts_beside_a_tag(self):
        f = Fixture(self)
        f.github(prs=[f.pr()])
        f.git(f.repo, "fetch", "-q", "origin", "target:refs/remotes/origin/target")
        f.git(f.repo, "branch", "-D", "target")
        f.adopt()
        f.ready()
        f.git(f.repo, "update-ref", "refs/remotes/origin/target", f.tip)
        f.git(f.repo, "tag", "target", f.start)
        self.assertTrue(f.ok("done", "1", "--folder", f.repo)["merged"])

    def test_a_base_that_is_a_commit_stays_one(self):
        """A folder on no branch records its commit as the base (current_base())."""
        f = Fixture(self, False)
        f.seed(base=f.tip, own=f.tip)
        self.assertTrue(f.ok("done", "1", "--folder", f.repo)["merged"])
        f = Fixture(self, False)
        f.seed(base=f.tip)
        # SHEP-96: nothing to merge waits in Ready for the person's Accept, its words capitalized.
        self.assertIn("Nothing to merge", f.ready()["message"])
        self.assertEqual((f.task()["state"], f.task().get("nothing_to_merge")), ("ready", True))

    def test_a_remote_tag_named_like_the_base_never_lands_on_it(self):
        f = Fixture(self)
        f.github(prs=[f.pr()])
        f.adopt()
        f.ready()
        f.git(f.repo, "push", "-q", "origin", f"{f.sibling('only a tag')}:refs/tags/target")
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        self.assertEqual(f.rev("refs/heads/target"), f.start)

    def on_main(self):
        f = Fixture(self)
        f.seed(base="main")
        f.github(prs=[f.pr(baseRefName="main")])
        f.ready()
        return f

    def test_the_checked_out_base_catches_up_beside_a_tag_of_its_name(self):
        f = self.on_main()
        f.git(f.repo, "tag", "main", f.first)
        moved = f.sibling("merged on GitHub")
        f.publish(moved, "main")
        f.ok("accept", "1", "--folder", f.repo)
        self.assertEqual(f.rev("refs/heads/main"), moved)

    def test_a_tag_called_remote_slash_base_never_lands_on_it(self):
        f = self.on_main()
        f.git(f.repo, "tag", "origin/main", f.sibling("only a tag"))
        f.ok("accept", "1", "--folder", f.repo)
        self.assertEqual(f.rev("refs/heads/main"), f.start)

    def test_a_local_merge_lands_the_branch_not_the_tag(self):
        self.tagged(False).merges_here()

    def test_a_local_merge_into_a_base_not_checked_out_too(self):
        f = self.tagged(False)
        f.seed(base="target")
        f.merges_here("refs/heads/target")

    def test_a_local_merge_beside_a_tag_named_like_the_base(self):
        f = Fixture(self, False)
        f.git(f.repo, "tag", "main", f.first)
        f.merges_here("refs/heads/main")


@ON_CI
class AGhThatCantRun(unittest.TestCase):
    """A gh that is there and can't run says nothing about GitHub, so it's never taken for gh's no.
    Tried on a host only gh can place, with no name saved: what a missing gh merges locally."""

    def elsewhere(self):
        f = Fixture(self, False)
        f.git(f.repo, "remote", "add", "origin", ENTERPRISE)
        f.github(prs=[])
        return f

    def refuses(self, f):
        """ready and Accept both, in plain words and as gh's, with nothing changed or merged."""
        before = f.saved()
        out = f.refusal("ready", "1", "--folder", f.repo, "--summary", "Sign-in works again")
        self.assertIn("gh couldn't", out["error"])
        self.assertIn("can't run here", out["error"])
        self.assertNotIn("isn't installed", out["error"])
        self.assertEqual((out["cause"], f.saved()), ("gh", before))
        f.seed(state="ready", ready_at=1)
        before = f.saved()
        out = f.refusal("accept", "1", "--folder", f.repo)
        self.assertIn("then try again", out["error"])
        self.assertEqual((out["cause"], f.saved(), f.rev("main")), ("gh", before, f.start))

    def test_a_named_gh_that_cant_run(self):
        """In turn: none there, a wrapper's interpreter gone, not executable, a folder, not a program."""
        for name, body, mode in (("no-such-gh", None, None), ("wrapper", "#!/no/such/interpreter\n", 0o755),
                                 ("plain-file", "#!/bin/sh\n", 0o644), ("folder", None, None), ("text", "not a program\n", 0o755)):
            with self.subTest(name=name):
                f = self.elsewhere()
                path = os.path.join(f.tmp, name)
                if name == "folder":
                    os.makedirs(path)
                elif body:
                    f.program(path, body, mode)
                f.env["HERDR_TASK_GH"] = path
                self.refuses(f)

    def test_a_gh_on_path_that_cant_run(self):
        for body, mode in (("#!/no/such/interpreter\n", 0o755), ("#!/bin/sh\n", 0o644)):
            with self.subTest(mode=oct(mode)):
                f = self.elsewhere()
                f.without_gh()
                f.program(os.path.join(os.path.dirname(f.gh_route), "gh"), body, mode)
                self.refuses(f)

    def test_on_a_github_remote_it_isnt_called_missing_either(self):
        f = Fixture(self)
        f.env["HERDR_TASK_GH"] = os.path.join(f.tmp, "no-such-gh")
        self.refuses(f)

    def test_its_words_are_plain(self):
        f = self.elsewhere()
        f.env["HERDR_TASK_GH"] = os.path.join(f.tmp, TOKEN_URL)
        error = f.no_ready()
        self.assertIn("can't run here", error)
        self.assertNotIn(SECRET, error)

    def test_a_recorded_pull_request_says_so_too(self):
        f = Fixture(self)
        f.seed(state="ready", ready_at=1, pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})
        f.env["HERDR_TASK_GH"] = os.path.join(f.tmp, "no-such-gh")
        out = f.refusal("accept", "1", "--folder", f.repo)
        self.assertIn("Couldn't reach pull request #7", out["error"])
        self.assertIn("can't run here", out["error"])
        self.assertEqual((out["cause"], f.task()["state"]), ("gh", "ready"))

    def asked_from(self, f, folder):
        """gh's reason from a folder that's gone. Called directly, as no command gets this far: git
        finds no remotes there first, and the task list's own folder can't be gone."""
        code = ("import sys; sys.dont_write_bytecode = True; sys.path.insert(0, sys.argv[1]);"
                "from herdr_task.github import gh; print(gh('auth', 'status', cwd=sys.argv[2])[2])")
        p = subprocess.run([sys.executable, "-c", code, BIN, folder], capture_output=True, text=True, env=f.env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_a_folder_thats_gone_isnt_gh_missing(self):
        f = Fixture(self, False)
        f.without_gh()
        f.program(os.path.join(os.path.dirname(f.gh_route), "gh"), "#!/bin/sh\n")
        said = self.asked_from(f, os.path.join(f.tmp, "gone"))
        self.assertIn("can't run here", said)
        self.assertNotIn("isn't installed", said)

    def test_with_no_gh_at_all_a_folder_thats_gone_still_is(self):
        f = Fixture(self, False)
        f.without_gh()
        self.assertIn("isn't installed", self.asked_from(f, os.path.join(f.tmp, "gone")))


@ON_CI
class TheCommandLine(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def help(self, *args):
        p = self.f.run(*args, "--help")
        self.assertEqual(p.returncode, 0, p.stderr)
        return " ".join(p.stdout.split())

    def test_adopt_help_says_what_it_needs_and_shows_how(self):
        said = self.help("adopt")
        for words in ("--pr", "started task", "open pull request for its branch", "at exactly its tip", "one merge base",
                      "Never creates, pushes or merges", "herdr-task adopt HAT-4 --pr 123"):
            self.assertIn(words, said)

    def test_the_route_to_gh_can_be_found(self):
        self.assertIn("HERDR_TASK_GH", self.help())

    def test_merge_help_says_what_it_does(self):
        said = self.help()
        self.assertIn("its agent is asked to merge it here", said)
        self.assertNotIn("ask the task's agent to merge it", said)

    def test_adopt_without_a_pull_request_is_a_usage_error(self):
        f = self.f
        before, asked = f.saved(), f.calls()
        p = f.run("adopt", "1", "--folder", f.repo)
        self.assertEqual(p.returncode, 2)
        self.assertIn("--pr", p.stderr)
        self.assertEqual((f.saved(), f.calls()), (before, asked))

    def test_a_refusal_without_json_goes_to_stderr(self):
        f = self.f
        p = f.run("adopt", "1", "--folder", f.repo, "--pr", "seven")
        self.assertEqual((p.returncode, p.stdout), (1, ""))
        self.assertTrue(p.stderr.startswith("herdr-task: "), p.stderr)
        self.assertIn("give its number or its link", p.stderr)


if __name__ == "__main__":
    unittest.main()
