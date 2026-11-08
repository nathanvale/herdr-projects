"""Bitbucket reads (B1) across herdr-task's own command line: `show --evidence` (what the Accept card
shows), `tick`, `accept`, `merge` and `ready` as their own processes, on test_native_publication.py's
Fixture with its remote on bitbucket.org and a saved, provider-qualified Bitbucket pull request.

Bitbucket here is test-owned: the child's HTTPS goes through a local CONNECT proxy (https_proxy),
which opens only api.bitbucket.org:443 and answers it as Bitbucket's REST API with a certificate from
a throwaway CA (SSL_CERT_FILE), so no real provider request can be made and herdr-task's transport
is the one it ships (no test seam). The execution host's credential is a recording Git credential
helper in the repository's own config, with the global and system configs emptied.

Oracle: the routes, methods and Authorization the proxy saw (and every host anything asked it for),
what the helper was asked, the task list reread after each process, the worktree and branch, and the
token's absence from every output and saved file. They prove what herdr-task does with Bitbucket's
answers as its documentation shows them; Bitbucket's own answers, a real credential helper and a
real account are native qualification, not this.

Runs only on CI, as the other command-line tests."""
import atexit
import http.server
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_native_publication as publication  # noqa: E402

TOKEN = "bbtoken-Secret_123"
REMOTE = "https://bitbucket.org/o/r.git"
ROOT = "/2.0/repositories/o/r"
RECORD = {"provider": "bitbucket", "host": "bitbucket.org", "repo": "o/r", "number": 7,
          "url": "https://bitbucket.org/o/r/pull-requests/7"}
REPOSITORY = {"full_name": "o/r", "links": {"html": {"href": "https://bitbucket.org/o/r"}}}

# The execution host's credential helper: asked as git asks any helper (`<helper> get`, the request
# on stdin), it logs the request and answers as FAKE_CREDENTIAL says, or not at all.
HELPER = '''#!/usr/bin/env python3
import json, os, sys
ask = sys.stdin.read()
with open(os.environ["FAKE_CREDENTIAL_LOG"], "a") as f:
    f.write(json.dumps([sys.argv[1:], ask]) + "\\n")
answer = json.loads(os.environ.get("FAKE_CREDENTIAL") or "null")
if sys.argv[1:] == ["get"] and answer is not None:
    sys.stdout.write(answer)
'''


CERTS = []


def cert():
    """A throwaway CA and api.bitbucket.org's certificate from it, made once per run: (ca.pem, leaf.pem,
    leaf.key) in a folder removed when the run ends."""
    if CERTS:
        return CERTS[0]
    folder = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, folder, True)
    p = lambda name: os.path.join(folder, name)
    with open(p("ca.cnf"), "w") as f:
        f.write("[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n[dn]\nCN=herdr-task test CA\n"
                "[v3]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n")
    with open(p("leaf.cnf"), "w") as f:
        f.write("[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=api.bitbucket.org\n")
    with open(p("leaf.ext"), "w") as f:
        f.write("subjectAltName=DNS:api.bitbucket.org\nbasicConstraints=critical,CA:FALSE\n"
                "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n"
                "authorityKeyIdentifier=keyid\nsubjectKeyIdentifier=hash\n")
    for argv in (["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", p("ca.key"), "-out", p("ca.pem"), "-days", "2",
                  "-config", p("ca.cnf")],
                 ["req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", p("leaf.key"), "-out", p("leaf.csr"),
                  "-config", p("leaf.cnf")],
                 ["x509", "-req", "-in", p("leaf.csr"), "-CA", p("ca.pem"), "-CAkey", p("ca.key"), "-set_serial", "1",
                  "-out", p("leaf.pem"), "-days", "2", "-extfile", p("leaf.ext")]):
        subprocess.run(["openssl", *argv], check=True, capture_output=True)
    CERTS.append((p("ca.pem"), p("leaf.pem"), p("leaf.key")))
    return CERTS[0]


class Api(http.server.BaseHTTPRequestHandler):
    """Bitbucket's REST API inside the tunnel: routes answer GET; anything else is recorded and refused."""

    def log_message(self, *args):
        pass

    def answer(self):
        fake = self.server.fake
        fake.seen.append({"method": self.command, "path": self.path, "auth": self.headers.get("Authorization")})
        routes = fake.routes.get(self.path) if self.command == "GET" else None
        if isinstance(routes, list):
            route = routes.pop(0) if len(routes) > 1 else routes[0]  # answers in turn, the last one again
        else:
            route = routes or (404, {"type": "error", "error": {"message": f"Not found {TOKEN}"}})
        status, body = route[0], route[1]
        data = json.dumps(body).encode()
        self.send_response(status)
        for k, v in (route[2] if len(route) > 2 else {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = answer


class Proxy(http.server.BaseHTTPRequestHandler):
    """The only way out of the child: CONNECT to api.bitbucket.org:443 alone, into Api over TLS."""

    def log_message(self, *args):
        pass

    def do_CONNECT(self):
        fake = self.server.fake
        fake.connects.append(self.path)
        if self.path != "api.bitbucket.org:443":
            self.send_error(403)
            return
        self.send_response(200, "Connection established")
        self.end_headers()
        self.close_connection = True
        try:
            tls = fake.context.wrap_socket(self.connection, server_side=True)
        except (OSError, ssl.SSLError):
            return
        try:
            Api(tls, self.client_address, self.server)
        finally:
            tls.close()

    def refuse(self):
        self.server.fake.connects.append(f"{self.command} {self.path}")
        self.send_error(403)

    do_GET = do_POST = do_PUT = do_DELETE = refuse


class Bitbucket:
    """The test's Bitbucket: routes {path: (status, body[, headers]) or [answers in turn]}; seen: what
    Api answered; connects: every target anything asked the proxy for."""

    def __init__(self, test):
        ca, leaf, key = cert()
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(leaf, key)
        self.routes, self.seen, self.connects = {}, [], []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        self.server.daemon_threads = True
        self.server.fake = self
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)
        proxy = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.env = {"https_proxy": proxy, "HTTPS_PROXY": proxy, "SSL_CERT_FILE": ca}

    def paths(self):
        return [r["path"] for r in self.seen]

    def pull_request(self, head, state="OPEN", title="Fix login", source="task/1", base="main", number=7, repo=None):
        repo = repo or REPOSITORY
        return {"id": number, "title": title, "state": state, "draft": False,
                "source": {"repository": repo, "branch": {"name": source}, "commit": {"hash": head[:12]}},
                "destination": {"repository": repo, "branch": {"name": base}, "commit": {"hash": "0" * 12}},
                "links": {"html": {"href": f"https://bitbucket.org/o/r/pull-requests/{number}"}}}

    def statuses_path(self, head, page=None):
        return f"{ROOT}/commit/{head}/statuses?pagelen=100" + (f"&page={page}" if page else "")

    def status(self, key, state, name=None):
        return {"type": "build", "key": key, "state": state, "name": name or key, "url": f"https://ci.example/{key}"}

    def answers(self, head, statuses=(), pr=None, pages=None):
        """Bitbucket answering for pull request #7 at `head`, its statuses on one page (or `pages`)."""
        self.routes.update({
            ROOT: (200, REPOSITORY),
            f"{ROOT}/pullrequests/7": (200, pr or self.pull_request(head)),
            f"{ROOT}/commit/{head[:12]}": (200, {"hash": head, "repository": REPOSITORY}),
            self.statuses_path(head): (200, {"values": list(statuses), "size": len(statuses), "page": 1, "pagelen": 100}),
        })
        for path, body in (pages or {}).items():
            self.routes[path] = (200, body)


def fixture(test, helper=True, remote=REMOTE):
    """A task in a folder whose remote is on bitbucket.org, Ready with its Bitbucket pull request saved,
    and Bitbucket answering as the test says (bb). The helper answers with TOKEN unless told otherwise."""
    f = publication.Fixture(test, github=False)
    f.git(f.repo, "remote", "add", "origin", remote)
    empty = os.path.join(f.tmp, "gitconfig")
    open(empty, "w").close()
    f.credential_log = os.path.join(f.tmp, "credential.log")
    open(f.credential_log, "w").close()
    f.env.update(GIT_CONFIG_GLOBAL=empty, GIT_CONFIG_NOSYSTEM="1", FAKE_CREDENTIAL_LOG=f.credential_log,
                 FAKE_CREDENTIAL=json.dumps(f"username=x-token-auth\npassword={TOKEN}\n"))
    for k in ("no_proxy", "NO_PROXY", "http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY", "SSL_CERT_DIR"):
        f.env.pop(k, None)
    if helper:
        f.git(f.repo, "config", "credential.helper", f.program(os.path.join(f.tmp, "bin", "credential-helper"), HELPER))
        f.git(f.repo, "config", "credential.useHttpPath", "true")
    f.bb = Bitbucket(test)
    f.env.update(f.bb.env)
    f.seed(state="ready", ready_at=1, pr=dict(RECORD))
    return f


def asked(f):
    """What the credential helper was asked: [(argv, request)]."""
    with open(f.credential_log) as fh:
        return [tuple(json.loads(line)) for line in fh]


class Quiet:
    """Assertions every Bitbucket test ends on: gh never asked, only Bitbucket's API host reached, and
    the token nowhere in anything herdr-task printed or saved."""

    def quiet(self, f, *outputs):
        self.assertEqual(f.calls(), [])
        self.assertTrue(all(c == "api.bitbucket.org:443" for c in f.bb.connects), f.bb.connects)
        for text in (f.saved(), *[json.dumps(o) if not isinstance(o, str) else o for o in outputs]):
            self.assertNotIn(TOKEN, text)

    def run_show(self, f):
        p = f.run("show", "1", "--folder", f.repo, "--evidence", "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.quiet(f, p.stdout, p.stderr)
        return json.loads(p.stdout)["evidence"]["checks"]


@publication.ON_CI
class ExactHeadChecks(unittest.TestCase, Quiet):
    def test_every_page_of_its_heads_statuses_is_read_on_the_hosts_token(self):
        f = fixture(self)
        page2 = f.bb.statuses_path(f.tip, 2)
        f.bb.answers(f.tip, pages={page2: {"values": [f.bb.status("deploy", "SUCCESSFUL")], "size": 3, "page": 2}})
        f.bb.routes[f.bb.statuses_path(f.tip)] = (200, {
            "values": [f.bb.status("build", "SUCCESSFUL"), f.bb.status("lint", "SUCCESSFUL")], "size": 3, "page": 1,
            "next": "https://api.bitbucket.org" + page2})
        checks = self.run_show(f)
        self.assertEqual(checks, {"state": "passed", "result": "passed", "head": f.tip, "text": f"All 3 passed on {f.tip[:7]}"})
        # Its head as Bitbucket abbreviates it, resolved to the full commit, whose statuses are read
        # page by page, then the pull request again: its head hadn't moved.
        self.assertEqual(f.bb.paths(), [ROOT, f"{ROOT}/pullrequests/7", f"{ROOT}/commit/{f.tip[:12]}",
                                        f.bb.statuses_path(f.tip), page2, f"{ROOT}/pullrequests/7"])
        self.assertEqual({(r["method"], r["auth"]) for r in f.bb.seen}, {("GET", f"Bearer {TOKEN}")})
        (argv, request), = asked(f)
        self.assertEqual(argv, ["get"])
        lines = request.splitlines()
        self.assertIn("protocol=https", lines)
        self.assertIn("host=bitbucket.org", lines)
        self.assertIn("path=o/r.git", lines)
        self.assertFalse(any(x.startswith("username=") for x in lines))  # no account herdr-task chose

    def test_an_ssh_remote_reads_on_the_same_https_lookup(self):
        f = fixture(self, remote="git@bitbucket.org:o/r.git")
        f.bb.answers(f.tip, [f.bb.status("a", "SUCCESSFUL")])
        self.assertEqual(self.run_show(f)["result"], "passed")
        (argv, request), = asked(f)
        lines = request.splitlines()
        self.assertIn("path=o/r.git", lines)
        self.assertFalse(any(x.startswith("username=") for x in lines))  # ssh's transport user "git" is no account

    def outcome(self, statuses=(), **over):
        f = fixture(self)
        f.bb.answers(f.tip, statuses, **over)
        return f, self.run_show(f)

    def test_empty_pending_failed_and_passed_stay_apart(self):
        s = Bitbucket.status
        for statuses, state, result, text in (
                ((), "none", "empty", "None reported on {} yet"),
                ((("a", "SUCCESSFUL"), ("b", "INPROGRESS")), "running", "pending", "1 of 2 still running on {}"),
                ((("a", "SUCCESSFUL"), ("b", "STOPPED")), "failed", "failed", "1 failing on {}: b"),
                ((("a", "SUCCESSFUL"), ("b", "FAILED")), "failed", "failed", "1 failing on {}: b"),
                ((("a", "SUCCESSFUL"),), "passed", "passed", "All 1 passed on {}")):
            with self.subTest(result=result, statuses=statuses):
                f, checks = self.outcome([s(None, k, st) for k, st in statuses])
                self.assertEqual(checks, {"state": state, "result": result, "head": f.tip, "text": text.format(f.tip[:7])})

    def test_a_read_that_isnt_whole_counts_for_nothing(self):
        def page(f, **over):
            return {f.bb.statuses_path(f.tip): (200, {"values": [f.bb.status("a", "SUCCESSFUL")], **over})}
        cases = {
            "fewer rows than it says": lambda f: page(f, size=2),
            "a next page on another host": lambda f: page(f, next="https://bitbucket.example/2.0/repositories/o/r/commit/"
                                                                  f"{f.tip}/statuses?pagelen=100&page=2"),
            "a next page in another collection": lambda f: page(f, next=f"https://api.bitbucket.org{ROOT}/pullrequests?page=2"),
            "the same page again": lambda f: page(f, next="https://api.bitbucket.org" + f.bb.statuses_path(f.tip)),
            "a redirect": lambda f: {f.bb.statuses_path(f.tip): (302, {}, {"Location": "https://api.bitbucket.org" + ROOT})},
        }
        for name, change in cases.items():
            with self.subTest(name):
                f = fixture(self)
                f.bb.answers(f.tip)
                f.bb.routes.update(change(f))
                checks = self.run_show(f)
                self.assertEqual((checks["state"], checks["result"]), ("unknown", "incomplete-read"))
                self.assertNotIn("head", checks)

    def test_a_link_that_isnt_a_url_never_stops_a_command(self):
        f = fixture(self)  # a status's own link is its poster's: left off, and the read still whole
        f.bb.answers(f.tip, [{**f.bb.status("a", "SUCCESSFUL"), "url": "https://a]b/"}])
        self.assertEqual(self.run_show(f)["result"], "passed")
        p = f.run("tick", "--folder", f.repo, "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        f = fixture(self)  # a next page that isn't a URL: incomplete
        f.bb.answers(f.tip)
        f.bb.routes[f.bb.statuses_path(f.tip)] = (200, {"values": [], "next": "https://a]b/x"})
        self.assertEqual(self.run_show(f)["result"], "incomplete-read")
        p = f.run("tick", "--folder", f.repo, "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_missing_moved_and_another_head_are_not_checks(self):
        f, checks = self.outcome()
        f.bb.routes[f"{ROOT}/pullrequests/7"] = (404, {"type": "error"})
        checks = self.run_show(f)
        self.assertEqual((checks["state"], checks["result"]), ("unknown", "missing"))

        f = fixture(self)
        f.bb.answers(f.tip, [f.bb.status("a", "SUCCESSFUL")])
        moved = f.bb.pull_request(f.start)  # pushed to while its statuses were read
        f.bb.routes[f"{ROOT}/pullrequests/7"] = [(200, f.bb.pull_request(f.tip)), (200, moved)]
        checks = self.run_show(f)
        self.assertEqual((checks["state"], checks["result"]), ("unknown", "identity-changed"))

        f = fixture(self)  # Bitbucket's head is another commit than this branch's tip: not the candidate's checks
        f.bb.answers(f.start, [f.bb.status("a", "SUCCESSFUL")])
        checks = self.run_show(f)
        self.assertEqual((checks["state"], checks["result"], checks["head"]), ("unknown", "other-head", f.start))

    def test_another_source_or_destination_is_not_this_tasks(self):
        for over in ({"base": "release"}, {"source": "task/2"}):
            with self.subTest(**over):
                f = fixture(self)
                f.bb.answers(f.tip, [f.bb.status("a", "SUCCESSFUL")], pr=f.bb.pull_request(f.tip, state="MERGED", **over))
                checks = self.run_show(f)
                self.assertEqual((checks["state"], checks["result"]), ("unknown", "refused"))
                self.assertIn("isn't read as this task's", checks["text"])
                p = f.run("tick", "--folder", f.repo, "--json")  # merged, but not as this task: nothing finishes
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.quiet(f, p.stdout, p.stderr)
                self.assertEqual((f.task()["state"], json.loads(p.stdout)["done"]), ("ready", []))
                self.assertTrue(os.path.isdir(f.wt))

    def test_a_fork_or_another_repositorys_answer_is_not_this_pull_request(self):
        other = {"full_name": "someone/r", "links": {"html": {"href": "https://bitbucket.org/someone/r"}}}
        f = fixture(self)
        f.bb.answers(f.tip)
        pr = f.bb.pull_request(f.tip)
        pr["source"]["repository"] = other
        f.bb.routes[f"{ROOT}/pullrequests/7"] = (200, pr)
        self.assertEqual(self.run_show(f)["result"], "identity-changed")


@publication.ON_CI
class HostCredentials(unittest.TestCase, Quiet):
    def test_no_usable_answer_from_the_helper_sends_nothing(self):
        cases = {"no helper": None, "no password": "username=x-token-auth\n",
                 "a password that isn't a token": "username=x\npassword=two words\n",
                 "a negotiated credential": f"authtype=Bearer\ncredential={TOKEN}\n"}
        for name, answer in cases.items():
            with self.subTest(name):
                f = fixture(self, helper=name != "no helper")
                f.env["FAKE_CREDENTIAL"] = json.dumps(answer)
                f.bb.answers(f.tip, [f.bb.status("a", "SUCCESSFUL")])
                checks = self.run_show(f)
                self.assertEqual((checks["state"], checks["result"]), ("unknown", "missing-credentials"))
                self.assertEqual((f.bb.connects, f.bb.seen), ([], []))  # nothing left this machine

    def test_a_refused_token_is_never_retried_another_way(self):
        f = fixture(self)
        f.bb.answers(f.tip)
        f.bb.routes[ROOT] = (401, {"type": "error", "error": {"message": f"Bad token {TOKEN}"}})
        checks = self.run_show(f)
        self.assertEqual((checks["state"], checks["result"]), ("unknown", "permission-refused"))
        self.assertEqual([(r["path"], r["auth"]) for r in f.bb.seen], [(ROOT, f"Bearer {TOKEN}")])  # once, no Basic

    def test_the_token_never_shows(self):
        f = fixture(self)
        f.bb.answers(f.tip, [f.bb.status("lint", "FAILED", name=f"lint {TOKEN}")],
                     pr=f.bb.pull_request(f.tip, title=f"Fix login {TOKEN}"))
        checks = self.run_show(f)
        self.assertEqual(checks["text"], f"1 failing on {f.tip[:7]}: lint [redacted]")
        p = f.run("tick", "--folder", f.repo, "--json")
        self.quiet(f, p.stdout, p.stderr)
        self.assertEqual(f.task()["attention"], "Checks failing: lint [redacted].")

    def test_a_remote_that_doesnt_bind_the_saved_repository_reaches_nobody(self):
        cases = {"another repository": lambda f: f.seed(pr={**RECORD, "repo": "o/other", "url": "https://bitbucket.org/o/other/pull-requests/7"}),
                 "a push URL elsewhere": lambda f: f.git(f.repo, "remote", "set-url", "--push", "origin", "https://bitbucket.org/o/fork.git"),
                 "an SSH push URL on another host": lambda f: f.git(f.repo, "remote", "set-url", "--push", "origin", "git@github.com:o/r.git"),
                 "a second URL on another host": lambda f: f.git(f.repo, "config", "--add", "remote.origin.url", "git@example.com:o/r.git"),
                 "a fetch URL rewritten elsewhere": lambda f: f.git(f.repo, "config", "url.https://example.com/.insteadOf", "https://bitbucket.org/")}
        for name, change in cases.items():
            with self.subTest(name):
                f = fixture(self)
                f.bb.answers(f.tip, [f.bb.status("a", "SUCCESSFUL")])
                change(f)
                checks = self.run_show(f)
                self.assertEqual((checks["state"], checks["result"]), ("unknown", "refused"))
                self.assertIn("nothing was sent", checks["text"])
                self.assertEqual((f.bb.connects, asked(f)), ([], []))


@publication.ON_CI
class NothingMergesOrPublishes(unittest.TestCase, Quiet):
    def passed(self):
        f = fixture(self)
        f.bb.answers(f.tip, [f.bb.status("a", "SUCCESSFUL")])
        return f

    def test_accept_and_merge_send_no_merge_and_merge_no_other_way(self):
        for verb in ("accept", "merge"):
            with self.subTest(verb):
                f = self.passed()
                p = f.run(verb, "1", "--folder", f.repo, "--json")
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                error = json.loads(p.stdout)["error"]
                self.assertIn("sent no merge there and doesn't merge it any other way", error)
                self.assertNotIn("cause", json.loads(p.stdout))
                self.quiet(f, p.stdout, p.stderr)
                self.assertEqual({r["method"] for r in f.bb.seen}, {"GET"})
                self.assertFalse(any("merge" in r["path"] for r in f.bb.seen))
                t = f.task()
                self.assertEqual((t["state"], t["attention"], t["pr"]["number"], t.get("accepted_at")), ("ready", error, 7, None))
                self.assertEqual((f.rev("main"), f.rev("task/1")), (f.start, f.tip))  # nothing merged here either
                self.assertTrue(os.path.isdir(f.wt))

    def test_accept_with_checks_running_waits_for_nothing_that_would_merge(self):
        f = fixture(self)
        f.bb.answers(f.tip, [f.bb.status("a", "INPROGRESS")])
        p = f.run("accept", "1", "--folder", f.repo, "--json")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("sent no merge there", json.loads(p.stdout)["error"])
        self.quiet(f, p.stdout, p.stderr)
        t = f.task()
        self.assertEqual((t["state"], t.get("auto_merge"), t.get("accepted_at")), ("ready", None, None))

    def test_the_ticks_auto_merge_sends_no_merge(self):
        f = self.passed()
        f.seed(auto_merge="checks")
        p = f.run("tick", "--folder", f.repo, "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.quiet(f, p.stdout, p.stderr)
        t = f.task()
        self.assertEqual((t["state"], json.loads(p.stdout)["done"]), ("ready", []))
        self.assertIn("sent no merge there", t["attention"])
        self.assertEqual({r["method"] for r in f.bb.seen}, {"GET"})
        self.assertEqual((f.rev("main"), f.rev("task/1")), (f.start, f.tip))

    def test_one_merged_on_bitbucket_at_its_head_finishes(self):
        f = fixture(self)
        f.bb.answers(f.tip, [f.bb.status("a", "SUCCESSFUL")], pr=f.bb.pull_request(f.tip, state="MERGED"))
        p = f.run("tick", "--folder", f.repo, "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.quiet(f, p.stdout, p.stderr)
        self.assertIn(f.task()["id"], json.loads(p.stdout)["done"])
        t = f.task()
        self.assertEqual((t["state"], t["merged"], t["pr"]["provider"]), ("done", True, "bitbucket"))
        self.assertNotIn("main_watch", json.loads(f.saved()))  # GitHub's base watch never takes a Bitbucket name
        self.assertFalse(os.path.isdir(f.wt))

    def test_one_merged_at_another_head_keeps_the_branch(self):
        f = fixture(self)
        f.bb.answers(f.start, [f.bb.status("a", "SUCCESSFUL")], pr=f.bb.pull_request(f.start, state="MERGED"))
        p = f.run("tick", "--folder", f.repo, "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.quiet(f, p.stdout, p.stderr)
        t = f.task()
        self.assertEqual((t["state"], t["merged_head"]), ("done", f.start))
        self.assertIn("what merged was", t["kept"])
        self.assertEqual(f.rev("task/1"), f.tip)
        self.assertTrue(os.path.isdir(f.wt))

    def test_a_provider_without_an_adapter_reaches_no_host(self):
        f = fixture(self)
        f.seed(pr={"provider": "gitlab", "host": "gitlab.com", "repo": "o/r", "number": 7,
                   "url": "https://gitlab.com/o/r/-/merge_requests/7"})
        p = f.run("merge", "1", "--folder", f.repo, "--json")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        error = json.loads(p.stdout)["error"]
        self.assertIn("gitlab", error)
        self.assertIn("nothing was sent", error)
        self.quiet(f, p.stdout, p.stderr)
        self.assertEqual((f.bb.connects, asked(f), f.task()["state"]), ([], [], "ready"))

    def test_ready_refuses_before_anything_is_pushed_or_sent(self):
        f = fixture(self)
        bare = os.path.join(f.tmp, "remote.git")
        f.git(f.tmp, "init", "-q", "--bare", "-b", "main", bare)
        f.git(f.repo, "config", f"url.{bare}.insteadOf", REMOTE)  # a push would land here
        f.seed(state="running")
        before = f.saved()
        p = f.run("ready", "1", "--folder", f.repo, "--summary", "Sign-in works again", "--json")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("doesn't publish to Bitbucket yet", json.loads(p.stdout)["error"])
        self.quiet(f, p.stdout, p.stderr)
        self.assertEqual((f.saved(), f.bb.connects), (before, []))
        r = subprocess.run(["git", "-C", bare, "rev-parse", "--verify", "--quiet", "refs/heads/task/1"], capture_output=True)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
