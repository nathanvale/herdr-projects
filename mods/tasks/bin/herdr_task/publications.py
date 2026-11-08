"""Bitbucket publication (B2): Ready pushes a task's branch on a frozen route, opens its draft pull
request and then prepares it for review, each owned effect under one durable claim, so a lost reply is
reconciled and never sent again. forge.py reaches it for a Bitbucket folder; bitbucket_http.py sends.

The claim. Every Bitbucket repository branch a task publishes has one claim, in this execution host's
claims file (STORE/.publications.json, under its own lock, written and synced before anything it
covers is sent). It names its owner (the task, its folder, checkout and machine), the push route and
remote it was bound by, and each stage:

- pushed: the commit git confirmed on Bitbucket's branch (git's own success, or the branch read back
  at exactly that commit). A fact: kept whatever fails after it.
- draft: opening the draft pull request. Its operation id (a UUID) is saved as uncertain before the
  write is sent, and goes in the pull request's description (a last line `Herdr-Operation: <id>`).
- ready: preparing it for review (draft off, the summary as description), with its own operation id.

A stage whose answer didn't come back whole stays uncertain. Ready then sends nothing that changes
anything (no push, no second pull request, no preparation) until Bitbucket shows positive, exact
evidence: for the draft, exactly one open pull request from the branch into its base, at the head
that was sent, whose description carries that same id; for ready, that pull request open at the head
that was sent with draft off. Then the stage is confirmed under the same id. An empty or failed
lookup, or anything that changed, leaves it uncertain: never released, retried or replaced here.

Concurrency, as it actually is. One execution host: one claim per repository branch across all its
folders and tasks, taken under the claims file's lock before the push, so a second task, folder or
command there is refused before anything is sent. Two execution hosts: each has its own claims file
(herdr-task keeps no shared store, and runs a folder's commands on the machine holding it), so neither
sees the other's claim. Between them only Bitbucket's own answers stand: a host never opens a pull
request while any is open from the branch, and never adopts, reconciles or prepares one whose
description carries another operation's id, so neither takes over the other's. Two hosts publishing
the same branch at the same moment can each open one, as Bitbucket offers no conditional create;
the next ready of either then sees two open and refuses, for the person.

Merging stays refused (bitbucket.py): nothing here asks Bitbucket, git or an agent to merge."""

import fcntl
import json
import os
import re
import socket
import subprocess
import time
import uuid

from .base import Fail, now, STORE
from . import bitbucket_http as http
from .bitbucket import ACCESS, NAME, remote_of, SIGN_IN
from .settings import machine_name

CLAIMS = os.path.join(STORE, ".publications.json")
MARK = "Herdr-Operation"
MARKS = re.compile(rf"^{MARK}: ([0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}})[ \t]*$", re.M)
PUSH_S, LOOK_S = 90, 60
UNCERTAIN, CONFIRMED = "uncertain", "confirmed"


class Outcome(Fail):
    """Ready refused for a Bitbucket publication, with what is known to have happened (--json:
    publication). result: refused (this command changed nothing on Bitbucket), changed (it made the
    changes `changed` lists, each confirmed, then stopped: pushed, draft), uncertain (a pull request write
    it sent may or may not have happened; the claim holds its id) or held (an earlier one still is
    uncertain, and this command sent nothing that changes anything). The claim's facts come with it."""

    def __init__(self, words, result, claim=None, changed=()):
        super().__init__(words)
        self.publication = {"result": "changed" if result == "refused" and changed else result,
                            "changed": list(changed), **(facts_of(claim) if claim else {})}


# ---- the claims file --------------------------------------------------------------------------

class Claims:
    """This host's claims, locked while open: `with Claims() as c: c.data["claims"][key] = ...; c.dirty = True`.
    A change is on disk (synced) when the block ends, before anything it covers is sent."""

    def __init__(self, write=True):
        self.write, self.dirty = write, False

    def __enter__(self):
        os.makedirs(STORE, exist_ok=True)
        self.lock = open(CLAIMS + ".lock", "a")
        fcntl.flock(self.lock, fcntl.LOCK_EX if self.write else fcntl.LOCK_SH)
        try:
            with open(CLAIMS) as f:
                self.data = json.load(f)
        except FileNotFoundError:
            self.data = {}
        except ValueError:
            self.close()
            raise Fail(f"{CLAIMS} isn't valid JSON, so no Bitbucket publication can be checked or claimed. Nothing was "
                       "pushed or sent. It holds what herdr-task knows about pull requests it opened: repair it, don't remove it.")
        if not isinstance(self.data, dict) or not isinstance(self.data.setdefault("claims", {}), dict):
            self.close()
            raise Fail(f"{CLAIMS} isn't a claims file herdr-task wrote; nothing was pushed or sent.")
        self.data.setdefault("version", 1)
        return self

    def close(self):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    def __exit__(self, kind, *_):
        try:
            if self.write and self.dirty:
                tmp = f"{CLAIMS}.{os.getpid()}.tmp"
                with open(tmp, "w") as f:
                    json.dump(self.data, f, indent=2)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, CLAIMS)
                d = os.open(STORE, os.O_RDONLY)
                try:
                    os.fsync(d)
                finally:
                    os.close(d)
        finally:
            self.close()


def key_of(repo, branch):
    return f"{http.HOST}/{repo.lower()}:{branch}"


def update(key, change):
    """change(claim) under the lock, on the claim as it is on disk now; saved before this returns.
    Returns the claim as saved (None: there is none)."""
    with Claims() as c:
        claim = c.data["claims"].get(key)
        out = change(claim)
        if out is None:
            c.data["claims"].pop(key, None)
        else:
            out["at"] = now()
            c.data["claims"][key] = out
        c.dirty = True
        return out


def facts_of(claim):
    """A claim as public output gives it: {repo, branch, base, pushed, draft, ready}, each stage
    {operation, state[, pr, head]} or None."""
    stage = lambda st: ({"operation": st["id"], "state": st["state"], "head": st.get("head"),
                         **({"pr": st["pr"]["url"]} if st.get("pr") else {})} if st else None)
    return {"repo": claim["repo"], "branch": claim["branch"], "base": claim.get("base"),
            "pushed": claim.get("pushed"), "draft": stage(claim.get("draft")), "ready": stage(claim.get("ready"))}


def owner_of(s, t):
    return {"task": s.key(t), "folder": s.loc["folder"], "worktree": t.get("worktree"),
            "machine": machine_name() or socket.gethostname()}


def facts(s, t):
    """The claim this task holds on this host, as public output gives it; None without one."""
    if (t.get("pr") or {}).get("provider") != "bitbucket" and not os.path.exists(CLAIMS):
        return None
    try:
        with Claims(write=False) as c:
            mine = owner_of(s, t)
            for claim in c.data["claims"].values():
                if isinstance(claim, dict) and claim.get("owner") == mine:
                    return facts_of(claim)
    except Fail:
        return None
    return None


# ---- git, on the frozen route -----------------------------------------------------------------

def push_route(wt, seen):
    """The one URL the branch is pushed to: the push view git derives from the remote (one only),
    pushed to as written, which no rewrite of git's (url.*.insteadOf, url.*.pushInsteadOf) touches
    again; None otherwise. Bound once, and every push and look goes there."""
    lines = (seen.get("push") or "").splitlines()
    if len(lines) != 1 or lines[0].startswith("-") or re.search(r"\s", lines[0]):
        return None
    url = lines[0]
    rules = http.git_out(wt, "config", "--get-regexp", r"^url\..*\.(insteadof|pushinsteadof)$") or ""
    for row in rules.splitlines():
        _, _, prefix = row.partition(" ")
        if prefix and url.startswith(prefix):
            return None
    return url


def quiet_git(wt, *args, timeout):
    """git in the checkout with every prompt off, bounded: (ok, its output)."""
    try:
        r = subprocess.run(["git", "-C", wt, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           universal_newlines=True, env=http._quiet_env(), timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return r.returncode == 0, r.stdout.strip()


def look(wt, url, branch):
    """The commit the route's branch holds, as git reads it there: the commit, "" for none, None when
    git couldn't say."""
    ok, out = quiet_git(wt, "ls-remote", "--heads", url, f"refs/heads/{branch}", timeout=LOOK_S)
    if not ok:
        return None
    rows = [line.split("\t") for line in out.splitlines()]
    if not rows:
        return ""
    if len(rows) == 1 and len(rows[0]) == 2 and rows[0][1] == f"refs/heads/{branch}" and http.COMMIT.fullmatch(rows[0][0]):
        return rows[0][0]
    return None


def push(wt, url, branch, head, there):
    """Pushes head to the route's branch, only over what Bitbucket said it holds (there; None: no such
    branch). True: the branch holds head (git said so, or reading it back does). False: it doesn't.
    None: git couldn't say."""
    ref = f"refs/heads/{branch}"
    ok, _ = quiet_git(wt, "push", "--porcelain", f"--force-with-lease={ref}:{there or ''}", url, f"{head}:{ref}", timeout=PUSH_S)
    if ok:
        return True
    seen = look(wt, url, branch)  # a lost answer is never a reason to push again: read what is there
    return None if seen is None else seen == head


# ---- what is sent -----------------------------------------------------------------------------

def described(text, op):
    """A description of at most Bitbucket's bound, its last line naming the operation that wrote it."""
    tail = f"\n\n{MARK}: {op}"
    text = (text or "").strip()
    room = http.LIMITS["description"] - len(tail)
    return (text if len(text) <= room else text[:room - 1] + "…") + tail


def marks(pr):
    return set(MARKS.findall(pr.get("description") or ""))


def heads(pr, head):
    """Bitbucket's (often abbreviated) head is exactly this commit."""
    return bool(pr.get("short")) and head.startswith(pr["short"])


def record(r, pr):
    return {"provider": "bitbucket", "host": http.HOST, "repo": r.repo, "number": pr["number"], "url": pr["url"]}


# ---- Ready ------------------------------------------------------------------------------------

def publish(s, t, where, summary=None):
    """Publishes the task's branch to its Bitbucket repository and prepares its pull request for review:
    the record Ready keeps ({provider, host, repo, number, url}). Refuses (Outcome) with what happened."""
    ref, wt, br, base = s.ref(t), t["worktree"], t["branch"], t.get("base") or "main"
    stays = "The task stays as it was"
    for name in (br, base):
        if not http.branch_name(name):
            raise Outcome(f"{name!r} isn't a branch name herdr-task sends Bitbucket; nothing was pushed or sent. {stays}.", "refused")
    ok, head, _ = http_git(wt, "rev-parse", "--verify", "--quiet", f"refs/heads/{br}")
    if not ok or not http.COMMIT.fullmatch(head or "") or head != t.get("head"):
        raise Outcome(f"{br} here isn't at the commit ready was run at ({(t.get('head') or '')[:7]}); nothing was pushed or "
                      f"sent. Commit, then run ready again.", "refused")
    remote = remote_of(wt)
    seen = http.origins(wt, remote) if remote else None
    bound = http.binding(seen)
    if not bound or bound["repo"] != where["repo"]:
        raise Outcome(f"This task's checkout doesn't push to {where['repo']} on Bitbucket in every way git uses its remote; "
                      f"nothing was pushed or sent. {stays}.", "refused")
    url = push_route(wt, seen)
    if not url:
        raise Outcome(f"This task's remote {remote} pushes to more than one place, or a rewrite of git's moves where it "
                      f"pushes, so the push can't be held to one route; nothing was pushed or sent. {stays}.", "refused")
    key, owner = key_of(bound["repo"], br), owner_of(s, t)
    route = {"remote": remote, "push": url, "seen": seen}
    saved = t.get("pr") if (t.get("pr") or {}).get("provider") == "bitbucket" else None

    # 1. The claim, before anything is sent: this task's, or none yet (taken now).
    fresh = []

    def take(claim):
        if claim is None:
            fresh.append(True)
            return {"repo": bound["repo"], "branch": br, "base": base, "owner": owner, "route": route,
                    "pushed": None, "draft": None, "ready": None, "made": now()}
        if claim.get("owner") != owner:
            o = claim.get("owner") or {}
            if not finished(s, claim):
                raise Outcome(f"{bound['repo']}'s branch {br} is claimed for publication by {o.get('task')} in {o.get('folder')} "
                              f"on {o.get('machine')}, and one branch has one owner; nothing was pushed or sent. {stays}.", "refused", claim)
            fresh.append(True)
            return {**take(None), "made": now()}
        held = [n for n in ("draft", "ready") if (claim.get(n) or {}).get("state") == UNCERTAIN]
        if held and claim.get("route") != route:
            raise Outcome(f"This task's remote reads otherwise than when its uncertain {held[0]} step was sent (operation "
                          f"{claim[held[0]]['id']}), so it can't be reconciled here; nothing was pushed or sent. Put the remote "
                          "back as it was, then run ready again.", "held", claim)
        if claim.get("base") != base and claim.get("draft"):
            raise Outcome(f"{br}'s pull request was claimed into {claim.get('base')}, and this task merges into {base}; nothing "
                          f"was pushed or sent. {stays}.", "refused", claim)
        return {**claim, "base": base, "route": route}
    claim = update(key, take)
    changed = []  # what this command changed on Bitbucket, each confirmed: pushed, draft

    def refuse(words, result="refused"):
        nonlocal claim
        if fresh and result == "refused" and not claim.get("pushed") and not claim.get("draft"):
            claim = update(key, lambda c: None if c and c.get("owner") == owner and not (c.get("pushed") or c.get("draft")) else c) or claim
        raise Outcome(words, result, claim, changed)

    def save(change):
        nonlocal claim
        claim = update(key, lambda c: change(dict(c)))

    if saved and claim.get("draft") and (claim["draft"].get("pr") or {}).get("number") not in (None, saved.get("number")):
        refuse(f"This task records pull request #{saved.get('number')}, and its claim is for #{claim['draft']['pr']['number']}; "
               f"nothing was pushed or sent. {stays}.")

    # 2. Bitbucket as it is now, on this machine's token (zero effect).
    try:
        r = http.session(wt, remote)
        r.still()
        if r.repo != bound["repo"]:
            raise http.Failure("identity-changed")
        if not r.branch(base):
            refuse(f"{base}, this task's base, isn't a branch on Bitbucket, so there's nothing to open a pull request into; "
                   f"nothing was pushed or sent. {stays}.")
        there = r.branch(br)
        opened = r.open_from(br)
    except http.Failure as e:
        refuse(said(e.category, "nothing was pushed or sent"), "held" if held_of(claim) else "refused")

    # 3. An uncertain step is reconciled first, by positive exact evidence only, before anything is sent:
    # its own operation id in the description of the one open pull request from the branch, into its
    # base, at the head that step was sent for (and, for ready, no longer a draft).
    d = claim.get("draft")
    if d and d["state"] == UNCERTAIN:
        hit = [p for p in opened if d["id"] in marks(p)]
        if len(hit) == 1 and hit[0]["base"] == base and heads(hit[0], d["head"]):
            save(lambda c: {**c, "draft": {**d, "state": CONFIRMED, "pr": record(r, hit[0]), "confirmed": now()}})
            d = claim["draft"]
        else:
            refuse(uncertain_words("draft", d, br, base), "held")
    rd = claim.get("ready")
    if rd and rd["state"] == UNCERTAIN:
        hit = [p for p in opened if p["number"] == (rd.get("pr") or {}).get("number") and rd["id"] in marks(p)]
        if len(hit) == 1 and hit[0]["base"] == base and heads(hit[0], rd["head"]) and not hit[0]["draft"]:
            save(lambda c: {**c, "ready": {**rd, "state": CONFIRMED, "confirmed": now()}})
            rd = claim["ready"]
        else:
            refuse(uncertain_words("ready", rd, br, base), "held")
    pr = (d or {}).get("pr") or saved
    others = [p for p in opened if not pr or p["number"] != pr["number"]]
    if others:
        p = others[0]
        foreign = marks(p) - ({d["id"]} if d else set())
        if pr or len(opened) > 1:
            refuse(f"{len(opened)} pull requests are open from {br} on Bitbucket (#{p['number']} among them), and a branch gets "
                   f"one; nothing was pushed or sent. Close the extra one on Bitbucket, then run ready again.")
        if p["base"] != base:
            refuse(f"A branch gets no second pull request: #{p['number']} is open from {br} into {p['base']}, not {base}; nothing "
                   f"was pushed or sent. {stays}: say why in your chat and end your turn.")
        if foreign:
            refuse(f"{NAME}'s pull request #{p['number']} from {br} was opened by another herdr-task publication (operation "
                   f"{sorted(foreign)[0]}), perhaps on another machine, and one never takes over another's; nothing was pushed or "
                   f"sent. {stays}: say why in your chat and end your turn.")
    if pr:
        mine = [p for p in opened if p["number"] == pr["number"]]
        if not mine:
            refuse(f"This task's pull request {pr['url']} isn't open from {br} into {base} on Bitbucket now (merged, declined or "
                   f"moved), and a branch gets no second one; nothing was pushed or sent. {stays}.")
        if mine[0]["base"] != base:
            refuse(f"This task's pull request {pr['url']} is into {mine[0]['base']} now, not {base}; nothing was pushed or sent. "
                   f"{stays}.")

    # 4. The push: only over what Bitbucket said the branch holds, on the route that was bound.
    if there != head:
        if http_git(wt, "rev-parse", "--verify", "--quiet", f"refs/heads/{br}")[1] != head:
            refuse(f"{br} moved here while ready ran; nothing was pushed or sent. Run ready again.")
        try:
            r.still()  # the last check before the push
        except http.Failure as e:
            refuse(said(e.category, "nothing was pushed or sent"))
        pushed = push(wt, url, br, head, there)
        if not pushed:
            how = "git couldn't say whether it reached Bitbucket" if pushed is None else "Bitbucket's branch doesn't hold it"
            refuse(f"git couldn't push {br} to {url}: {how}. No pull request was opened or changed. {stays}. git push works "
                   f"with this machine's own Git credentials, and they're the person's to repair: say why in your chat and end "
                   f"your turn.", "held" if held_of(claim) else "refused")
        save(lambda c: {**c, "pushed": {"head": head, "to": url, "at": now()}})
        changed.append("pushed")
        r.started = time.monotonic()  # the push is git's, bounded by itself; Bitbucket's budget starts again
    elif not (claim.get("pushed") or {}).get("head") == head:
        save(lambda c: {**c, "pushed": {"head": head, "to": url, "at": now(), "found": True}})

    # 5. The draft: kept (this task's own), adopted (one opened by hand at exactly this head, carrying no
    # operation id), or opened now under a new operation id saved as uncertain before it is sent.
    if pr and not d:
        save(lambda c: {**c, "draft": {"id": str(uuid.uuid4()), "state": CONFIRMED, "head": None, "pr": pr, "kept": "saved",
                                       "confirmed": now()}})
    elif not pr and opened:
        p = opened[0]
        if not heads(p, head):
            refuse(f"{NAME}'s pull request #{p['number']} from {br} is at {p['short'][:7]}, not {head[:7]}, which was just "
                   f"pushed; nothing else was sent. Run ready again once Bitbucket shows it.")
        pr = record(r, p)
        save(lambda c: {**c, "draft": {"id": str(uuid.uuid4()), "state": CONFIRMED, "head": head, "pr": pr, "kept": "adopted",
                                       "confirmed": now()}})
    elif not pr:
        title = f"{ref} {t['title']}"[:http.LIMITS["title"]]
        op = str(uuid.uuid4())
        body = described((t.get("prompt") or "").strip() or t["title"], op)
        try:
            if r.branch(br) != head:
                raise http.Failure("identity-changed")
            r.still()  # the last check before the claim and the write
        except http.Failure as e:
            refuse(said(e.category, "no pull request was opened"))
        if not r.can_send():
            refuse(said("not-sent", "no pull request was opened"))
        save(lambda c: {**c, "draft": {"id": op, "state": UNCERTAIN, "head": head, "sent": now()}})
        try:
            made = r.create(br, base, head, title, body)
        except http.Failure as e:
            made, why = None, e.category
        if made is None and why in ("not-sent", "write-refused"):
            save(lambda c: {**c, "draft": None, "refused": {"id": op, "why": why, "at": now()}})
            refuse(said(why, "no pull request was opened"))
        if made is None:
            try:  # one look, for positive evidence only: none found is no evidence of anything
                found = [p for p in r.open_from(br) if op in marks(p) and p["base"] == base and heads(p, head)]
            except http.Failure:
                found = []
            made = found[0] if len(found) == 1 else None
            if not made:
                refuse(uncertain_words("draft", claim["draft"], br, base), "uncertain")
        pr = record(r, made)
        save(lambda c: {**c, "draft": {**c["draft"], "state": CONFIRMED, "pr": pr, "confirmed": now()}})
        changed.append("draft")
    t["pr"] = {**(saved or {}), **pr}

    # 6. Ready for review: the pull request at exactly this head, its checks read in full, then draft off
    # with the summary, keeping its title, reviewers, destination and close_source_branch.
    try:
        v = http.read_pull_request(wt, remote, pr["number"], reader=r)
    except http.Failure as e:
        refuse(said(e.category, "it wasn't marked ready for review"))
    if (v["source"], v["base"], v["state"]) != (br, base, "OPEN"):
        refuse(f"{v['url']} isn't open from {br} into {base} now; it wasn't marked ready for review.")
    if v["head"] != head:
        refuse(f"{v['url']} is at {v['head'][:7]} on Bitbucket, not {head[:7]}; it wasn't marked ready for review. Run ready "
               "again once Bitbucket shows this commit.")
    op = str(uuid.uuid4())
    text = (summary or "").strip() or t["title"]
    if (t.get("details") or "").strip():
        text += "\n\n" + t["details"].strip()
    try:
        now_pr, kept = r.current(pr["number"])
        if (now_pr["source"], now_pr["base"], now_pr["state"]) != (br, base, "OPEN") or not heads(now_pr, head):
            raise http.Failure("identity-changed")
        if http_git(wt, "rev-parse", "--verify", "--quiet", f"refs/heads/{br}")[1] != head:
            raise http.Failure("identity-changed")
        r.still()  # the last check before the claim and the write
    except http.Failure as e:
        refuse(said(e.category, "it wasn't marked ready for review"))
    if not r.can_send():
        refuse(said("not-sent", "it wasn't marked ready for review"))
    save(lambda c: {**c, "ready": {"id": op, "state": UNCERTAIN, "head": head, "pr": pr, "sent": now()}})
    try:
        r.prepare(pr["number"], kept, described(text, op), br, base, head)
    except http.Failure as e:
        if e.category in ("not-sent", "write-refused"):
            save(lambda c: {**c, "ready": rd if rd and rd.get("state") == CONFIRMED else None,
                            "refused": {"id": op, "why": e.category, "at": now()}})
            refuse(said(e.category, "it wasn't marked ready for review"))
        refuse(uncertain_words("ready", claim["ready"], br, base), "uncertain")
    save(lambda c: {**c, "ready": {**c["ready"], "state": CONFIRMED, "confirmed": now()}})
    return t["pr"]


def http_git(wt, *args):
    out = http.git_out(wt, *args)
    return out is not None, out or "", None


def held_of(claim):
    return any((claim.get(n) or {}).get("state") == UNCERTAIN for n in ("draft", "ready"))


def finished(s, claim):
    """A claim another task of this folder held, for a branch no longer in play: its task is done or
    gone, and nothing it sent is uncertain. Only then may another task take it."""
    o = claim.get("owner") or {}
    if held_of(claim) or o.get("folder") != s.loc["folder"] or o.get("machine") != (machine_name() or socket.gethostname()):
        return False
    slug, _, n = str(o.get("task")).rpartition("#")
    if slug != s.slug:
        return False
    other = next((x for x in s.data["tasks"] if str(x.get("id")) == n), None)
    return other is None or other.get("state") == "done"


def said(category, nothing):
    """A failure category in herdr-task's words, with what didn't happen and what to do: only a credential
    is repaired (the person's), anything else is run again later."""
    words = http.WORDS.get(category, http.WORDS["unavailable"])
    if category in SIGN_IN or category == "write-refused":
        return f"{NAME}: {words}, so {nothing}. {ACCESS[0].upper() + ACCESS[1:]} is the person's to repair: say why in your chat and end your turn."
    return f"{NAME}: {words}, so {nothing}. Run ready again later; if it says the same, say why in your chat and end your turn."


def uncertain_words(stage, st, br, base):
    what = "opening the draft pull request" if stage == "draft" else "marking the pull request ready for review"
    return (f"{NAME} didn't answer whole for {what} from {br} into {base} (operation {st['id']}, at {st['head'][:7]}), so it may "
            f"or may not have happened. herdr-task never sends it again: ready records it once Bitbucket shows it "
            + ("(one open pull request from that branch into that base, at that commit, whose description ends with the line "
               if stage == "draft" else
               f"(pull request #{(st.get('pr') or {}).get('number')} open at that commit, no longer a draft, whose description "
               "ends with the line ")
            + f"`{MARK}: {st['id']}`). If it never happened, the person does it on Bitbucket that way; then run ready again. "
            "Say why in your chat and end your turn.")
