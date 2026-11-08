"""Bitbucket Cloud's REST transport, for reads (B1): one repository's pull request and the complete
statuses of exactly its head commit, on this machine's own Git credentials. bitbucket.py is the
adapter that reads them for the forge.

- The folder binds the repository: every view of its remote (the URL written in its config, the one
  git uses after its rewrites, the one it pushes to) names the same Bitbucket repository, or nothing
  is sent. The binding holds no credential: only the HTTPS lookup path and any user written in an
  HTTPS URL. An SSH transport user ("git") is never an account.
- The credential is the execution host's: `git credential fill` in the folder, as git itself would
  ask its configured helper, with every prompt off and a short deadline. Only an ordinary username
  and password answer counts; its password is a Bitbucket API or access token and goes as Bearer
  authentication. No other account, store, setting or Basic fallback is tried; herdr-task never
  approves, rejects or stores a credential. One is asked for each read and dropped after it.
- Requests go only to https://api.bitbucket.org/2.0/repositories/<that repository>, by fixed paths:
  no caller's URL, header or method. A pagination link must stay in the same collection on that
  origin; redirects, foreign or repeated links, counts that disagree and every bound below make the
  read incomplete, never a shorter complete one.
- Failures are categories (Failure.category), never Bitbucket's or git's own text, so no token, body
  or header reaches output, a task or a log; text taken from Bitbucket (titles, check names) has the
  token removed.

Nothing here writes to Bitbucket: publication, readiness and merging are not this module's."""

import http.client
import json
import os
import re
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = "bitbucket.org"
API = "https://api.bitbucket.org"
LIMITS = {"body": 1024 * 1024, "pages": 20, "rows": 1000, "request_s": 8, "total_s": 45,
          "credential_s": 5, "credential_bytes": 16384, "text": 512}

COMMIT = re.compile(r"[0-9a-f]{40}")
SHORT = re.compile(r"[0-9a-f]{7,40}")
REPOSITORY = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_.-]*")
STATES = {"OPEN": "OPEN", "MERGED": "MERGED", "DECLINED": "CLOSED", "SUPERSEDED": "CLOSED"}
STATUS = {"SUCCESSFUL": "pass", "INPROGRESS": "pending", "FAILED": "fail", "STOPPED": "fail"}

# What each failure means to the person, in herdr-task's words only.
WORDS = {
    "not-bitbucket": "this folder's remote isn't one Bitbucket repository herdr-task can bind (its written, fetch and push "
                     "URLs must all name the same one on bitbucket.org)",
    "missing-credentials": "this machine's Git credential helper gave no Bitbucket token for it without asking "
                           "(set up a REST-capable API or access token for bitbucket.org there)",
    "permission-refused": "Bitbucket refused this machine's token for reading it (the token needs pull request read access)",
    "rate-limited": "Bitbucket limited how often it is read; the next look tries again",
    "malformed-response": "Bitbucket's answer wasn't one herdr-task can read",
    "incomplete-read": "Bitbucket's answer didn't come complete, so none of it counts",
    "identity-changed": "Bitbucket answered for another repository, pull request or commit, or it moved while it was read",
    "missing": "Bitbucket has no such pull request in this repository (or this token can't see it)",
    "unavailable": "Bitbucket couldn't be reached from this machine",
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
    """Every view git has of the remote's URL: written (config), used (fetch, after rewrites), push."""
    seen = {"written": git_out(folder, "config", "--get-all", f"remote.{remote}.url"),
            "used": git_out(folder, "remote", "get-url", "--all", remote),
            "push": git_out(folder, "remote", "get-url", "--push", "--all", remote)}
    return seen if all(seen.values()) else None


SSH = re.compile(r"(?:ssh://)?(?:[^@/:]+@)?([^/:]+)(?::\d+)?[:/]([^?#]+)")


def _path_repo(path):
    return re.sub(r"\.git$", "", path.strip("/"))


def binding(seen):
    """The repository the remote's three views agree on, with the credential lookup it implies:
    {repo, path, username?}; None when they don't name one Bitbucket repository. The written URL
    must be on bitbucket.org; a rewrite may reach it through an SSH alias of the same path, and an
    HTTPS view must be bitbucket.org itself, with no password, query or port but 443."""
    if not seen:
        return None
    repo, path, user = None, None, None
    for n, url in enumerate(line for view in ("written", "used", "push") for line in seen[view].splitlines()):
        if re.match(r"https://", url, re.I):
            u = urllib.parse.urlsplit(url)
            try:
                port = u.port
            except ValueError:
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
            if not m or (n == 0 and m.group(1).lower() != HOST):
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
        u = urllib.parse.urlsplit(url)
        try:
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
        try:
            with self.opener.open(req, timeout=min(LIMITS["request_s"], left)) as r:
                body = r.read(LIMITS["body"] + 1)
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
        except (OSError, ValueError, http.client.HTTPException):
            raise Failure("unavailable")
        if len(body) > LIMITS["body"]:
            raise Failure("incomplete-read")
        try:
            value = json.loads(body.decode())
        except (UnicodeDecodeError, ValueError):
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
        u = urllib.parse.urlsplit(href)
        if (u.scheme, u.netloc, u.query, u.fragment) != ("https", HOST, "", "") or u.path.rstrip("/").lower() != path.lower():
            raise Failure("malformed-response")
        return href

    def same_repository(self, row):
        if not isinstance(row, dict) or not isinstance(row.get("full_name"), str) or row["full_name"].lower() != self.repo.lower():
            raise Failure("identity-changed")
        self.link((row.get("links") or {}).get("html") if isinstance(row.get("links"), dict) else None, f"/{self.repo}")

    def pull_request(self, number):
        row = self.get(f"{self.root}/pullrequests/{number}", "missing")
        src, dst = row.get("source"), row.get("destination")
        if not (isinstance(src, dict) and isinstance(dst, dict)):
            raise Failure("malformed-response")
        # This repository's own branch into this repository: a fork's pull request is never the task's.
        self.same_repository(src.get("repository"))
        self.same_repository(dst.get("repository"))
        head = (src.get("commit") or {}).get("hash") if isinstance(src.get("commit"), dict) else None
        source = (src.get("branch") or {}).get("name") if isinstance(src.get("branch"), dict) else None
        base = (dst.get("branch") or {}).get("name") if isinstance(dst.get("branch"), dict) else None
        if (type(row.get("id")) is not int or row["id"] != number or row.get("state") not in STATES
                or not isinstance(row.get("title"), str) or not isinstance(row.get("draft", False), bool)
                or not isinstance(head, str) or not SHORT.fullmatch(head)
                or not all(isinstance(b, str) and len(b) <= 255 and BRANCH.fullmatch(b) for b in (source, base))):
            raise Failure("identity-changed" if type(row.get("id")) is int and row["id"] != number else "malformed-response")
        url = self.link((row.get("links") or {}).get("html") if isinstance(row.get("links"), dict) else None,
                        f"/{self.repo}/pull-requests/{number}")
        return {"number": number, "url": url, "state": STATES[row["state"]], "draft": row.get("draft", False),
                "title": self.clean(row["title"]), "short": head, "source": source, "base": base}

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
                    or row.get("state") not in STATUS or not all(isinstance(row.get(k), (str, type(None))) for k in ("name", "url"))):
                raise Failure("malformed-response")
            keys.add(row["key"])
            commit = (row.get("commit") or {}).get("hash") if isinstance(row.get("commit"), dict) else None
            if commit is not None and commit != full:
                raise Failure("identity-changed")
            item = {"name": self.clean(row.get("name") or row["key"]), "state": STATUS[row["state"]]}
            link = row.get("url")
            if isinstance(link, str) and not self.has_token(link) and urllib.parse.urlsplit(link).scheme == "https" \
                    and not urllib.parse.urlsplit(link).username:
                item["url"] = link[:2048]
            out.append(item)
        return out


def read_pull_request(folder, remote, number):
    """Pull request #number of the folder's bound Bitbucket repository, with the complete statuses of
    exactly its head: {repo, number, url, state, draft, title, head (full), source, base, checks}.
    The pull request is read again after its statuses: a head, branch or state that moved meanwhile
    refuses (identity-changed), so the checks are always the head's that is returned. Failure otherwise."""
    seen = origins(folder, remote)
    bound = binding(seen)
    if not bound:
        raise Failure("not-bitbucket")
    token = credential(folder, remote, seen, bound)
    r = Reader(bound["repo"], token)
    r.same_repository(r.get(r.root))  # the token reads this very repository
    pr = r.pull_request(number)
    head = r.commit(pr["short"])
    checks = r.statuses(head)
    again = r.pull_request(number)
    if any(again[k] != pr[k] for k in ("short", "source", "base", "state")):
        raise Failure("identity-changed")
    out = {**pr, "repo": bound["repo"], "head": head, "checks": checks}
    out.pop("short")
    if r.has_token(json.dumps(out)):
        raise Failure("malformed-response")
    return out
