"""Bitbucket publication (B2) across herdr-task's own command line: `ready` (push, draft, ready for
review), `show` and `accept`/`merge` as their own processes, on test_native_publication.py's Fixture in a
folder whose remote is on bitbucket.org.

Bitbucket here is test_bitbucket.py's: its REST API behind a local CONNECT proxy that opens only
api.bitbucket.org:443, with a throwaway CA, answered by Model below (its pull requests, and its branches
as the bare repository git pushed to holds them). git reaches that bare repository through the remote's
own rewrite to an SSH alias (`url.bbtest:.insteadOf`) and a test-owned SSH transport (GIT_SSH_COMMAND),
so no real provider, network or account is used. The credential is test_bitbucket.py's recording
helper.

Oracle: the methods, paths and bodies Bitbucket saw, the bare repository's branches, the task list and
this host's claims file reread after each process (STORE/.publications.json), the --json refusal's
`publication`, and the token's absence from every output and saved file. They prove what herdr-task
sends and keeps given Bitbucket's answers as its documentation shows them; Bitbucket's real answers, a
real credential helper, a real account and two real execution hosts are native qualification.

Runs only on CI, as the other command-line tests."""
import home_guard  # noqa: F401  (first: every test on a throwaway home, never the real one)
import copy
import json
import os
import re
import subprocess
import sys
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_native_publication as publication  # noqa: E402
import test_bitbucket as bb  # noqa: E402

TOKEN, ROOT, REPOSITORY, LOST = bb.TOKEN, bb.ROOT, bb.REPOSITORY, bb.LOST
MARK = re.compile(r"^Herdr-Operation: ([0-9a-f-]{36})$", re.M)
REVIEWER = "{11111111-2222-3333-4444-555555555555}"
KEY = "bitbucket.org/o/r:task/1"

# git's SSH command for the alias: its last word is git's own (git-receive-pack 'o/r.git'), run as
# `git receive-pack 'o/r.git'` in the folder that holds o/r.git.
SSH = '''#!/bin/sh
for last; do :; done
case "$last" in git-receive-pack*) [ -z "$FAKE_SSH_FAIL" ] || exit 255;; esac  # a push fails; reads still go
cd "$FAKE_SSH_ROOT" || exit 1
exec sh -c "git ${last#git-}"
'''


# The server's own hook before it updates any ref: FAKE_DECLINE declines the push, as a branch permission
# would; FAKE_RACE names a command (another host's whole ready) run while this push waits, so that host's
# push lands first and this one's ref update meets a branch that exists.
PRE_RECEIVE = '''#!/usr/bin/env python3
import json, os, subprocess, sys
sys.stdin.read()
if os.environ.get("FAKE_DECLINE"):
    print("branch permissions: pushes to this branch are restricted", file=sys.stderr)
    sys.exit(1)
race = os.environ.get("FAKE_RACE")
if race and os.path.exists(race):
    with open(race) as f:
        spec = json.load(f)
    os.remove(race)
    r = subprocess.run(spec["argv"], env=spec["env"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    with open(spec["out"], "w") as f:
        json.dump([r.returncode, r.stdout, r.stderr], f)
'''


class Model:
    """The test's Bitbucket repository o/r. Its branches are the bare repository's; its pull requests
    are prs. create and prepare say how a write goes: ok, lost (done, its reply lost), dropped (not
    done, its reply lost) or refused (403). touch: {path: what happens as that GET is answered}."""

    def __init__(self, f, bare):
        self.f, self.bare, self.prs, self.statuses, self.next = f, bare, {}, {}, 7
        self.create = self.prepare = "ok"
        self.listing = "ok"
        self.after_create, self.touch = None, {}

    def head(self, ref):
        r = subprocess.run(["git", "-C", self.bare, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                           capture_output=True, text=True)
        return r.stdout.strip() or None

    def open(self, number=7, base="main", description="", draft=False, source="task/1", fork=None):
        """A pull request opened on Bitbucket by someone else (by hand, another machine's, or from a fork)."""
        self.prs[number] = {"id": number, "title": "By hand", "description": description, "draft": draft, "state": "OPEN",
                            "close_source_branch": False, "reviewers": [], "source": source, "base": base, "fork": fork}
        self.next = max(self.next, number + 1)
        return self.prs[number]

    def row(self, pr):
        head = self.head(f"refs/heads/{pr['source']}") or "0" * 40
        fork = pr.get("fork") and {"full_name": pr["fork"], "links": {"html": {"href": f"https://bitbucket.org/{pr['fork']}"}}}
        return {"type": "pullrequest", "id": pr["id"], "title": pr["title"], "description": pr["description"], "state": pr["state"],
                "draft": pr["draft"], "close_source_branch": pr["close_source_branch"],
                "reviewers": [{"type": "user", "uuid": r["uuid"], "display_name": "Rev"} for r in pr["reviewers"]],
                "source": {"repository": fork or REPOSITORY, "branch": {"name": pr["source"]}, "commit": {"hash": head[:12]}},
                "destination": {"repository": REPOSITORY, "branch": {"name": pr["base"]}, "commit": {"hash": "0" * 12}},
                "links": {"html": {"href": f"https://bitbucket.org/o/r/pull-requests/{pr['id']}"}}}

    def answer(self, method, path, body):
        u = urllib.parse.urlsplit(path)
        p = u.path
        if method == "GET" and path in self.touch:
            self.touch.pop(path)(self.f)
        if method == "GET":
            if p == ROOT:
                return (200, REPOSITORY)
            if p.startswith(ROOT + "/refs/branches/"):
                name = urllib.parse.unquote(p[len(ROOT + "/refs/branches/"):])
                full = self.head(f"refs/heads/{name}")
                return (200, {"name": name, "target": {"hash": full}}) if full else (404, {"type": "error"})
            if p == ROOT + "/pullrequests":
                if self.listing == "unavailable":
                    return (503, {"type": "error"})
                m = re.fullmatch(r'source\.branch\.name="([^"]+)" AND state="OPEN"', urllib.parse.parse_qs(u.query)["q"][0])
                rows = [self.row(x) for x in self.prs.values() if x["source"] == m.group(1) and x["state"] == "OPEN"]
                return (200, {"values": rows, "size": len(rows), "page": 1, "pagelen": 50})
            m = re.fullmatch(re.escape(ROOT) + r"/pullrequests/(\d+)", p)
            if m:
                pr = self.prs.get(int(m.group(1)))
                return (200, self.row(pr)) if pr else (404, {"type": "error"})
            m = re.fullmatch(re.escape(ROOT) + r"/commit/([0-9a-f]{40})/statuses", p)
            if m:
                rows = self.statuses.get(m.group(1), [])
                return (200, {"values": rows, "size": len(rows), "page": 1, "pagelen": 100})
            m = re.fullmatch(re.escape(ROOT) + r"/commit/([0-9a-f]+)", p)
            if m:
                full = self.head(m.group(1))
                return (200, {"hash": full, "repository": REPOSITORY}) if full else (404, {"type": "error"})
            return None
        if method == "POST" and p == ROOT + "/pullrequests":
            if self.create in ("refused", "dropped"):
                return (403, {"type": "error", "error": {"message": TOKEN}}) if self.create == "refused" else LOST
            pr = {"id": self.next, "title": body["title"], "description": body["description"], "draft": body["draft"],
                  "state": "OPEN", "close_source_branch": body["close_source_branch"], "reviewers": [],
                  "source": body["source"]["branch"]["name"], "base": body["destination"]["branch"]["name"]}
            self.next += 1
            self.prs[pr["id"]] = pr
            if self.after_create:
                self.after_create(pr)
            return LOST if self.create == "lost" else (201, self.row(pr))
        m = re.fullmatch(re.escape(ROOT) + r"/pullrequests/(\d+)", p)
        if method == "PUT" and m and int(m.group(1)) in self.prs:
            if self.prepare in ("refused", "dropped"):
                return (403, {"type": "error"}) if self.prepare == "refused" else LOST
            pr = self.prs[int(m.group(1))]
            pr.update(title=body["title"], description=body["description"], draft=body["draft"],
                      close_source_branch=body["close_source_branch"], reviewers=list(body["reviewers"]),
                      base=body["destination"]["branch"]["name"])
            return LOST if self.prepare == "lost" else (200, self.row(pr))
        return None


def fixture(test):
    """A running task/1 in a folder whose remote is https://bitbucket.org/o/r.git, with Bitbucket's main
    at the folder's own, nothing of task/1 there yet, and no claim."""
    f = publication.Fixture(test, github=False)
    srv = os.path.join(f.tmp, "srv")
    f.bare_bb = os.path.join(srv, "o", "r.git")
    os.makedirs(os.path.dirname(f.bare_bb))
    f.git(f.tmp, "init", "-q", "--bare", "-b", "main", f.bare_bb)
    f.git(f.repo, "push", "-q", f.bare_bb, "main")
    # Every ref update the server committed, as git's own post-receive hook sees it (never one its ref
    # transaction refused): "<ref> <old> <new>".
    f.ref_log = os.path.join(f.tmp, "ref-updates.log")
    open(f.ref_log, "w").close()
    f.program(os.path.join(f.bare_bb, "hooks", "post-receive"),
              '#!/bin/sh\nwhile read old new ref; do\n  [ -z "$FAKE_REF_LOG" ] || echo "$ref $old $new" >> "$FAKE_REF_LOG"\ndone\n')
    f.env["FAKE_REF_LOG"] = f.ref_log
    f.program(os.path.join(f.bare_bb, "hooks", "pre-receive"), PRE_RECEIVE)
    f.git(f.repo, "remote", "add", "origin", bb.REMOTE)
    f.git(f.repo, "config", "url.bbtest:.insteadOf", "https://bitbucket.org/")
    empty = os.path.join(f.tmp, "gitconfig")
    open(empty, "w").close()
    f.credential_log = os.path.join(f.tmp, "credential.log")
    open(f.credential_log, "w").close()
    f.env.update(GIT_CONFIG_GLOBAL=empty, GIT_CONFIG_NOSYSTEM="1", FAKE_CREDENTIAL_LOG=f.credential_log,
                 FAKE_CREDENTIAL=json.dumps(f"username=x-token-auth\npassword={TOKEN}\n"),
                 GIT_SSH_COMMAND=f.program(os.path.join(f.tmp, "bin", "fake-ssh"), SSH), GIT_SSH_VARIANT="simple",
                 FAKE_SSH_ROOT=srv)
    for k in ("no_proxy", "NO_PROXY", "http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY", "SSL_CERT_DIR"):
        f.env.pop(k, None)
    f.git(f.repo, "config", "credential.helper", f.program(os.path.join(f.tmp, "bin", "credential-helper"), bb.HELPER))
    f.git(f.repo, "config", "credential.useHttpPath", "true")
    f.bb = bb.Bitbucket(test)
    f.env.update(f.bb.env)
    f.model = Model(f, f.bare_bb)
    f.bb.handler = f.model.answer
    f.claims_path = os.path.join(f.env["HERDR_TASK_STORE"], ".publications.json")
    return f


class Publishing(unittest.TestCase):
    def setUp(self):
        self.f = fixture(self)

    # ---- what each process did --------------------------------------------------------------

    def ready(self, code=0):
        f = self.f
        p = f.run("ready", "1", "--folder", f.repo, "--summary", "Sign-in works again", "--json")
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        self.quiet(p.stdout, p.stderr)
        return json.loads(p.stdout)

    def quiet(self, *outputs):
        f = self.f
        self.assertEqual(f.calls(), [])  # gh never asked
        self.assertTrue(all(c == "api.bitbucket.org:443" for c in f.bb.connects), f.bb.connects)
        for text in (f.saved(), self.claims_text(), *outputs):
            self.assertNotIn(TOKEN, text)

    def claims_text(self):
        try:
            with open(self.f.claims_path) as fh:
                return fh.read()
        except FileNotFoundError:
            return ""

    def claim(self):
        text = self.claims_text()
        return json.loads(text)["claims"].get(KEY) if text else None

    def writes(self, method):
        return [r for r in self.f.bb.seen if r["method"] == method]

    def there(self):
        return self.f.model.head("refs/heads/task/1")

    def marker(self, body):
        found = MARK.findall(body["description"])
        self.assertEqual(len(found), 1, body["description"])
        return found[0]

    # ---- publishing ------------------------------------------------------------------------

    def test_ready_pushes_opens_a_draft_and_prepares_it_keeping_what_people_set(self):
        f = self.f

        def people(pr):  # what Bitbucket's defaults and a person set on it once it opened
            pr.update(title="Fix login (renamed by a person)", close_source_branch=True, reviewers=[{"uuid": REVIEWER}])
        f.model.after_create = people
        out = self.ready()
        self.assertEqual(self.there(), f.tip)
        (post,), (put,) = self.writes("POST"), self.writes("PUT")
        self.assertEqual((post["path"], post["auth"]), (f"{ROOT}/pullrequests", f"Bearer {TOKEN}"))
        b = post["body"]
        self.assertEqual((b["draft"], b["close_source_branch"], b["source"]["branch"]["name"], b["source"]["commit"]["hash"],
                          b["destination"]["branch"]["name"]), (True, False, "task/1", f.tip, "main"))
        self.assertTrue(b["title"].endswith(" Fix login"), b["title"])
        draft_id = self.marker(b)
        self.assertEqual(put["path"], f"{ROOT}/pullrequests/7")
        b = put["body"]
        # Draft off with the summary; title, reviewers, destination and close_source_branch exactly as they were.
        self.assertEqual((b["draft"], b["title"], b["reviewers"], b["close_source_branch"], b["destination"]),
                         (False, "Fix login (renamed by a person)", [{"uuid": REVIEWER}], True,
                          {"branch": {"name": "main"}, "repository": {"full_name": "o/r"}}))
        self.assertTrue(b["description"].startswith("Sign-in works again"))
        ready_id = self.marker(b)
        t = f.task()
        self.assertEqual((t["state"], t["pr"]["provider"], t["pr"]["host"], t["pr"]["repo"], t["pr"]["number"]),
                         ("ready", "bitbucket", "bitbucket.org", "o/r", 7))
        self.assertIn("pull request #7", out["message"])
        c = self.claim()
        self.assertEqual((c["pushed"]["head"], c["draft"]["id"], c["draft"]["state"], c["ready"]["id"], c["ready"]["state"]),
                         (f.tip, draft_id, "confirmed", ready_id, "confirmed"))
        shown = f.ok("show", "1", "--folder", f.repo)["publication"]
        self.assertEqual((shown["draft"]["operation"], shown["ready"]["state"], shown["pushed"]["head"]), (draft_id, "confirmed", f.tip))

    def test_no_merge_setting_promises_a_merge_bitbucket_wont_get(self):
        for policy in ("checks", "auto"):
            with self.subTest(policy=policy):
                self.f = f = fixture(self)
                f.seed(set={"merge": policy})
                out = self.ready()
                self.assertIn("Merge pull request #7 on Bitbucket yourself", out["message"])
                self.assertNotIn("merges by itself", out["message"])
                t = f.task()
                self.assertEqual((t["state"], t.get("auto_merge"), t.get("attention")), ("ready", None, None))
                self.assertFalse(any("merge" in r["path"] for r in f.bb.seen))

    def test_a_forks_branch_of_the_same_name_is_left_out(self):
        self.f.model.open(number=3, fork="someone/r")
        self.ready()
        self.assertEqual((self.f.task()["pr"]["number"], len(self.writes("POST"))), (7, 1))

    def test_a_branch_this_host_never_pushed_is_never_pushed_over(self):
        for name, commit in (("someone's commits", lambda f: f.sibling("a reviewer's fixup")), ("even ones it holds", lambda f: f.start)):
            with self.subTest(name):
                self.f = f = fixture(self)
                other = commit(f)
                f.git(f.repo, "push", "-q", f.bare_bb, f"{other}:refs/heads/task/1")
                out = self.ready(1)
                self.assertIn("this machine never pushed it there", out["error"])
                self.assertEqual((out["publication"]["result"], self.there(), self.writes("POST")), ("refused", other, []))
                self.assertIsNone(self.claim())

    def test_this_hosts_own_last_push_is_the_only_one_it_pushes_over(self):
        f = self.f
        self.ready()
        first = f.tip
        f.git(f.wt, "commit", "-q", "--amend", "-m", "the task's work, reworded")
        f.tip = f.git(f.wt, "rev-parse", "HEAD")
        f.seed(state="running")
        self.ready()
        self.assertEqual((self.there(), len(self.writes("POST")), len(self.writes("PUT"))), (f.tip, 1, 2))
        self.assertEqual(self.claim()["pushed"]["head"], f.tip)
        self.assertIn(f"refs/heads/task/1 {first} {f.tip}", self.updates())
        # Someone else's push since: the next push refuses, its expectation no longer the branch's.
        f.git(f.repo, "push", "-q", "-f", f.bare_bb, f"{f.sibling('a fixup on Bitbucket')}:refs/heads/task/1")
        f.git(f.wt, "commit", "-q", "--allow-empty", "-m", "more")
        f.tip = f.git(f.wt, "rev-parse", "HEAD")
        f.seed(state="running")
        out = self.ready(1)
        self.assertIn("someone pushed since", out["error"])
        self.assertEqual(out["publication"]["result"], "refused")
        self.assertNotEqual(self.there(), f.tip)

    def test_a_push_git_doesnt_answer_for_keeps_its_claim_and_is_settled_from_the_branch(self):
        f = self.f
        f.env["FAKE_SSH_FAIL"] = "1"
        out = self.ready(1)
        self.assertIn("may or may not have happened", out["error"])
        self.assertEqual((out["publication"]["result"], self.writes("POST"), self.there()), ("uncertain", [], None))
        op = self.claim()["push"]["id"]
        self.assertEqual((self.claim()["push"]["state"], out["publication"]["push"]["operation"]), ("uncertain", op))
        del f.env["FAKE_SSH_FAIL"]  # the branch is still absent: it didn't land, and a create-if-absent may go again
        self.ready()
        self.assertEqual((self.there(), f.task()["state"], self.claim()["push"]), (f.tip, "ready", None))

    # ---- two execution hosts ---------------------------------------------------------------

    def second_host(self):
        """Another execution host with the same task: its own clone of the folder (the same commits), its
        own task list and claims file and its own machine name, on the same Bitbucket and SSH transport."""
        a = self.f
        b = copy.copy(a)
        root = os.path.join(a.tmp, "host-b")
        os.makedirs(root)
        b.repo, b.wt = os.path.join(root, "repo"), os.path.join(root, "wt")
        b.env = {**a.env, "HERDR_TASK_STORE": os.path.join(root, "tasks"), "HERDR_TASK_SETTINGS": os.path.join(root, "shepherdr.json")}
        b.claims_path = os.path.join(root, "tasks", ".publications.json")
        with open(b.env["HERDR_TASK_SETTINGS"], "w") as fh:
            json.dump({"here": "host-b"}, fh)
        b.git(root, "clone", "-q", a.repo, b.repo)
        for k, v in (("remote.origin.url", bb.REMOTE), ("url.bbtest:.insteadOf", "https://bitbucket.org/"),
                     ("credential.helper", os.path.join(a.tmp, "bin", "credential-helper")), ("credential.useHttpPath", "true"),
                     ("user.name", "T"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
            b.git(b.repo, "config", k, v)
        b.git(b.repo, "worktree", "add", "-q", "-b", "task/1", b.wt, a.tip)
        b.ok("add", "Fix login", "--folder", b.repo, "--space", "sp1")
        b.store = b.ok("where", "--folder", b.repo)["store"]
        b.seed(state="running", started=1, mode="worktree", worktree=b.wt, branch="task/1", start=a.start, base="main")
        return b

    def as_host(self, host, code):
        mine, self.f = self.f, host
        try:
            return self.ready(code)
        finally:
            self.f = mine

    def updates(self):
        with open(self.f.ref_log) as fh:
            return fh.read().splitlines()

    def test_two_hosts_publishing_the_same_task_create_its_branch_and_pull_request_once(self):
        cases = {
            "the second reads after the first": (False, False, "this machine never pushed it there"),
            # Both find no branch; the second's push waits in the server while the first's whole ready runs, so
            # the server's own ref update (expecting none) is what refuses it.
            "both find no branch, the same commit": (True, False, "refused to create task/1"),
            "both find no branch, another commit": (True, True, "refused to create task/1"),
        }
        for name, (racing, own_commit, words) in cases.items():
            with self.subTest(name):
                self.f = a = fixture(self)
                b = self.second_host()
                if own_commit:
                    b.tip = b.commit(b.wt, "host b's own")
                if racing:
                    spec, said = os.path.join(a.tmp, "race.json"), os.path.join(a.tmp, "race.out")
                    with open(spec, "w") as fh:
                        json.dump({"argv": [sys.executable, os.path.join(publication.BIN, "herdr-task"), "ready", "1", "--folder",
                                            a.repo, "--summary", "Sign-in works again", "--json"], "env": a.env, "out": said}, fh)
                    b.env = {**b.env, "FAKE_RACE": spec}
                    out = self.as_host(b, 1)
                    with open(said) as fh:
                        code, stdout, stderr = json.load(fh)
                    self.assertEqual(code, 0, stdout + stderr)  # host A, meanwhile, published
                    self.quiet(stdout, stderr)
                else:
                    self.ready()  # host A publishes first
                    out = self.as_host(b, 1)
                self.assertIn(words, out["error"])
                self.assertEqual((out["publication"]["result"], out["publication"]["changed"]), ("refused", []))
                created = [u for u in self.updates() if u.startswith("refs/heads/task/1 " + "0" * 40)]
                self.assertEqual((len(created), len(self.writes("POST")), self.there()), (1, 1, a.tip))
                self.assertEqual((b.task()["state"], b.task().get("pr"), a.task()["state"], a.task()["pr"]["number"]),
                                 ("running", None, "ready", 7))
                with open(b.claims_path) as fh:
                    self.assertEqual(json.load(fh)["claims"], {})  # the loser holds nothing

    def test_a_push_the_server_declines_is_refused_as_that(self):
        f = self.f
        f.env["FAKE_DECLINE"] = "1"
        out = self.ready(1)
        self.assertIn("declined the push of task/1", out["error"])
        self.assertEqual((out["publication"]["result"], self.there(), self.writes("POST"), self.claim()), ("refused", None, [], None))

    def test_merge_stays_refused_once_published(self):
        f = self.f
        self.ready()
        before = len(f.bb.seen)
        for verb in ("accept", "merge"):
            p = f.run(verb, "1", "--folder", f.repo, "--json")
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertIn("sent no merge there and doesn't merge it any other way", json.loads(p.stdout)["error"])
        self.assertEqual({r["method"] for r in f.bb.seen[before:]}, {"GET"})
        self.assertEqual((f.task()["state"], f.rev("main"), f.hc("send")), ("ready", f.start, []))

    def test_a_bitbucket_folder_never_merges_here_or_by_an_agent(self):
        f = self.f
        f.seed(state="ready", ready_at=1)
        for verb in ("accept", "merge"):
            error = f.refused(verb, "1", "--folder", f.repo)
            self.assertIn("is on Bitbucket (o/r), where herdr-task merges nothing", error)
        self.assertEqual((f.rev("main"), f.hc("send", "run"), f.task()["state"], f.bb.connects), (f.start, [], "ready", []))

    # ---- uncertain writes ------------------------------------------------------------------

    def test_a_lost_reply_found_at_once_is_kept_under_its_own_id(self):
        f = self.f
        f.model.create = "lost"
        self.ready()
        (post,) = self.writes("POST")
        c = self.claim()
        self.assertEqual((c["draft"]["id"], c["draft"]["state"], c["draft"]["pr"]["number"]), (self.marker(post["body"]), "confirmed", 7))
        self.assertEqual(f.task()["pr"]["number"], 7)

    def test_a_lost_reply_is_reopened_without_sending_again_and_reconciled_under_the_same_id(self):
        f = self.f
        f.model.create = "lost"

        def unseen(f):
            f.model.listing = "unavailable"
        f.model.after_create = lambda pr: unseen(f)  # the one look after the write then fails
        out = self.ready(1)
        p = out["publication"]
        self.assertEqual((p["result"], p["changed"], p["draft"]["state"]), ("uncertain", ["pushed"], "uncertain"))
        op = p["draft"]["operation"]
        self.assertIn(op, out["error"])
        self.assertIn("never sends it again", out["error"])
        self.assertEqual((f.task()["state"], f.task().get("pr"), self.claim()["draft"]["id"]), ("running", None, op))
        # The next ready, Bitbucket answering again: nothing is sent twice, the same id is confirmed.
        f.model.listing = "ok"
        self.ready()
        self.assertEqual(len(self.writes("POST")), 1)
        c = self.claim()
        self.assertEqual((c["draft"]["id"], c["draft"]["state"], c["draft"]["pr"]["number"]), (op, "confirmed", 7))
        self.assertEqual((f.task()["state"], f.task()["pr"]["number"]), ("ready", 7))

    def test_an_empty_lookup_never_releases_or_resends_it(self):
        f = self.f
        f.model.create = "dropped"  # never made, but its reply is lost: nothing can tell that from a slow one
        p = self.ready(1)["publication"]
        self.assertEqual(p["result"], "uncertain")
        op = p["draft"]["operation"]
        for _ in range(2):
            out = self.ready(1)
            self.assertEqual((out["publication"]["result"], out["publication"]["changed"]), ("held", []))
            self.assertIn(f"Herdr-Operation: {op}", out["error"])
        self.assertEqual((len(self.writes("POST")), self.writes("PUT"), self.claim()["draft"]["state"]), (1, [], "uncertain"))
        # The person opens it on Bitbucket the way the refusal says: then it is recorded under that same id.
        f.model.open(number=12, description=f"Opened by hand\n\nHerdr-Operation: {op}")
        self.ready()
        c = self.claim()
        self.assertEqual((c["draft"]["id"], c["draft"]["pr"]["number"], len(self.writes("POST"))), (op, 12, 1))

    def test_an_uncertain_preparation_holds_until_bitbucket_shows_it(self):
        f = self.f
        f.model.prepare = "lost"
        out = self.ready(1)
        p = out["publication"]
        self.assertEqual((p["result"], p["changed"], p["draft"]["state"], p["ready"]["state"]),
                         ("uncertain", ["pushed", "draft"], "confirmed", "uncertain"))
        op = p["ready"]["operation"]
        self.assertEqual((f.task()["state"], f.task().get("pr")), ("running", None))
        f.model.prepare = "ok"
        self.ready()
        (first, second) = self.writes("PUT")  # the one lost, then this ready's own
        self.assertEqual(self.marker(first["body"]), op)
        self.assertEqual((len(self.writes("POST")), f.task()["state"], f.task()["pr"]["number"]), (1, "ready", 7))

    def test_a_refused_write_keeps_the_push_and_says_so(self):
        f = self.f
        f.model.create = "refused"
        out = self.ready(1)
        p = out["publication"]
        self.assertEqual((p["result"], p["changed"], p["pushed"]["head"], p["draft"]), ("changed", ["pushed"], f.tip, None))
        self.assertIn("Bitbucket refused this machine's token for this change", out["error"])
        self.assertEqual((self.there(), f.task()["state"], f.task().get("pr")), (f.tip, "running", None))
        self.assertEqual(f.ok("show", "1", "--folder", f.repo)["publication"]["pushed"]["head"], f.tip)
        f.model.create = "ok"  # repaired: the push isn't repeated, the draft opens
        self.ready()
        self.assertEqual((len(self.writes("POST")), f.task()["state"]), (2, "ready"))

    # ---- nothing sent ----------------------------------------------------------------------

    def nothing_sent(self, out, words):
        self.assertIn(words, out["error"])
        self.assertEqual((out["publication"]["result"], out["publication"]["changed"]), ("refused", []))
        self.assertEqual((self.there(), self.writes("POST"), self.writes("PUT")), (None, [], []))
        self.assertEqual((self.f.task()["state"], self.f.task().get("pr")), ("running", None))

    def test_preflight_refuses_before_any_effect(self):
        cases = {
            "no base on Bitbucket": (lambda f: f.model.touch.update({f"{ROOT}/refs/branches/main": lambda f: subprocess.run(
                ["git", "-C", f.bare_bb, "update-ref", "-d", "refs/heads/main"], check=True)}), "isn't a branch on Bitbucket"),
            "a pull request into another base": (lambda f: f.model.open(base="release"), "into release, not main"),
            "another publication's pull request": (lambda f: f.model.open(
                description="x\n\nHerdr-Operation: 99999999-8888-4777-8666-555555555555"), "opened by another herdr-task publication"),
            "two open from the branch": (lambda f: (f.model.open(7), f.model.open(8)), "2 pull requests are open from task/1"),
            "no token": (lambda f: f.env.update(FAKE_CREDENTIAL="null"), "gave no Bitbucket token"),
        }
        for name, (change, words) in cases.items():
            with self.subTest(name):
                self.f = fixture(self)
                change(self.f)
                self.nothing_sent(self.ready(1), words)
                self.assertIsNone(self.claim())  # a claim taken for nothing is let go

    def test_a_remote_changed_before_the_push_or_the_write_stops_it(self):
        pushurl = lambda f: f.git(f.repo, "config", "remote.origin.pushurl", bb.REMOTE)
        listing = f"{ROOT}/pullrequests?q=" + urllib.parse.quote('source.branch.name="task/1" AND state="OPEN"', safe="") + "&pagelen=50"
        self.f.model.touch[listing] = pushurl  # as the last read before the push is answered
        self.nothing_sent(self.ready(1), "reads otherwise than when it was bound")

        self.f = f = fixture(self)
        answer = f.model.answer

        def after_the_push(method, path, body):  # as the branch is read again, just before the draft is opened
            if method == "GET" and path == f"{ROOT}/refs/branches/task%2F1" and self.there() == f.tip:
                pushurl(f)
            return answer(method, path, body)
        f.bb.handler = after_the_push
        out = self.ready(1)
        self.assertIn("reads otherwise than when it was bound", out["error"])
        self.assertEqual((out["publication"]["result"], out["publication"]["changed"], self.writes("POST")), ("changed", ["pushed"], []))
        self.assertEqual((self.there(), self.claim()["pushed"]["head"], self.claim()["draft"]), (f.tip, f.tip, None))

    def test_a_push_url_git_would_rewrite_again_is_no_frozen_route(self):
        f = self.f  # git rewrites once for its views (bbtest:o/r.git), and again for a push to that URL as written
        f.git(f.repo, "config", "url.elsewhere:.insteadOf", "bbtest:")
        out = self.ready(1)
        self.assertIn("can't be held to one route", out["error"])
        self.assertEqual((out["publication"]["result"], self.there(), f.bb.connects), ("refused", None, []))

    # ---- one owner -------------------------------------------------------------------------

    def test_a_branch_claimed_by_another_task_or_machine_is_refused_before_anything_is_sent(self):
        f = self.f
        for owner in ({"task": "elsewhere#3", "folder": "/other/clone", "worktree": "/other/wt", "machine": "laptop"},
                      {"task": f.ok("where", "--folder", f.repo)["slug"] + "#1", "folder": f.repo, "worktree": f.wt, "machine": "laptop"}):
            with self.subTest(owner=owner):
                claim = {"repo": "o/r", "branch": "task/1", "base": "main", "owner": owner, "route": {}, "pushed": None,
                         "draft": {"id": "99999999-8888-4777-8666-555555555555", "state": "confirmed", "head": f.tip,
                                   "pr": {"number": 3, "url": "https://bitbucket.org/o/r/pull-requests/3"}}, "ready": None}
                os.makedirs(os.path.dirname(f.claims_path), exist_ok=True)
                with open(f.claims_path, "w") as fh:
                    json.dump({"version": 1, "claims": {KEY: claim}}, fh)
                out = self.ready(1)
                self.assertIn("is claimed for publication by", out["error"])
                self.assertIn("on laptop", out["error"])
                self.assertEqual((out["publication"]["result"], f.bb.connects, bb.asked(f), self.there()), ("refused", [], [], None))
                self.assertEqual(self.claim()["owner"], owner)  # never taken over

    def test_a_claims_file_that_doesnt_read_refuses_and_is_kept(self):
        f = self.f
        os.makedirs(os.path.dirname(f.claims_path), exist_ok=True)
        with open(f.claims_path, "w") as fh:
            fh.write("{not json")
        error = f.refused("ready", "1", "--folder", f.repo, "--summary", "x")
        self.assertIn("isn't valid JSON", error)
        self.assertEqual((self.claims_text(), f.bb.connects, self.there()), ("{not json", [], None))


Publishing = publication.ON_CI(Publishing)

if __name__ == "__main__":
    unittest.main()
