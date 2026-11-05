"""The forge: the one way commands, the tick and the Accept card reach a task's pull request,
whichever provider hosts it. Each provider's adapter owns its transport and how its answers read
(GitHub: github.py). Local Git, task state, approval and cleanup stay with their own owners.

A saved pull request that names no provider ({number, url, repo}: every record written so far) is
GitHub's. One naming a provider without an adapter here, or one its forge answers for with another
host, repository, number or link, is refused before anything is sent or changed: never read,
commented on or merged as someone else's."""

from . import github
from .base import Fail

GITHUB = "github"
ADAPTERS = {GITHUB: github}
REFUSED = "REFUSED"


def provider_of(pr):
    """A saved pull request's (or a repository's) provider; unnamed is GitHub."""
    return (pr or {}).get("provider") or GITHUB


def adapter_of(pr):
    name = provider_of(pr)
    if name not in ADAPTERS:
        raise Fail(f"This task's pull request is on {name}, which herdr-task can't reach here; nothing was sent to it.")
    return ADAPTERS[name]


def refused(why):
    """A view that is none of the task's pull request: nothing reads it as merged, open or checked."""
    return {"state": REFUSED, "refused": why}


def mismatch(saved, seen, name):
    """Why the pull request the forge answered for isn't the saved one, or None when it is."""
    if not seen:
        return f"{name} didn't say which pull request it answered for; nothing was changed."
    same = (seen["provider"] == provider_of(saved) and seen["number"] == saved.get("number")
            and all(saved.get(k) in (None, seen[k]) for k in ("url", "repo"))
            and str(saved.get("host") or seen["host"]).lower() == seen["host"])
    if same:
        return None
    mine = saved.get("url") or f"#{saved.get('number')} in {saved.get('repo')}"
    return f"{name} answered for {seen['url']}, not this task's pull request {mine}; nothing was changed."


# ---- the repository and publishing ----------------------------------------------------------

def repository(s):
    """The forge repository a folder's tasks publish to: {provider, repo}; None: they merge here."""
    repo = github.github(s)
    return {"provider": GITHUB, "repo": repo} if repo else None


def pr_open(s, task, where, summary=None):
    """Publishes the task's branch as its pull request in `where`. A saved one is read first and kept
    only when its forge answers for exactly it; refused before any push or comment when it is another
    provider's or repository's, its forge doesn't answer, or answers for another pull request (one
    saved for another host never reaches this one's)."""
    saved, current = task.get("pr"), None
    if saved:
        mine = saved.get("url") or f"#{saved.get('number')} in {saved.get('repo')}"
        if provider_of(saved) != provider_of(where) or saved.get("repo") not in (None, where["repo"]):
            raise Fail(f"This task's pull request {mine} isn't in {where['repo']}, this folder's repository; nothing was pushed.")
    if saved and saved.get("number"):
        a, known = adapter_of(saved), {**saved, "repo": saved.get("repo") or where["repo"]}
        current = a.pr_view({**task, "pr": known})
        if not current:
            raise Fail(f"{a.NAME} didn't answer for this task's pull request {mine}; nothing was pushed.")
        why = mismatch(known, a.pr_identity(current), a.NAME)
        if why:
            raise Fail(why)
    return adapter_of(where).pr_open(s, task, where["repo"], summary, current)


def pr_adopt(task, where):
    return adapter_of(where).pr_adopt(task, where["repo"])


# ---- the saved pull request -----------------------------------------------------------------

def pr_view(task):
    """The task's pull request as its forge reads it now; None when the forge didn't answer; a
    refused view when it is another provider's or the forge answered for another one."""
    saved = task["pr"]
    try:
        a = adapter_of(saved)
    except Fail as e:
        return refused(str(e))
    v = a.pr_view(task)
    if not v:
        return v
    why = mismatch(saved, a.pr_identity(v), a.NAME)
    return refused(why) if why else v


def view_adapter(v):
    return ADAPTERS[v.get("provider") or GITHUB]


def pr_problem(v):
    """What keeps it from merging, for the person; None when nothing does."""
    return v["refused"] if v.get("refused") else view_adapter(v).pr_problem(v)


def pr_pending(v):
    return not v.get("refused") and view_adapter(v).pr_pending(v)


def pr_is_merged(v):
    return not v.get("refused") and view_adapter(v).pr_is_merged(v)


def pr_merge_commit(v):
    return None if v.get("refused") else view_adapter(v).pr_merge_commit(v)


def pr_checks(v):
    """Its checks as facts ({failed, running, total}), or {refused: why}."""
    return {"refused": v["refused"]} if v.get("refused") else view_adapter(v).pr_checks(v)


def integrate(task, v):
    """Merges the task's pull request on its forge at the head `v` read: (ok, why not)."""
    if v.get("refused"):
        return False, v["refused"]
    return adapter_of(task["pr"]).pr_merge(task["pr"], v)
