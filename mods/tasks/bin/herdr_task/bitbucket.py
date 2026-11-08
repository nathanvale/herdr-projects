"""Bitbucket Cloud's forge adapter (forge.py reaches it): a task's saved, provider-qualified pull
request and the complete checks of exactly its head (B1), and which Bitbucket repository a folder
publishes to (B2; publications.py publishes), through bitbucket_http.py on this machine's own Git
credentials. Local Git, task state, approval and cleanup stay with their owners.

A saved Bitbucket pull request is {provider: "bitbucket", host: "bitbucket.org", repo, number, url}.
It is read only from the task's own checkout, whose remote must bind that same repository: one saved
for another repository, or a checkout whose remote binds none, refuses before anything is sent.

Merging one is refused, as Bitbucket's merge can't be held to the exact head that was accepted;
nothing merges it another way (no GitHub, local or agent merge), and `adopt` stays GitHub's."""

import os
import re

from .base import Fail
from . import bitbucket_http as http

NAME = "Bitbucket"
PROVIDER = "bitbucket"
ACCESS = "this machine's Git credential helper for bitbucket.org (a REST-capable API or access token)"
MERGE_REFUSED = ("Bitbucket's merge can't be tied to exactly the commit that was accepted, so herdr-task sent no merge "
                 "there and doesn't merge it any other way. Merge pull request #{n} on Bitbucket yourself: the tick then "
                 "finishes the task, and removes its branch only if what merged is this branch's commit.")
SIGN_IN = {"missing-credentials", "permission-refused"}
NO_LOCAL = ("{ref}'s folder is on Bitbucket ({repo}), where herdr-task merges nothing: not there, not here and not by an "
            "agent, as Bitbucket's merge can't be tied to exactly the commit that was accepted. Run ready to publish it, then "
            "merge its pull request on Bitbucket yourself. Nothing was merged.")


def host():
    return http.HOST


class Why(str):
    """Why a pull request couldn't be read, in words, with its category (bitbucket_http.WORDS)."""

    def __new__(cls, category, words):
        w = super().__new__(cls, words)
        w.category = category
        return w


def remote_of(folder):
    """The remote a checkout's branch goes to: origin, else its first."""
    out = http.git_out(folder, "remote") or ""
    names = out.split()
    return "origin" if "origin" in names else (names[0] if names else None)


def on_bitbucket(url):
    """A remote URL on bitbucket.org itself, HTTPS or SSH."""
    m = re.match(r"(?:[a-z][a-z0-9+.-]*://)?(?:[^@/]+@)?([^/:]+)", url.strip(), re.I)
    return bool(m) and m.group(1).lower() == http.HOST


def repository_of(folder):
    """The Bitbucket repository a folder publishes to, {provider, repo, host}, when its remote (origin,
    else its first) is written on bitbucket.org; None when it isn't. One written there whose views don't
    all bind one repository refuses (Fail): it never merges here instead, and nothing is sent."""
    remote = remote_of(folder)
    written = (http.git_out(folder, "config", "--get-all", f"remote.{remote}.url") or "") if remote else ""
    if not any(on_bitbucket(u) for u in written.splitlines()):
        return None
    bound = http.binding(http.origins(folder, remote))
    if not bound:
        raise Fail(f"This folder's remote {remote} is on Bitbucket, and {http.WORDS['not-bitbucket']}; nothing was pushed or "
                   "sent and nothing merges here. The task stays as it was.")
    return {"provider": PROVIDER, "repo": bound["repo"], "host": http.HOST}


def no_local_merge(s, task):
    """Refuses (Fail) a merge here, or by an agent, of a task in a folder on Bitbucket."""
    where = repository_of(s.loc["folder"])
    if where:
        raise Fail(NO_LOCAL.format(ref=s.ref(task), repo=where["repo"]))


def pr_read(task):
    """The task's saved pull request as Bitbucket reads it now, and why not: (view, None) or (None, Why).
    Refuses (Fail) before anything is sent when its checkout isn't here or its remote doesn't bind
    the saved repository."""
    pr, wt = task["pr"], task.get("worktree")
    mine = pr.get("url") or f"#{pr.get('number')} in {pr.get('repo')}"
    if not (wt and os.path.isdir(wt)):
        raise Fail(f"This task's pull request {mine} is read through its own checkout, which isn't here; nothing was sent.")
    remote = remote_of(wt)
    bound = http.binding(http.origins(wt, remote)) if remote else None
    if not bound:
        raise Fail(f"This task's pull request {mine} is on Bitbucket, and {http.WORDS['not-bitbucket']}; nothing was sent.")
    if not isinstance(pr.get("repo"), str) or bound["repo"] != pr["repo"] or type(pr.get("number")) is not int:
        raise Fail(f"This task's pull request {mine} isn't in {bound['repo']}, the Bitbucket repository this folder's remote "
                   f"names; nothing was sent.")
    try:
        r = http.read_pull_request(wt, remote, pr["number"])
    except http.Failure as e:
        return None, Why(e.category, http.WORDS.get(e.category, http.WORDS["unavailable"]))
    except (TypeError, KeyError, AttributeError, IndexError, ValueError, RecursionError):
        return None, Why("malformed-response", http.WORDS["malformed-response"])
    # The task's own candidate: its branch into its base. Another source or destination is never read
    # as this task's, so nothing finishes on it and no card counts its checks (as GitHub's adoption).
    branch, base = task.get("branch"), task.get("base") or "main"
    if r["source"] != branch or r["base"] != base:
        raise Fail(f"Bitbucket's pull request {r['url']} is from {r['source']} into {r['base']}, and this task is {branch} "
                   f"into {base}, so it isn't read as this task's; nothing was changed.")
    view = {"provider": PROVIDER, "host": http.HOST, "repo": r["repo"], "number": r["number"], "url": r["url"],
            "state": r["state"], "draft": r["draft"], "title": r["title"], "headRefOid": r["head"],
            "headRefName": r["source"], "baseRefName": r["base"], "checks": {"head": r["head"], "complete": True, "items": r["checks"]}}
    return view, None


def pr_identity(v):
    """Which pull request Bitbucket answered for: {provider, host, repo, number, url}; None without one."""
    if v.get("provider") != PROVIDER or not all(v.get(k) for k in ("repo", "number", "url")):
        return None
    return {"provider": PROVIDER, "host": http.HOST, "repo": v["repo"], "number": v["number"], "url": v["url"]}


def pr_checks(v):
    """Its head's checks as facts: {failed: [names], running, total, head, result}. result keeps every
    complete read apart: empty (none reported yet), pending, failed or passed. A read that wasn't
    complete never becomes a view (pr_read() says why instead)."""
    c = v.get("checks") or {}
    items = c.get("items") if c.get("complete") is True else None
    if items is None:
        return {"refused": "Bitbucket's checks weren't read in full, so none of them count."}
    failed = [i["name"] for i in items if i["state"] == "fail"]
    running = sum(1 for i in items if i["state"] == "pending")
    result = "failed" if failed else "pending" if running else "passed" if items else "empty"
    return {"failed": failed, "running": running, "total": len(items), "head": c.get("head"), "result": result}


def pr_problem(v):
    """What keeps it from merging, for the person; None when nothing does (in the GitHub adapter's words,
    which the tick clears by)."""
    if v.get("state") == "CLOSED":
        return "The pull request was closed."
    c = pr_checks(v)
    if c.get("refused"):
        return c["refused"]
    if c["failed"]:
        bad = c["failed"]
        return "Checks failing: " + ", ".join(bad[:3]) + (" and more." if len(bad) > 3 else ".")
    return None


def pr_pending(v):
    """Still waiting on its checks: some are running, or none were reported at all (empty is never green)."""
    c = pr_checks(v)
    return not c.get("refused") and (c["running"] > 0 or c["total"] == 0)


def repair(why):
    """What the person does when a read failed, by why (Why.category): only a credential needs repairing."""
    if getattr(why, "category", None) in SIGN_IN:
        return f"Repair {ACCESS}, then try again."
    return "Try again later; merging it is done on Bitbucket itself either way."


def merge_refusal(pr):
    return MERGE_REFUSED.format(n=pr.get("number"))


def pr_merge(pr, v):
    """Never sent: (False, why)."""
    return False, merge_refusal(pr)

