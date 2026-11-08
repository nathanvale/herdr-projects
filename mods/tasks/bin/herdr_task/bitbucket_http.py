"""Bitbucket Cloud's REST transport: one repository's pull request and the complete statuses of
exactly its head commit (B1), and the two writes publication makes (B2: opening a draft pull request,
and preparing it for review), on this machine's own Git credentials. bitbucket.py is the adapter that
reads for the forge; publications.py owns the writes' claims.

- The folder binds the repository: every view of its remote (the URL written in its config, the one
  git uses after its rewrites, the one it pushes to) names the same Bitbucket repository, or nothing
  is sent. The binding holds no credential: only the HTTPS lookup path and any user written in an
  HTTPS URL. An SSH transport user ("git") is never an account.
- The credential is the execution host's: `git credential fill` in the folder, as git itself would
  ask its configured helper, with every prompt off and a short deadline. Only an ordinary username
  and password answer counts; its password is a Bitbucket API or access token and goes as Bearer
  authentication. No other account, store, setting or Basic fallback is tried; herdr-task never
  approves, rejects or stores a credential. One is asked for each command and dropped after it.
- Requests go only to https://api.bitbucket.org/2.0/repositories/<that repository>, by fixed paths:
  no caller's URL, header or method. A pagination link must stay in the same collection on that
  origin; redirects, foreign or repeated links, counts that disagree and every bound below make the
  read incomplete, never a shorter complete one.
- A write is sent once. Bitbucket refusing its token (401, 403: write-refused) is a refusal; anything else that
  isn't its exact, complete answer (a timeout, a dropped connection, another status, an answer that
  doesn't read or doesn't match) is uncertain-write: it may have happened, and nothing here sends it
  again. Only a write the budget stops before any byte leaves is not-sent.
- Failures are categories (Failure.category), never Bitbucket's or git's own text, so no token, body
  or header reaches output, a task or a log; text taken from Bitbucket (titles, check names) has the
  token removed.

Merging is not this module's: nothing here sends one."""

import http.client
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = "bitbucket.org"
API = "https://api.bitbucket.org"
LIMITS = {"body": 1024 * 1024, "pages": 20, "rows": 1000, "request_s": 8, "total_s": 45,
          "credential_s": 5, "credential_bytes": 16384, "text": 512, "description": 32000, "title": 255,
          "reviewers": 100, "open": 5}

COMMIT = re.compile(r"[0-9a-f]{40}")
SHORT = re.compile(r"[0-9a-f]{7,40}")
REPOSITORY = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_.-]*")
REVIEWER_UUID = re.compile(r"\{?[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\}?", re.I)
ACCOUNT = re.compile(r"[A-Za-z0-9:_-]{1,128}")


def branch_name(name):
    """A branch name herdr-task sends Bitbucket: one git takes and its query can't misread."""
    return (isinstance(name, str) and len(name) <= 255 and bool(BRANCH.fullmatch(name)) and ".." not in name
            and not name.endswith(("/", ".lock")))
STATES = {"OPEN": "OPEN", "MERGED": "MERGED", "DECLINED": "CLOSED", "SUPERSEDED": "CLOSED"}
STATUS = {"SUCCESSFUL": "pass", "INPROGRESS": "pending", "FAILED": "fail", "STOPPED": "fail"}

# What each failure means to the person, in herdr-task's words only.
WORDS = {
    "not-bitbucket": "this folder's remote doesn't point at one and the same Bitbucket repository on bitbucket.org every "
                     "way git uses it",
    "missing-credentials": "this machine's Git credential helper gave no Bitbucket token without asking; set up an API "
                           "or access token for bitbucket.org there",
    "permission-refused": "Bitbucket refused this machine's token for reading it (the token needs pull request read access)",
    "rate-limited": "Bitbucket limited how often it is read; the next look tries again",
    "malformed-response": "Bitbucket's answer wasn't one herdr-task can read",
    "incomplete-read": "Bitbucket's answer didn't come complete, so none of it counts",
    "identity-changed": "Bitbucket answered for another repository, pull request or commit, or it moved while it was read",
    "missing": "Bitbucket has no such pull request in this repository (or this token can't see it)",
    "unavailable": "Bitbucket couldn't be reached from this machine",
    "uncertain-write": "Bitbucket's answer to the write didn't come back whole, so it may or may not have happened",
    "not-sent": "the write wasn't sent: the time this command may take ran out first",
    "write-refused": "Bitbucket refused this machine's token for this change (the token needs pull request write access)",
    "remote-changed": "this folder's remote reads otherwise than when it was bound, so where it goes wasn't checked",
}


class Failure(Exception):
    def __init__(self, category):
        super().__init__(category)
        self.category = category


# ---- the folder's repository ----------------------------------------------------------------

def git_out(folder, *args):
    try:
        r = subprocess.run(["git", "-C", folder, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           universal_newlines=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def origins(folder, remote):
    """Every view git has of the remote's URL: written (its configured url lines), pushurl (configured
    push URLs, often none), used (fetch, after rewrites) and push (after rewrites)."""
    seen = {"written": git_out(folder, "config", "--get-all", f"remote.{remote}.url"),
            "pushurl": git_out(folder, "config", "--get-all", f"remote.{remote}.pushurl") or "",
            "used": git_out(folder, "remote", "get-url", "--all", remote),
            "push": git_out(folder, "remote", "get-url", "--push", "--all", remote)}
    return seen if all(seen[k] for k in ("written", "used", "push")) else None


SSH = re.compile(r"(?:ssh://)?(?:[^@/:]+@)?([^/:]+)(?::\d+)?[:/]([^?#]+)")


def _path_repo(path):
    return re.sub(r"\.git$", "", path.strip("/"))


def binding(seen):
    """The repository the remote's views agree on, with the credential lookup it implies:
    {repo, path, username?}; None when they don't name one Bitbucket repository. Every configured URL
    (url and pushurl lines) must be on bitbucket.org itself; only a view git derives from them by a
    rewrite (url.*.insteadOf) may reach it through an SSH alias of the same path. An HTTPS view must be
    bitbucket.org itself, with no password, query or port but 443."""
    if not seen:
        return None
    repo, path, user = None, None, None
    views = [(view in ("written", "pushurl"), line) for view in ("written", "pushurl", "used", "push")
             for line in seen[view].splitlines()]
    for configured, url in views:
        if re.match(r"https://", url, re.I):
            try:
                u = urllib.parse.urlsplit(url)
                port = u.port
            except ValueError:  # not a URL at all (an unbalanced "[" among others): binds nothing
                return None
            if (u.hostname or "").lower() != HOST or port not in (None, 443) or u.password or u.query or u.fragment:
                return None
            here = urllib.parse.unquote(u.path).strip("/")
            name = urllib.parse.unquote(u.username or "") or None
            if name and (not re.fullmatch(r"[^\r\n\0=]{1,128}", name) or (user and user != name)):
                return None
            user, path = user or name, here
        else:
            m = SSH.fullmatch(url)
            if not m or (configured and m.group(1).lower() != HOST):
                return None
            here = m.group(2)
        found = _path_repo(here)
        if not REPOSITORY.fullmatch(found) or len(found) > 256 or (repo and repo.lower() != found.lower()):
            return None
        repo = repo or found
    if not repo:
        return None
    return {"repo": repo, "path": path or repo + ".git", **({"username": user} if user else {})}


# ---- the host's credential ------------------------------------------------------------------

def _quiet_env():
    false = shutil.which("false") or "/usr/bin/false"
    env = dict(os.environ)
    env.update(GIT_TERMINAL_PROMPT="0", GIT_ASKPASS=false, SSH_ASKPASS=false, GCM_INTERACTIVE="never")
    return env


def credential(folder, remote, seen, bound):
    """The token this machine's Git credential helper gives for the bound repository, asked without
    any prompt. The remote must still read as it did (seen): a change refuses, never another lookup."""
    if origins(folder, remote) != seen:
        raise Failure("identity-changed")
    ask = f"protocol=https\nhost={HOST}\npath={bound['path']}\n" + (f"username={bound['username']}\n" if bound.get("username") else "") + "\n"
    try:
        r = subprocess.run(["git", "-C", folder, "credential", "fill"], input=ask.encode(), stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, env=_quiet_env(), timeout=LIMITS["credential_s"])
    except (OSError, subprocess.SubprocessError):
        raise Failure("missing-credentials")
    if r.returncode != 0 or len(r.stdout) > LIMITS["credential_bytes"]:
        raise Failure("missing-credentials")
    try:
        text = r.stdout.decode()
    except UnicodeDecodeError:
        raise Failure("missing-credentials")
    values = {}
    for row in text.rstrip("\n").split("\n"):
        key, eq, value = row.partition("=")
        if not eq or not key:
            raise Failure("missing-credentials")
        # Asked for an ordinary username and password, never negotiated authentication.
        if key in ("authtype", "credential", "ephemeral", "continue", "url") or key.endswith("[]"):
            raise Failure("missing-credentials")
        if key not in ("protocol", "host", "path", "username", "password"):
            continue  # expiry, refresh tokens and other metadata stay unread
        if key in values:
            raise Failure("missing-credentials")
        values[key] = value
    token, user = values.get("password"), values.get("username")
    if (not token or not re.fullmatch(r"[\x21-\x7e]{1,8192}", token) or not user
            or (bound.get("username") and user != bound["username"]) or values.get("protocol") != "https"
            or values.get("host") != HOST or values.get("path", bound["path"]) != bound["path"]):
        raise Failure("missing-credentials")
    return token


# ---- reads ----------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect is answered as itself (3xx), never followed with the token


class Reader:
    """Reads one bound repository with one token, within LIMITS."""

    def __init__(self, repo, token):
        self.repo, self.token, self.started = repo, token, time.monotonic()
        self.root = f"{API}/2.0/repositories/" + "/".join(urllib.parse.quote(p, safe="") for p in repo.split("/"))
        self.opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def clean(self, text):
        """Bitbucket's text, safe to show: the token (in any form) and control characters gone, bounded."""
        text = str(text)
        for form in (f"Bearer {self.token}", self.token, urllib.parse.quote(self.token, safe="")):
            text = text.replace(form, "[redacted]")
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)[:LIMITS["text"]]

    def has_token(self, value):
        return self.token in value or urllib.parse.quote(self.token, safe="") in value

    def target(self, url, collection):
        """A pagination link, admitted only inside the same collection of this repository on the API."""
        if not isinstance(url, str) or self.has_token(url):
            raise Failure("incomplete-read")
        try:
            u = urllib.parse.urlsplit(url)
            port = u.port
        except ValueError:
            raise Failure("incomplete-read")
        if (u.scheme, u.hostname, port, u.username, u.password, u.fragment) != ("https", "api.bitbucket.org", None, None, None, "") \
                or u.path != urllib.parse.urlsplit(collection).path or not url.startswith(self.root + "/"):
            raise Failure("incomplete-read")
        return url

    def get(self, url, lost="identity-changed"):
        """One GET of a fixed path; lost: what a 404 means there (only a pull request's is "missing")."""
        left = LIMITS["total_s"] - (time.monotonic() - self.started)
        if left <= 0:
            raise Failure("incomplete-read")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
        # A wall-clock bound on the whole request, not only on each socket wait: a body that trickles in
        # past it is incomplete.
        deadline = time.monotonic() + min(LIMITS["request_s"], left)
        try:
            with self.opener.open(req, timeout=min(LIMITS["request_s"], left)) as r:
                body = b""
                while len(body) <= LIMITS["body"]:
                    if time.monotonic() > deadline:
                        raise Failure("incomplete-read")
                    chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                    if not chunk:
                        break
                    body += chunk
        except Failure:
            raise
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            if code in (401, 403):
                raise Failure("permission-refused")
            if code == 404:
                raise Failure(lost)
            if code == 429:
                raise Failure("rate-limited")
            raise Failure("incomplete-read" if 300 <= code < 400 else "unavailable")
        except (TimeoutError, socket.timeout):
            raise Failure("incomplete-read")
        except urllib.error.URLError as e:
            raise Failure("incomplete-read" if isinstance(e.reason, (TimeoutError, socket.timeout)) else "unavailable")
        except (OSError, ValueError, http.client.HTTPException):
            raise Failure("unavailable")
        if len(body) > LIMITS["body"]:
            raise Failure("incomplete-read")
        try:
            value = json.loads(body.decode())
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise Failure("malformed-response")
        if not isinstance(value, dict):
            raise Failure("malformed-response")
        return value

    def pages(self, url):
        """Every row of a paged collection, or Failure: no row counts from a read that isn't whole."""
        rows, visited, size, nxt = [], set(), None, url
        while nxt:
            here = self.target(nxt, url)
            if here in visited or len(visited) >= LIMITS["pages"]:
                raise Failure("incomplete-read")
            visited.add(here)
            page = self.get(here, "incomplete-read")
            values, nxt = page.get("values"), page.get("next")
            if not isinstance(values, list) or len(values) > 100 or (nxt is not None and (not isinstance(nxt, str) or not nxt)):
                raise Failure("malformed-response")
            for name in ("page", "pagelen"):
                if name in page and (type(page[name]) is not int or page[name] < 1):
                    raise Failure("incomplete-read")
            if "previous" in page:
                self.target(page["previous"], url)
            if "size" in page:
                if type(page["size"]) is not int or not 0 <= page["size"] <= LIMITS["rows"] or size not in (None, page["size"]):
                    raise Failure("incomplete-read")
                size = page["size"]
            rows.extend(values)
            if len(rows) > LIMITS["rows"]:
                raise Failure("incomplete-read")
        if size is not None and len(rows) != size:
            raise Failure("incomplete-read")
        return rows

    def link(self, value, path):
        """A web link Bitbucket gave, admitted only as exactly this repository's page."""
        href = (value or {}).get("href") if isinstance(value, dict) else None
        if not isinstance(href, str) or self.has_token(href):
            raise Failure("malformed-response")
        try:
            u = urllib.parse.urlsplit(href)
        except ValueError:
            raise Failure("malformed-response")
        if (u.scheme, u.netloc, u.query, u.fragment) != ("https", HOST, "", "") or u.path.rstrip("/").lower() != path.lower():
            raise Failure("malformed-response")
        return href

    def same_repository(self, row):
        if not isinstance(row, dict) or not isinstance(row.get("full_name"), str) or row["full_name"].lower() != self.repo.lower():
            raise Failure("identity-changed")
        self.link((row.get("links") or {}).get("html") if isinstance(row.get("links"), dict) else None, f"/{self.repo}")

    def pull_request(self, number):
        return self.parse(self.get(f"{self.root}/pullrequests/{number}", "missing"), number)

    def parse(self, row, number=None):
        """A pull request row, as this repository's own branch into this repository (a fork's is never the
        task's): {number, url, state, draft, title, short, source, base, description}; number:
        the one asked for (another refuses: identity-changed)."""
        if not isinstance(row, dict):
            raise Failure("malformed-response")
        src, dst = row.get("source"), row.get("destination")
        if not (isinstance(src, dict) and isinstance(dst, dict)):
            raise Failure("malformed-response")
        self.same_repository(src.get("repository"))
        self.same_repository(dst.get("repository"))
        head = (src.get("commit") or {}).get("hash") if isinstance(src.get("commit"), dict) else None
        source = (src.get("branch") or {}).get("name") if isinstance(src.get("branch"), dict) else None
        base = (dst.get("branch") or {}).get("name") if isinstance(dst.get("branch"), dict) else None
        n = row.get("id")
        if (type(n) is not int or n < 1 or (number is not None and n != number) or not isinstance(row.get("state"), str)
                or row["state"] not in STATES
                or not isinstance(row.get("title"), str) or not isinstance(row.get("draft", False), bool)
                or not isinstance(row.get("description", ""), (str, type(None)))
                or not isinstance(head, str) or not SHORT.fullmatch(head)
                or not all(isinstance(b, str) and len(b) <= 255 and BRANCH.fullmatch(b) for b in (source, base))):
            raise Failure("identity-changed" if type(n) is int and number is not None and n != number else "malformed-response")
        url = self.link((row.get("links") or {}).get("html") if isinstance(row.get("links"), dict) else None,
                        f"/{self.repo}/pull-requests/{n}")
        return {"number": n, "url": url, "state": STATES[row["state"]], "draft": row.get("draft", False),
                "title": self.clean(row["title"]), "short": head, "source": source, "base": base,
                "description": row.get("description") or ""}

    def commit(self, short):
        """The full commit Bitbucket itself resolves the pull request's (often abbreviated) head to."""
        row = self.get(f"{self.root}/commit/{urllib.parse.quote(short, safe='')}")
        full = row.get("hash")
        if not isinstance(full, str) or not COMMIT.fullmatch(full) or not full.startswith(short):
            raise Failure("identity-changed" if isinstance(full, str) and COMMIT.fullmatch(full) else "malformed-response")
        self.same_repository(row.get("repository"))
        return full

    def statuses(self, full):
        """Every build status reported on exactly this commit: [{name, state: pass|pending|fail, url?}]."""
        keys, out = set(), []
        for row in self.pages(f"{self.root}/commit/{full}/statuses?pagelen=100"):
            if (not isinstance(row, dict) or not isinstance(row.get("key"), str) or not row["key"] or row["key"] in keys
                    or not isinstance(row.get("state"), str) or row["state"] not in STATUS or not all(isinstance(row.get(k), (str, type(None))) for k in ("name", "url"))):
                raise Failure("malformed-response")
            keys.add(row["key"])
            commit = (row.get("commit") or {}).get("hash") if isinstance(row.get("commit"), dict) else None
            if commit is not None and commit != full:
                raise Failure("identity-changed")
            item = {"name": self.clean(row.get("name") or row["key"]), "state": STATUS[row["state"]]}
            link = row.get("url")
            try:
                shown = isinstance(link, str) and not self.has_token(link) and urllib.parse.urlsplit(link).scheme == "https" \
                    and not urllib.parse.urlsplit(link).username
            except ValueError:
                shown = False  # a status's own link is its poster's: one that isn't a URL is left off, not fatal
            if shown:
                item["url"] = link[:2048]
            out.append(item)
        return out


    # ---- publication (B2) ---------------------------------------------------------------------

    def still(self):
        """Refuses (remote-changed) once the remote reads otherwise than when it was bound: the last check
        before each effect, so a push or write never goes where the binding wasn't checked."""
        if origins(self.folder, self.remote) != self.seen:
            raise Failure("remote-changed")

    def branch(self, name):
        """The full commit Bitbucket's branch `name` holds, or None when it has no such branch."""
        try:
            row = self.get(f"{self.root}/refs/branches/{urllib.parse.quote(name, safe='')}", "missing")
        except Failure as e:
            if e.category == "missing":
                return None
            raise
        target = row.get("target")
        full = target.get("hash") if isinstance(target, dict) else None
        if not isinstance(row.get("name"), str) or not isinstance(full, str) or not COMMIT.fullmatch(full):
            raise Failure("malformed-response")
        if row["name"] != name:
            raise Failure("identity-changed")
        return full

    def open_from(self, branch):
        """Every open pull request from this repository's branch, each read in full, into any base."""
        q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"', safe="")
        rows = self.pages(f"{self.root}/pullrequests?q={q}&pagelen=50")
        if len(rows) > LIMITS["open"]:
            raise Failure("incomplete-read")
        out = []
        for row in rows:
            n = row.get("id") if isinstance(row, dict) else None
            if type(n) is not int or n < 1 or any(p["number"] == n for p in out):
                raise Failure("malformed-response")
            pr = self.pull_request(n)
            if pr["source"] != branch or pr["state"] != "OPEN":
                raise Failure("identity-changed")  # the query answered for another branch or state
            out.append(pr)
        return out

    def kept(self, row):
        """What preparing a pull request keeps exactly as it is now: its title, reviewers, destination and
        close_source_branch (whatever its value: true asks Bitbucket to close the branch on merge)."""
        title, close = row.get("title"), row.get("close_source_branch")
        if not isinstance(title, str) or not title or self.clean(title) != title or not isinstance(close, bool):
            raise Failure("malformed-response")
        people = row.get("reviewers", [])
        if not isinstance(people, list) or len(people) > LIMITS["reviewers"]:
            raise Failure("malformed-response")
        reviewers, ids = [], set()
        for person in people:
            uid = person.get("uuid") if isinstance(person, dict) else None
            account = person.get("account_id") if isinstance(person, dict) else None
            if not isinstance(person, dict) or (uid is None and account is None) \
                    or (uid is not None and not (isinstance(uid, str) and REVIEWER_UUID.fullmatch(uid))) \
                    or (account is not None and not (isinstance(account, str) and ACCOUNT.fullmatch(account))):
                raise Failure("malformed-response")
            for x in (uid, account):
                if x is not None:
                    if x in ids:
                        raise Failure("malformed-response")
                    ids.add(x)
            reviewers.append({"uuid": uid} if uid is not None else {"account_id": account})
        dst = row.get("destination") if isinstance(row.get("destination"), dict) else {}
        base = (dst.get("branch") or {}).get("name") if isinstance(dst.get("branch"), dict) else None
        if not isinstance(base, str) or not BRANCH.fullmatch(base):
            raise Failure("malformed-response")
        return {"title": title, "reviewers": reviewers, "close_source_branch": close,
                "destination": {"branch": {"name": base}, "repository": {"full_name": self.repo}}}

    def current(self, number):
        """Pull request #number as it is now, and what preparing it keeps: (pr, kept)."""
        row = self.get(f"{self.root}/pullrequests/{number}", "missing")
        return self.parse(row, number), self.kept(row)

    def can_send(self):
        """Whether a write would still be sent: time is left for its whole request."""
        return LIMITS["total_s"] - (time.monotonic() - self.started) >= LIMITS["request_s"]

    def send(self, method, url, body):
        """One write, sent once: Bitbucket's answer, or Failure: not-sent (no byte left), write-refused
        (401, 403: refused) or uncertain-write (anything else: it may have happened)."""
        if not self.can_send():
            raise Failure("not-sent")
        data = json.dumps(body).encode()
        if self.has_token(data.decode()):
            raise Failure("not-sent")
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/json", "Content-Type": "application/json"})
        deadline = time.monotonic() + LIMITS["request_s"]
        try:
            with self.opener.open(req, timeout=LIMITS["request_s"]) as r:
                status, raw = r.status, b""
                while len(raw) <= LIMITS["body"]:
                    if time.monotonic() > deadline:
                        raise Failure("uncertain-write")
                    chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                    if not chunk:
                        break
                    raw += chunk
        except Failure:
            raise
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            raise Failure("write-refused" if code in (401, 403) else "uncertain-write")
        except (OSError, ValueError, http.client.HTTPException):  # timeouts and dropped connections among them
            raise Failure("uncertain-write")
        if status not in (200, 201) or len(raw) > LIMITS["body"]:
            raise Failure("uncertain-write")
        try:
            value = json.loads(raw.decode())
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise Failure("uncertain-write")
        if not isinstance(value, dict):
            raise Failure("uncertain-write")
        return value

    def create(self, branch, base, head, title, description):
        """Opens a draft pull request from branch (at exactly head) into base, close_source_branch false:
        its parsed answer, which must be exactly that, or Failure (send())."""
        row = self.send("POST", f"{self.root}/pullrequests", {
            "title": title, "description": description, "draft": True, "close_source_branch": False,
            "source": {"branch": {"name": branch}, "commit": {"hash": head}, "repository": {"full_name": self.repo}},
            "destination": {"branch": {"name": base}, "repository": {"full_name": self.repo}}})
        try:
            pr = self.parse(row)
        except Failure:
            raise Failure("uncertain-write")
        if (pr["source"], pr["base"], pr["state"], pr["draft"]) != (branch, base, "OPEN", True) or not head.startswith(pr["short"]):
            raise Failure("uncertain-write")
        return pr

    def prepare(self, number, kept, description, branch, base, head):
        """Marks pull request #number ready for review (draft off) with this description, sending back the
        fields it keeps as they were read (kept): its parsed answer, which must be exactly that, or Failure."""
        row = self.send("PUT", f"{self.root}/pullrequests/{number}", {**kept, "description": description, "draft": False})
        try:
            pr, again = self.parse(row, number), self.kept(row)
        except Failure:
            raise Failure("uncertain-write")
        if (pr["source"], pr["base"], pr["state"], pr["draft"]) != (branch, base, "OPEN", False) \
                or not head.startswith(pr["short"]) or again != kept:
            raise Failure("uncertain-write")
        return pr

def session(folder, remote):
    """A Reader for the folder's bound Bitbucket repository on this machine's token, once that token reads
    this very repository (404: it can't see it). It keeps the remote's views it was bound by (seen), so
    still() refuses once they change. Failure otherwise."""
    seen = origins(folder, remote)
    bound = binding(seen)
    if not bound:
        raise Failure("not-bitbucket")
    token = credential(folder, remote, seen, bound)
    r = Reader(bound["repo"], token)
    r.folder, r.remote, r.seen, r.bound = folder, remote, seen, bound
    r.same_repository(r.get(r.root, "missing"))
    return r


def read_pull_request(folder, remote, number, reader=None):
    """Pull request #number of the folder's bound Bitbucket repository, with the complete statuses of
    exactly its head: {repo, number, url, state, draft, title, head (full), source, base, checks}.
    The pull request is read again after its statuses: a head, branch or state that moved meanwhile
    refuses (identity-changed), so the checks are always the head's that is returned. Failure otherwise.
    reader: a session() already open (publication's), else one is opened for this read."""
    r = reader or session(folder, remote)
    pr = r.pull_request(number)
    head = r.commit(pr["short"])
    checks = r.statuses(head)
    again = r.pull_request(number)
    if any(again[k] != pr[k] for k in ("short", "source", "base", "state")):
        raise Failure("identity-changed")
    out = {**pr, "repo": r.repo, "head": head, "checks": checks}
    out.pop("short")
    out.pop("description")
    if r.has_token(json.dumps(out)):
        raise Failure("malformed-response")
    return out
