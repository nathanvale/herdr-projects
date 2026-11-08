"""The forge seam (herdr_task/forge.py) across herdr-task's own command line: `ready` and `merge` as
their own processes, on test_native_publication.py's Fixture (a throwaway repo, a bare remote reached
through url.insteadOf, a stand-in hc first on PATH and a recording stand-in gh behind HERDR_TASK_GH).

Oracle: the gh argv this file writes out, what the bare remote holds, and the task list reread after
each process. Wrong implementations these catch: sending a pull request saved for another provider
or host to the default GitHub host (gh is called at all); trusting `--repo` without checking which
pull request GitHub answered for (a push, comment or merge follows); pushing before the saved one is
read and confirmed; adopting another repository's pull request; reading a saved one gh can't answer
as gone and publishing over it; qualifying or dropping legacy records (the saved record changes).
They prove what herdr-task does with gh's answers, not GitHub's own answers or a real push.

Runs only on CI, as the publication tests: herdr-task's commands never run from a test on a
person's machine."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_native_publication as publication  # noqa: E402

LEGACY = {"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"}
FOREIGN_HOST = {"provider": "github", "host": "github.example.com", "repo": "o/r", "number": 7,
                "url": "https://github.example.com/o/r/pull/7"}
BITBUCKET = {"provider": "bitbucket", "host": "bitbucket.org", "repo": "o/r", "number": 7,
             "url": "https://bitbucket.org/o/r/pull-requests/7"}
OTHER_REPO = "https://github.com/o/fork/pull/7"
OTHER_HOST = "https://github.example.com/o/r/pull/7"
VIEW = ["pr", "view", "7", "--repo", "o/r", "--json", "state,mergeable,headRefOid,baseRefName,statusCheckRollup,mergeCommit,url"]
SUMMARY = "Sign-in works again"  # the Fixture's ready --summary
COMMENT = ["pr", "comment", "7", "--repo", "o/r", "--body", SUMMARY]

# The recording gh route, but `pr view` gets no answer, as a GitHub that errs: every other call as before.
NO_VIEW_GH = '''#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:3] == ["pr", "view"]:
    with open(os.environ["FAKE_GH_LOG"], "a") as f:
        f.write(json.dumps(sys.argv[1:]) + "\\n")
    print("HTTP 502: Bad Gateway (https://api.github.com/graphql)", file=sys.stderr)
    sys.exit(1)
os.execv(sys.executable, [sys.executable, os.environ["REAL_GH_ROUTE"]] + sys.argv[1:])
'''


def fixture(test):
    f = publication.Fixture(test)
    f.env.pop("GH_HOST", None)  # gh's default host, github.com, is the one herdr-task reaches
    return f


def unasked(f):
    """gh's log emptied: what the command under test asks it, alone, is what follows."""
    open(f.log, "w").close()


def core(pr):
    """A saved pull request as written: its legacy fields, and nothing qualifying it."""
    return {k: v for k, v in pr.items() if k not in ("checked", "watch")}


@publication.ON_CI
class MergeThroughTheForge(unittest.TestCase):
    def ready_with(self, pr, **view):
        f = fixture(self)
        f.seed(state="ready", ready_at=1, base="target", pr=dict(pr))
        f.github(prs=[f.pr(**view)])
        return f

    def merge_call(self, f):
        return ["pr", "merge", "7", "--repo", "o/r", "--squash", "--delete-branch", "--match-head-commit", f.tip]

    def test_a_legacy_pull_request_merges_on_github(self):
        f = self.ready_with(LEGACY)
        self.assertTrue(f.ok("merge", "1", "--folder", f.repo)["merged"])
        self.assertEqual(f.calls("pr", "view")[0], VIEW)
        self.assertEqual(f.calls("pr", "merge"), [self.merge_call(f)])
        t = f.task()
        self.assertEqual((t["state"], core(t["pr"])), ("done", LEGACY))  # never qualified on the way

    def test_another_providers_pull_request_reaches_no_host(self):
        f = self.ready_with(BITBUCKET)
        unasked(f)
        error = f.refused("merge", "1", "--folder", f.repo)
        self.assertIn("bitbucket", error)
        self.assertIn("nothing was sent", error)
        self.assertEqual(f.calls(), [])
        self.assertEqual((f.task()["state"], f.task()["pr"]), ("ready", BITBUCKET))

    def test_one_saved_for_another_host_reaches_no_host(self):
        f = self.ready_with(FOREIGN_HOST)
        unasked(f)
        error = f.refused("merge", "1", "--folder", f.repo)
        self.assertIn("github.example.com", error)
        self.assertIn("nothing was sent", error)
        self.assertIn("set GH_HOST to github.example.com", error)
        self.assertEqual(f.calls(), [])
        self.assertEqual((f.task()["state"], f.task()["pr"]), ("ready", FOREIGN_HOST))

    def test_github_answering_for_another_repository_merges_nothing(self):
        f = self.ready_with(LEGACY, url=OTHER_REPO)
        error = f.refused("merge", "1", "--folder", f.repo)
        self.assertIn(f"not this task's pull request {LEGACY['url']}", error)
        self.assertEqual(f.calls("pr", "merge"), [])
        self.assertEqual(f.task()["state"], "ready")
        self.assertTrue(os.path.isdir(f.wt))


@publication.ON_CI
class PublishThroughTheForge(unittest.TestCase):
    """Ready's publication: its branch pushed and its pull request kept, adopted or refused."""

    def nothing_published(self, f, before):
        self.assertEqual(f.saved(), before)  # not Ready, no summary: the task as it was
        self.assertEqual(f.task()["state"], "running")
        self.assertIsNone(f.remote_tip("task/1"))
        self.assertEqual((f.calls("pr", "comment"), f.calls("pr", "create"), f.calls("pr", "merge")), ([], [], []))

    def test_its_open_pull_request_is_kept_and_told(self):
        f = fixture(self)
        f.seed(pr=dict(LEGACY))
        f.github(prs=[f.pr(baseRefName="old-base")])
        f.ready()
        t = f.task()
        self.assertEqual((t["state"], core(t["pr"])), ("ready", LEGACY))
        self.assertEqual(f.remote_tip("task/1"), f.tip)
        self.assertEqual((f.calls("pr", "comment"), f.calls("pr", "create")), ([COMMENT], []))

    def test_an_open_one_for_its_branch_is_adopted(self):
        f = fixture(self)
        f.github(prs=[f.pr(baseRefName="old-base")])
        f.ready()
        t = f.task()
        self.assertEqual((t["state"], core(t["pr"])), ("ready", LEGACY))  # recorded as before: unqualified, GitHub's
        self.assertEqual((f.calls("pr", "comment"), f.calls("pr", "create")), ([COMMENT], []))

    def test_another_repositorys_pull_request_is_never_adopted(self):
        f = fixture(self)
        f.github(prs=[f.pr(baseRefName="old-base", url=OTHER_REPO)])
        f.ready()
        self.assertEqual(f.task()["pr"]["number"], 9)  # its own opened instead, as gh opens it
        self.assertEqual(len(f.calls("pr", "create")), 1)
        self.assertNotIn(COMMENT, f.calls("pr", "comment"))

    def test_one_saved_for_another_host_is_refused_before_any_gh_call(self):
        f = fixture(self)
        f.seed(pr=dict(FOREIGN_HOST))
        f.github(prs=[f.pr(baseRefName="old-base")])
        before = f.saved()
        unasked(f)
        error = f.no_ready()
        self.assertIn("github.example.com", error)
        self.assertIn("nothing was sent", error)
        self.assertEqual(f.calls(), [])
        self.nothing_published(f, before)

    def test_github_answering_for_another_repository_publishes_nothing(self):
        f = fixture(self)
        f.seed(pr=dict(LEGACY))
        f.github(prs=[f.pr(baseRefName="old-base", url=OTHER_REPO)])
        before = f.saved()
        self.assertIn(f"not this task's pull request {LEGACY['url']}", f.no_ready())
        self.nothing_published(f, before)

    def test_ready_refuses_when_a_saved_pull_request_cannot_be_read_and_nothing_merges(self):
        f = fixture(self)
        f.publish(f.tip, "task/1")  # its pull request was opened at its tip
        f.seed(pr=dict(LEGACY))
        f.github(prs=[f.pr(baseRefName="old-base")])
        newer = f.commit(f.wt, "one more fix")
        f.env.update(HERDR_TASK_GH=f.program(os.path.join(f.tmp, "bin/gh-no-view"), NO_VIEW_GH), REAL_GH_ROUTE=f.gh_route)
        before = f.saved()
        error = f.no_ready()
        self.assertIn("gh couldn't read pull request #7", error)
        self.assertIn("HTTP 502", error)
        self.assertEqual(f.saved(), before)  # not Ready: the task as it was
        self.assertEqual(f.task()["state"], "running")
        self.assertEqual(f.remote_tip("task/1"), f.tip)  # the newer commit wasn't pushed
        self.assertEqual((f.calls("pr", "comment"), f.calls("pr", "create")), ([], []))
        self.assertIn("isn't ready", f.refused("accept", "1", "--folder", f.repo))
        self.assertIn("Couldn't reach pull request #7", f.refused("merge", "1", "--folder", f.repo))
        self.assertEqual(f.calls("pr", "merge"), [])
        self.assertEqual((f.task()["state"], core(f.task()["pr"])), ("running", LEGACY))
        self.assertEqual((f.rev("refs/heads/task/1"), os.path.isdir(f.wt)), (newer, True))


@publication.ON_CI
class TheMergedListAnswersForThisRepository(unittest.TestCase):
    """SHEP-59's merged list (the tick's read for a Ready task with no pull request recorded): a merged
    pull request at the task's tip counts only when its own link is in this folder's repository on
    the host gh is sent to. Another's is never recorded, and nothing finishes or is cleaned up."""

    def tick_with_merged(self, url):
        f = fixture(self)
        f.seed(state="ready", ready_at=1, own=f.tip, head=f.tip)
        f.github(prs=[f.pr(state="MERGED", baseRefName="old-base", url=url, mergeCommit={"oid": "e" * 40})])
        return f, f.ok("tick", "--folder", f.repo)

    def test_one_in_this_repository_finishes_the_task(self):
        f, report = self.tick_with_merged(LEGACY["url"])
        self.assertEqual(report["done"], [1])
        self.assertEqual((f.task()["state"], core(f.task()["pr"])), ("done", LEGACY))

    def test_one_from_another_repository_or_host_is_never_recorded(self):
        for url in (OTHER_REPO, OTHER_HOST):
            with self.subTest(url=url):
                f, report = self.tick_with_merged(url)
                self.assertEqual(report["done"], [])
                t = f.task()
                self.assertEqual(t["state"], "ready")
                for key in ("pr", "merged", "done_at"):
                    self.assertNotIn(key, t)
                self.assertNotIn("main_watch", json.loads(f.saved()))
                self.assertEqual((os.path.isdir(f.wt), f.rev("refs/heads/task/1")), (True, f.tip))


@publication.ON_CI
class AFolderOnAnotherHost(unittest.TestCase):
    """The host gh places a folder on (its link in `gh repo view`, an SSH alias resolved by gh) against
    the one `--repo owner/name` is sent to (GH_HOST, else github.com): publication refuses when they
    differ or the host is unknown, saying to set GH_HOST, and works once it's that host."""

    def remote(self, url, **gh):
        f = fixture(self)
        f.git(f.repo, "remote", "set-url", "origin", url)
        f.git(f.repo, "config", "--add", f"url.{f.bare}.insteadOf", url)
        f.github(prs=[], **gh)
        return f

    def refuses(self, f, *words):
        before = f.saved()
        error = f.no_ready()
        for w in words:
            self.assertIn(w, error)
        self.assertIn("nothing was pushed", error)
        self.assertEqual(f.saved(), before)  # not Ready: the task as it was
        self.assertIsNone(f.remote_tip("task/1"))
        self.assertEqual((f.calls("pr", "create"), f.calls("pr", "comment"), f.calls("api")), ([], [], []))

    def test_an_enterprise_remote_refuses_and_names_gh_host(self):
        self.refuses(self.remote(publication.ENTERPRISE), "git.example.com", "Set GH_HOST to git.example.com")

    def test_an_ssh_alias_is_checked_as_gh_resolves_it(self):
        self.refuses(self.remote(publication.ALIAS, host="git.example.com"), "Set GH_HOST to git.example.com")
        f = self.remote(publication.ALIAS, host="github.com")
        f.ready()
        self.assertEqual((f.task()["state"], f.remote_tip("task/1")), ("ready", f.tip))

    def test_a_link_with_no_host_refuses(self):
        self.refuses(self.remote(publication.URL, repo_url=None), "didn't say which host")

    def test_with_gh_host_set_it_publishes_there(self):
        f = self.remote(publication.ENTERPRISE)
        f.env["GH_HOST"] = "git.example.com"
        f.ready()
        t = f.task()
        self.assertEqual((t["state"], t["pr"]["url"]), ("ready", "https://git.example.com/o/r/pull/9"))
        self.assertEqual(f.remote_tip("task/1"), f.tip)

@publication.ON_CI
class AnExistingPullRequestOnAnotherHost(unittest.TestCase):
    """issue #7: a folder gh places on an Enterprise host, GH_HOST unset, and a same-named github.com
    pull request at the task's branch and head. Adopt, Accept's already-exists path, merge, Accept
    with one recorded and the tick's merged read all refuse before any call about it (forge.reach()):
    nothing recorded, merged or finished, and the worktree and branch stay."""

    def setUp(self):
        self.f = f = fixture(self)
        f.git(f.repo, "remote", "set-url", "origin", publication.ENTERPRISE)
        f.git(f.repo, "config", "--add", f"url.{f.bare}.insteadOf", publication.ENTERPRISE)
        f.github(prs=[f.pr()])

    def refused(self, *args, words="Set GH_HOST to git.example.com"):
        f = self.f
        before = f.task()
        unasked(f)
        error = f.refused(*args, "--folder", f.repo)
        self.assertIn(words, error)
        t = f.task()
        self.assertEqual(t, before)  # the task as it was: no pull request recorded, not done, no merged_head
        for key in ("merged", "merged_head", "done_at"):
            self.assertNotIn(key, t)
        self.assertEqual(f.calls("pr"), [])  # never asked to view, list or merge it
        self.assertEqual((os.path.isdir(f.wt), f.rev("refs/heads/task/1")), (True, f.tip))
        return error

    def recorded(self):
        self.f.seed(state="ready", ready_at=1, base="target", pr=dict(LEGACY))

    def test_adopt_refuses(self):
        self.refused("adopt", "1", "--pr", "7")
        self.assertNotIn("pr", self.f.task())

    def test_accepts_already_exists_path_refuses(self):
        self.f.seed(state="ready", ready_at=1, base="target",
                    attention='Couldn\'t open a pull request: a pull request for branch "task/1" already exists')
        self.refused("accept", "1")
        self.assertNotIn("pr", self.f.task())

    def test_merge_refuses(self):
        self.recorded()
        self.refused("merge", "1")

    def test_accept_with_a_recorded_pull_request_refuses(self):
        self.recorded()
        self.refused("accept", "1")

    def test_the_ticks_merged_read_records_nothing(self):
        f = self.f
        f.seed(own=f.tip, head=f.tip)  # Working, its agent between turns
        f.github(prs=[f.pr(state="MERGED", baseRefName="old-base", mergeCommit={"oid": "e" * 40})])
        unasked(f)
        self.assertEqual(f.ok("tick", "--folder", f.repo)["done"], [])
        t = f.task()
        self.assertEqual(t["state"], "running")
        for key in ("pr", "merged", "merged_head", "done_at"):
            self.assertNotIn(key, t)
        self.assertEqual(f.calls("pr"), [])
        self.assertEqual((os.path.isdir(f.wt), f.rev("refs/heads/task/1")), (True, f.tip))

    def test_a_folder_host_gh_didnt_name_refuses(self):
        self.f.git(self.f.repo, "remote", "set-url", "origin", publication.URL)
        self.f.github(prs=[self.f.pr()], repo_url=None)
        self.recorded()
        self.refused("merge", "1", words="didn't say which host")


if __name__ == "__main__":
    unittest.main()
