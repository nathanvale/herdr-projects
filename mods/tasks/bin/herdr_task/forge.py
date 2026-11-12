"""The forge: the one way commands, the tick and the Accept card reach a task's pull request,
whichever provider hosts it. Each provider's adapter owns its transport and how its answers read
(GitHub: github.py; Bitbucket Cloud: bitbucket.py for reads, publications.py for publishing). Local Git,
task state, approval and cleanup stay with their own owners.

A saved pull request that names no provider ({number, url, repo}: every record written so far) is
GitHub's. One naming a provider without an adapter here, or saved for a host other than the one its
adapter reaches, is refused before anything is sent to any host. One its forge answers for with
another host, repository, number or link is refused before anything is pushed, commented on,
recorded or merged: never read as someone else's.

A folder's repository for reads (repository()) is still GitHub's or none. Ready publishes to
publishing_repository(): GitHub's first, else the Bitbucket repository its remote binds (B2), where
publications.py pushes, opens the draft and prepares it under durable claims. A merge of a Bitbucket
pull request is refused (no_merge()), and so is a local or agent merge in a Bitbucket folder
(no_local_merge()): only a merge done on Bitbucket by hand finishes its task."""

from . import bitbucket, github, publications
from .base import Fail

GITHUB = "github"
BITBUCKET = bitbucket.PROVIDER
ADAPTERS = {GITHUB: github, BITBUCKET: bitbucket}
REFUSED = "REFUSED"


def provider_of(pr):
    """A saved pull request's (or a repository's) provider; unnamed is GitHub."""
    return (pr or {}).get("provider") or GITHUB


def adapter_of(pr):
    name = provider_of(pr)
    if name not in ADAPTERS:
        raise Fail(f"This task's pull request is on {name}, which herdr-task can't reach here; nothing was sent to it.")
    return ADAPTERS[name]


def mine(pr):
    return pr.get("url") or f"#{pr.get('number')} in {pr.get('repo')}"


def host_of(pr):
    """The host a saved pull request is on: its own, else its link's; None when it says neither."""
    named = pr.get("host") or github.link_host(pr.get("url"))
    return str(named).lower() if named else None


def route(pr):
    """The adapter that reaches a saved pull request, refused (Fail) before any call when it is
    another provider's or saved for another host than the one that adapter reaches."""
    a = adapter_of(pr)
    there = host_of(pr)
    if there and there != a.host():
        hint = f" If {there} is where it should go, set GH_HOST to {there}." if a is github else ""
        raise Fail(f"This task's pull request {mine(pr)} is on {there}, and herdr-task reaches {a.NAME} at {a.host()} here; "
                   f"nothing was sent to either.{hint}")
    return a


def name_of(pr):
    """The name of the forge a saved pull request is on, for the person (GitHub when it names none
    or one without an adapter here)."""
    return ADAPTERS.get(provider_of(pr), github).NAME


def repair_of(pr, why):
    """What the person does when that forge couldn't read it (why: its reason), as one sentence."""
    return bitbucket.repair(why) if provider_of(pr) == BITBUCKET else f"Repair {github.GH_ACCESS}, then try again."


def no_merge(task):
    """Why its forge isn't asked to merge the task's saved pull request at all, for the person; None
    when it is. Bitbucket's merge can't be held to the head that was accepted, so it is never sent."""
    pr = task.get("pr") or {}
    return bitbucket.merge_refusal(pr) if provider_of(pr) == BITBUCKET else None


def admit(task):
    """Refuses (Fail) a task whose saved pull request no adapter here reaches, before anything asks
    any host about it or its folder."""
    if task.get("pr"):
        route(task["pr"])


def refused(why):
    """A view that is none of the task's pull request: nothing reads it as merged, open or checked."""
    return {"state": REFUSED, "refused": why}


def mismatch(saved, seen, name):
    """Why the pull request the forge answered for isn't the saved one, or None when it is."""
    if not seen:
        return f"{name} didn't say which pull request it answered for; nothing was changed."
    same = (seen["provider"] == provider_of(saved) and seen["number"] == saved.get("number")
            and all(saved.get(k) in (None, seen[k]) for k in ("url", "repo"))
            and (host_of(saved) or seen["host"]) == seen["host"])
    if same:
        return None
    return f"{name} answered for {seen['url']}, not this task's pull request {mine(saved)}; nothing was changed."


# ---- the folder's repository ----------------------------------------------------------------

def repository(s, fresh=False):
    """The forge repository a folder's tasks publish to: {provider, repo, host}; None: they merge here.
    host: the one the forge itself places the folder on (gh resolves the remote, aliases included);
    None when it didn't say. As github.github(): asked again when fresh, and s.github_saved says
    whether it was a saved answer."""
    repo = github.github(s, fresh=True) if fresh else github.github(s)
    return {"provider": GITHUB, "repo": repo, "host": github.host_of(s)} if repo else None


def publishing_repository(s, fresh=False):
    """The repository Ready publishes a folder's tasks to: GitHub's (repository()), else the Bitbucket
    repository its remote binds (bitbucket.repository_of(), which refuses one written on bitbucket.org
    that doesn't bind); None: they merge here."""
    return repository(s, fresh) or bitbucket.repository_of(s.loc["folder"])


def no_local_merge(s, task):
    """Refuses (Fail) a merge here of a task whose folder merges through a pull request: GitHub's, or
    Bitbucket's, where nothing merges but the person on Bitbucket."""
    github.no_local_merge(s, task)
    bitbucket.no_local_merge(s, task)


def reach(where, nothing="nothing was pushed", then="run ready again"):
    """Refuses (Fail) a folder whose repository the forge places on another host than the one its
    adapter sends commands to, or on none it named: gh is sent `--repo owner/name` alone, so it goes
    to its default host, not necessarily the folder's. Refused, never skipped. The one owner of this
    check: publication, adoption, merging and the tick's merged read all call it, before any call
    about a pull request. nothing, then: what didn't happen, and what to do after setting GH_HOST."""
    w, there = adapter_of(where), where.get("host")
    if not there:
        raise Fail(f"{w.NAME} didn't say which host {where['repo']} is on, so its pull request can't be kept to {w.host()}; "
                   f"{nothing}. Try again; if it says the same, set GH_HOST to that repository's host.")
    if there != w.host():
        raise Fail(f"This folder's repository is on {there}, and herdr-task reaches {w.NAME} at {w.host()} here, so its pull "
                   f"request would go to the wrong host; {nothing}. Set GH_HOST to {there}, then {then}.")


def merge_reach(s, task):
    """reach() for merging the task's saved pull request, before anything reads it: the folder's
    repository as the forge places it now (a folder it no longer places refuses as one with no host).
    One no adapter here reaches is left to pr_read(), which refuses it without any call, and so is a
    Bitbucket one: its adapter binds the task's own checkout before anything is sent (bitbucket.pr_read())."""
    try:
        if route(task["pr"]) is not github:
            return
    except Fail:
        return
    where = repository(s) or {"provider": provider_of(task["pr"]), "repo": task["pr"].get("repo")}
    reach(where, "nothing was merged", "try again")


# ---- publishing -----------------------------------------------------------------------------

def pr_open(s, task, where, summary=None):
    """Publishes the task's branch as its pull request in `where`. A saved one is read first and kept
    only when its forge answers for exactly it: refused before any push, comment or new pull request
    when it is another provider's, host's or repository's, its forge doesn't answer (the adapter's
    own refusal), or answers for another pull request. A Bitbucket repository publishes through
    publications.publish(), which reads and claims it before any push."""
    saved, state = task.get("pr"), None
    reach(where)
    if saved:
        a = route(saved)
        if provider_of(saved) != provider_of(where) or saved.get("repo") not in (None, where["repo"]):
            raise Fail(f"This task's pull request {mine(saved)} isn't in {where['repo']}, this folder's repository; nothing was pushed.")
    if provider_of(where) == BITBUCKET:
        # Its own reads, claims and identity checks, before any push (publications.publish()).
        return publications.publish(s, task, where, summary)
    if saved:
        if saved.get("number"):
            known = {**saved, "repo": saved.get("repo") or where["repo"]}
            v, why = a.pr_read({**task, "pr": known})
            if not v or not v.get("state"):
                raise a.GhFailed(f"read pull request #{saved['number']}", why or "an answer it couldn't read")
            wrong = mismatch(known, a.pr_identity(v), a.NAME)
            if wrong:
                raise Fail(wrong)
            state = v["state"]
    return adapter_of(where).pr_open(s, task, where["repo"], summary, state)


def pr_adopt(task, where):
    """The open pull request for the task's branch in `where`, recorded when its own link is there;
    refused (reach()) before anything is asked when `where` is on another host."""
    reach(where, "nothing was adopted", "accept again")
    return adapter_of(where).pr_adopt(task, where["repo"])


def adopt_existing(s, task, given):
    """Records an existing pull request by hand (the adapter checks it is the task's), refused first
    when the one already saved is unreachable here, or another forge's than GitHub (whose adoption
    alone is here): nothing is read or recorded."""
    admit(task)
    if task.get("pr") and provider_of(task["pr"]) != GITHUB:
        raise Fail(f"This task already records {name_of(task['pr'])}'s pull request {mine(task['pr'])}, and a task keeps the one "
                   "it records; nothing was adopted.")
    # The folder's host, once gh has placed it (the adapter's own lookup, asked once), before any
    # call about the pull request.
    return github.adopt_existing(s, task, given, lambda s: reach(repository(s), "nothing was adopted", "adopt again"))


def pr_merged(task, where):
    return adapter_of(where).pr_merged(task, where["repo"])


def already_merged(s, task):
    """SHEP-59 (the adapter's already_merged()), with a saved pull request read only through
    pr_view(): refused (Fail) when it is unreachable or its forge answers for another one. Its pull
    request queries (the saved one's view, the merged list) go only when the folder's repository is
    on the host gh is sent to (reach()): otherwise none is merged, nothing is recorded or raised, and
    local Git alone (merged_here(), landed()) says whether its work is in its base. Ready then goes
    on to publication, which refuses on that host (pr_open()); the tick goes on to other tasks."""
    admit(task)

    def view(t):
        v = pr_view(t)
        if v and v.get("refused"):
            raise Fail(v["refused"])
        return v

    def reached(s):
        try:
            reach(repository(s), "nothing was recorded", "try again")  # the lookup already_merged() just made
        except Fail:
            return False
        return True
    return github.already_merged(s, task, view, reached)


# ---- the saved pull request -----------------------------------------------------------------

def pr_read(task):
    """The task's pull request as its forge reads it now, and why not: (view, None), or (None, the
    forge's reason). A refused view (and no reason) when it is unreachable here or the forge answered
    for another one: nothing is sent for one that is unreachable, or one its adapter refuses to read
    before sending anything (a Bitbucket checkout that doesn't bind it)."""
    saved = task["pr"]
    try:
        a = route(saved)
        v, why = a.pr_read(task)
    except Fail as e:
        return refused(str(e)), None
    if not v:
        return v, why
    wrong = mismatch(saved, a.pr_identity(v), a.NAME)
    return (refused(wrong), None) if wrong else (v, None)


def pr_view(task):
    """pr_read()'s view alone: None when the forge can't say."""
    return pr_read(task)[0]


def view_adapter(v):
    return ADAPTERS[v.get("provider") or GITHUB]


def pr_problem(v):
    """What keeps it from merging, for the person; None when nothing does."""
    return v["refused"] if v.get("refused") else view_adapter(v).pr_problem(v)


def pr_pending(v):
    return not v.get("refused") and view_adapter(v).pr_pending(v)


def pr_checks(v):
    """Its checks as facts ({failed, running, total}), or {refused: why}."""
    return {"refused": v["refused"]} if v.get("refused") else view_adapter(v).pr_checks(v)


def integrate(task, v, queue=False):
    """Merges the task's pull request on its forge at the head `v` read: (ok, why not). queue: its
    base merges through GitHub's merge queue (#742, #801, #802), so the request only queues it."""
    if v.get("refused"):
        return False, v["refused"]
    return adapter_of(task["pr"]).pr_merge(task["pr"], v, **({"queue": True} if queue else {}))
