"""GitHub and merging: pull requests, checks, and finishing a merged task."""

import json
import os
import re
from urllib.parse import quote

from .base import Fail, GH, git, now, run, STORE
from .agents import agent_running, live_agents


# ---- GitHub ---------------------------------------------------------------------------------

def gh(*args, cwd=None):
    # gh not installed (or not on this caller's PATH, as a background service's): it doesn't work here, said plainly
    try:
        r = run([GH, *args], cwd=cwd or STORE)
    except OSError:
        return False, "", "gh isn't installed here (GitHub CLI)"
    return r.returncode == 0, r.stdout.strip(), (r.stderr or r.stdout).strip()


def gh_problem(doing, err):
    """gh couldn't answer, for the person: gh's own access, never git's (push_problem())."""
    return (f"gh couldn't {doing} ({' '.join(str(err).split())}). The task stays as it was and nothing merged here. "
            "Repair gh's own access (gh auth status; HERDR_TASK_GH names the gh command to run), then try again.")


def push_problem(branch, remote, err):
    """git couldn't push, for the person: git's own access to the remote, which gh's sign-in doesn't give it."""
    return (f"git couldn't push {branch} to {remote} ({' '.join(str(err).split())}). The task stays as it was. This is git's "
            "own access to that remote, apart from gh's sign-in: repair the remote's credentials, then try again. "
            "A branch already on GitHub at this commit needs no push.")


GITHUB_URL = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/]+@)?(?:ssh\.)?github\.com[:/]", re.I)


def github_remote(main):
    """A remote's configured URL says this repo lives on GitHub. Read from git, so it holds while gh
    can't answer. A host only gh can place (GitHub Enterprise, an ssh alias) shows once gh has."""
    ok, out, _ = git(main, "config", "--get-regexp", r"^remote\..*\.url$")
    return ok and any(GITHUB_URL.match(line.split(None, 1)[-1]) for line in out.splitlines())


def github(s):
    """The repo on GitHub ("owner/name"); asked again after an hour. None: it has no GitHub remote,
    so tasks merge locally. One that has refuses (Fail) while gh can't answer, also when gh isn't
    installed or isn't on this caller's PATH (a background service's): a failed answer is never
    saved and never becomes a local merge. An earlier saved None doesn't count against such a remote."""
    if s.loc["kind"] != "repo":
        return None
    g = s.data.get("github") or {}
    fresh = g and now() - g.get("at", 0) < 3600000
    if fresh and g.get("repo"):
        return g["repo"]
    known = bool(g.get("repo")) or github_remote(s.loc["folder"])
    if fresh and not known:
        return None
    ok, out, err = gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner", cwd=s.loc["folder"])
    if known and not (ok and out):
        raise Fail(gh_problem("say which GitHub repository this folder is", err or "no answer"))
    s.data["github"] = {"repo": out if ok and out else None, "at": now()}
    s.dirty = True
    return s.data["github"]["repo"]


def no_local_merge(s, task):
    """Refuses a local merge of a task in a repo on GitHub (Fail): there it goes through its pull
    request, and with no answer from gh (github()) nobody can say none exists."""
    if github(s):
        raise Fail(f"{s.ref(task)} has no pull request recorded, and this repo merges through one. Run ready to open it, "
                   f"or `herdr-task adopt {s.ref(task)} --pr <number>` to record the one that exists.")


def remote_of(main):
    names = git(main, "remote")[1].split()
    return "origin" if "origin" in names else (names[0] if names else "origin")


def publish(s, task, repo):
    """The task's branch on its remote: pushed, unless GitHub already holds exactly its tip. That is
    asked of gh, so a published branch needs no git credentials. No such branch there is an answer
    (it's pushed); no answer refuses (Fail), never read as published or as not."""
    wt, br = task["worktree"], task["branch"]
    ok, tip, err = git(wt, "rev-parse", "--verify", br)
    if not ok or not tip:
        raise Fail(f"Couldn't read {br} here: {err}")
    ok, there, err = gh("api", f"repos/{repo}/git/ref/heads/{quote(br, safe='/')}", "--jq", ".object.sha")
    if not ok and "HTTP 404" not in err:
        raise Fail(gh_problem(f"read {br} on GitHub", err))
    if ok and not there:
        raise Fail(gh_problem(f"read {br} on GitHub", "no answer"))
    if ok and there == tip:
        return
    remote = remote_of(s.loc["folder"])
    ok, _, err = git(wt, "push", "--force-with-lease", "-u", remote, br)
    if not ok:
        raise Fail(push_problem(br, remote, err))


def pr_open(s, task, repo, summary=None):
    """Publishes the task's branch and opens its pull request (or keeps the open one, also one
    opened by hand or by its agent for the branch: SHEP-13's "already exists"). Refuses (Fail) when
    gh or git can't: a saved pull request gh can't read is never replaced by a new one, and one
    adopted (adopt_existing()) is never replaced at all."""
    br, pr = task["branch"], task.get("pr") or {}
    state = None
    if pr.get("number"):
        ok, state, err = gh("pr", "view", str(pr["number"]), "--repo", repo, "--json", "state", "-q", ".state")
        if not ok or not state:
            raise Fail(gh_problem(f"read pull request #{pr['number']}", err or "no answer"))
        if state != "OPEN" and pr.get("adopted"):
            raise Fail(f"Pull request #{pr['number']}, adopted for {s.ref(task)}, is {state.lower()}, and adoption never opens "
                       "another. Reopen it on GitHub, then run ready again.")
    publish(s, task, repo)
    if state == "OPEN":
        if summary:
            gh("pr", "comment", str(pr["number"]), "--repo", repo, "--body", summary)
        return pr
    if pr_adopt(task, repo):
        if summary:
            gh("pr", "comment", str(task["pr"]["number"]), "--repo", repo, "--body", summary)
        return task["pr"]
    body = (task.get("prompt") or "").strip() or task["title"]
    if summary:
        body += "\n\n## Summary\n\n" + summary.strip()
    if (task.get("details") or "").strip():
        body += "\n\n## Details\n\n" + task["details"].strip()
    ok, out, err = gh("pr", "create", "--repo", repo, "--head", br, "--base", task.get("base") or "main",
                      "--title", f"{s.ref(task)} {task['title']}", "--body", body)
    if not ok or not out:
        raise Fail(f"Couldn't open a pull request: {err}" + (
            f" When it targets another branch, `herdr-task adopt {s.ref(task)} --pr <number>` records it." if "already exists" in err else ""))
    url = out.split()[-1]
    task["pr"] = {"number": int(url.rstrip("/").split("/")[-1]), "url": url, "repo": repo}
    return task["pr"]


def pr_adopt(task, repo):
    """The open pull request for the task's branch, opened by hand or by its agent, recorded on the
    task; None when there is none (SHEP-13: ready failed with "already exists"). Only one from this
    repo (never a fork's branch of the same name), into the task's base, at the branch's tip here."""
    ok, out, err = gh("pr", "list", "--repo", repo, "--head", task["branch"], "--state", "open",
                      "--json", "number,url,isCrossRepository,baseRefName,headRefOid")
    if not ok:
        raise Fail(gh_problem(f"list the pull requests for {task['branch']}", err))
    tip_ok, tip, _ = git(task["worktree"], "rev-parse", task["branch"])
    try:
        found = next((p for p in json.loads(out) if not p.get("isCrossRepository")
                      and p.get("baseRefName") == (task.get("base") or "main")
                      and tip_ok and tip and p.get("headRefOid") == tip), None) if out else None
    except (ValueError, TypeError, AttributeError):
        raise Fail(gh_problem(f"list the pull requests for {task['branch']}", "an answer it couldn't read"))
    if found:
        task["pr"] = {"number": found["number"], "url": found["url"], "repo": repo}
    return task.get("pr") if found else None


PR_LINK = re.compile(r"https://[^/]+/([^/]+/[^/]+)/pull/([0-9]+)/?")
OID = re.compile(r"[0-9a-f]{40,64}")


def adopt_existing(s, task, given):
    """Records a pull request that already exists on a started task, by hand (herdr-task adopt): its
    number, or its link. True: recorded. False: it already was, and nothing changed. Refuses (Fail)
    with what to do, leaving the task as it was, unless it is this repo's own open pull request for
    the task's branch, at exactly its tip, and its base is proved from commits (below). On success
    the task's base becomes the pull request's, the old one kept in base_history, and it merges only
    on the person's Accept. Never creates a pull request, pushes, fetches or merges.

    The proof: the task's start commit is the one and only merge base of the tip and the pull
    request's base commit. So the base holds everything the task started from and none of the
    task's own work: the pull request carries exactly the task's commits, whatever the two branches
    are called. --all: two merge bases prove nothing. A branch that has since taken in that base's
    commits refuses too, stricter than it need be and simple to check."""
    ref, main, br, start = s.ref(task), s.loc["folder"], task.get("branch"), task.get("start")
    if task.get("mode") != "worktree" or task.get("state") not in ("running", "ready") or not (task.get("worktree") and br and start):
        raise Fail(f"{ref} isn't a started worktree task ({task.get('state')}): adoption is for one with its branch and start "
                   "commit recorded. Start it, or reopen it.")
    repo = github(s)
    if not repo:
        raise Fail(f"{main} has no GitHub remote, so there is no pull request to adopt.")
    link = PR_LINK.fullmatch(given.strip())
    word = link.group(2) if link else given.strip().lstrip("#")
    if not word.isdigit():
        raise Fail(f"{given!r} isn't a pull request: give its number or its link.")
    number = int(word)
    if link and link.group(1).lower() != repo.lower():
        raise Fail(f"{given} is in {link.group(1)}, and this folder's repository is {repo}. Give a pull request of {repo}.")
    have = task.get("pr") or {}
    if have.get("number"):
        if have["number"] == number and str(have.get("repo")).lower() == repo.lower():
            return False
        raise Fail(f"{ref} already records pull request #{have['number']} of {have.get('repo')}, and a task keeps the one it "
                   f"records. Carry on with that one, or use a new task for #{number}.")
    ok, out, err = gh("pr", "view", str(number), "--repo", repo, "--json",
                      "number,url,state,isCrossRepository,headRefName,headRefOid,baseRefName,baseRefOid")
    if not ok:
        raise Fail(gh_problem(f"read pull request #{number} of {repo}", err))
    try:
        p = json.loads(out)
        answered = PR_LINK.fullmatch(p["url"])
        base, base_oid, state = p["baseRefName"], p["baseRefOid"], p["state"]
        cross, head, head_oid = p["isCrossRepository"], p["headRefName"], p["headRefOid"]
    except (ValueError, TypeError, KeyError):
        raise Fail(gh_problem(f"read pull request #{number} of {repo}", "an answer it couldn't read"))
    base_oid = str(base_oid or "")
    if not answered or answered.group(1).lower() != repo.lower() or int(answered.group(2)) != number:
        raise Fail(f"GitHub answered #{number} with {p['url']}, not a pull request of {repo}. Check the repository's name and "
                   "the number, then adopt again.")
    if cross is not False:
        raise Fail(f"Pull request #{number} comes from another repository (a fork). Adopt only one whose branch is in {repo}.")
    if head != br:
        raise Fail(f"Pull request #{number} is for branch {head}, and {ref} works on {br}. Adopt the one for {br}.")
    if state != "OPEN":
        raise Fail(f"Pull request #{number} is {str(state).lower()}, not open. Reopen it on GitHub, then adopt again.")
    ok, tip, _ = git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{br}")
    if not ok or not tip:
        raise Fail(f"Branch {br} isn't here to compare. Restore it, then adopt again.")
    if head_oid != tip:
        raise Fail(f"Pull request #{number} is at {str(head_oid)[:7]}, and {br} is at {tip[:7]} here. Bring them to the same "
                   "commit, then adopt again.")
    if tip == start:
        raise Fail(f"{br} has no commits of its own past its start, so there is nothing for #{number} to carry. Commit the "
                   "task's work first.")
    if not OID.fullmatch(base_oid) or not git(main, "cat-file", "-e", f"{base_oid}^{{commit}}")[0]:
        raise Fail(f"The base of #{number} ({base} at {base_oid[:7] or 'no commit'}) isn't here, so it can't be proved to match "
                   f"where {ref} started. Run `git fetch {remote_of(main)} {base}` in {main} (update gh if it gave no commit), "
                   "then adopt again.")
    ok, bases, _ = git(main, "merge-base", "--all", tip, base_oid)
    if not ok or bases.split() != [start]:
        met = ", ".join(b[:7] for b in bases.split()) or "nowhere"
        raise Fail(f"Can't prove #{number}'s base {base} matches {ref}: the task started at {start[:7]}, and its tip meets "
                   f"{base_oid[:7]} at {met}, so the pull request wouldn't carry exactly the task's work. Retarget it or rebase "
                   "the branch so they meet at the start, or leave it unadopted.")
    task["pr"] = {"number": number, "url": p["url"], "repo": repo, "adopted": now()}
    if task.get("base") != base:
        task.setdefault("base_history", []).append({"base": task.get("base"), "at": now(), "pr": number})
        task["base"], task["base_set"], task["base_by"] = base, True, "pull-request"
    # Adoption decides no merge: a merge the tick would start, or ready's old complaint, goes with it.
    task.pop("auto_merge", None)
    if (task.get("attention") or "").startswith(("Couldn't open a pull request", "Couldn't push")):
        task.pop("attention")
    s.dirty = True
    return True


BAD = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
PENDING = {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING", "REQUESTED", "EXPECTED"}


def pr_view(task):
    pr = task["pr"]
    ok, out, _ = gh("pr", "view", str(pr["number"]), "--repo", pr["repo"], "--json", "state,mergeable,headRefOid,statusCheckRollup,mergeCommit")
    try:
        return json.loads(out) if ok else None
    except ValueError:
        return None


def pr_problem(v):
    """What keeps a pull request from merging, for the person; None when nothing does."""
    if v.get("state") == "CLOSED":
        return "The pull request was closed."
    if v.get("mergeable") == "CONFLICTING":
        return "It conflicts with the base branch."
    checks = v.get("statusCheckRollup") or []
    bad = [c.get("name") or c.get("context") or "a check" for c in checks
           if (c.get("conclusion") or c.get("state") or "").upper() in BAD]
    if bad:
        return "Checks failing: " + ", ".join(bad[:3]) + (" and more." if len(bad) > 3 else ".")
    return None


def pr_pending(v):
    return any((c.get("status") or c.get("state") or "").upper() in PENDING and not (c.get("conclusion") or "")
               for c in v.get("statusCheckRollup") or [])


def update_main(s, task):
    """After a merge on GitHub: the base branch here catches up when it's checked out and clean."""
    main, base = s.loc["folder"], task.get("base") or "main"
    remote = remote_of(main)
    git(main, "fetch", remote, base)
    ok, cur, _ = git(main, "symbolic-ref", "--short", "HEAD")
    if ok and cur == base and not git(main, "status", "--porcelain", "--untracked-files=no")[1]:
        git(main, "merge", "--ff-only", f"{remote}/{base}")
    elif not (ok and cur == base):
        # A base not checked out here (a task's own --base): its branch fast-forwards (git refuses
        # anything else, and a branch checked out in another worktree).
        git(main, "fetch", remote, f"{base}:{base}")


MAIN_WATCH_MS = 3 * 3600000  # how long main is watched after a task merges through its pull request


def watch_main(s, task, sha=None):
    """A task just merged through its pull request: its base branch on GitHub is watched for a few
    hours (ghnews.main_pass), so the Assistant hears once if it goes red (as Shepherdr)."""
    if not task.get("pr"):
        return
    base = task.get("base") or "main"
    w = s.data.setdefault("main_watch", {}).setdefault(base, {})
    w.update(repo=task["pr"]["repo"], until=now() + MAIN_WATCH_MS, space=task.get("space") or w.get("space"))
    merged = [m for m in w.get("merged") or [] if now() - (m.get("at") or 0) < 24 * 3600000]
    merged.append({"ref": s.ref(task), "title": task["title"], "pr": task["pr"]["number"], "at": now(), **({"sha": sha} if sha else {})})
    w["merged"] = merged[-30:]
    s.dirty = True


def base_commit(main, base):
    """A task's base as it can be read here: its branch, else its remote's copy (a target this clone
    never checked out, as an adopted pull request's can be)."""
    return base if git(main, "rev-parse", "--verify", "--quiet", base)[0] else f"refs/remotes/{remote_of(main)}/{base}"


def merged_here(s, task):
    """Its own work is in the base branch here (merged by anyone, without a PR): the newest commit
    its branch held that the base didn't (own_work()) is in the base now. A branch that only caught
    up with its base (SHEP-23: `git merge --ff-only main` mid-work, its tip the base's) has no work
    of its own, so it never counts as merged."""
    own, main = own_work(s, task), s.loc["folder"]
    return bool(own) and git(main, "merge-base", "--is-ancestor", own, base_commit(main, task["base"]))[0]


def own_work(s, task):
    """The newest commit of the task's own seen on its branch, or None: its tip whenever the branch
    holds commits its base branch doesn't, here or on its remote (kept on the task as "own"; the
    tick and ready look), else the last one kept."""
    main, br, base, start = s.loc["folder"], task.get("branch"), task.get("base"), task.get("start")
    if not (br and base and start):
        return None
    ok, tip, _ = git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{br}")
    tip = tip if ok and tip else task.get("head")
    if tip and tip != start and tip != task.get("own") and not any(
            git(main, "merge-base", "--is-ancestor", tip, ref)[0] for ref in (base, f"refs/remotes/{remote_of(main)}/{base}")):
        task["own"] = tip
        s.dirty = True
    return task.get("own")


def finish(s, task, even_if_busy=False):
    """Done, its branch merged: removes the worktree and branch when nothing is left uncommitted
    there and (unless the person merged from Herdr) no agent still works in it."""
    task["state"], task["done_at"] = "done", now()
    for k in ("attention", "merge_requested", "queue", "queued_at"):
        task.pop(k, None)
    s.dirty = True
    wt, br, main = task.get("worktree"), task.get("branch"), s.loc["folder"]
    if not wt or (not even_if_busy and any(agent_running(k) for k in live_agents(s.key(task)))):
        return
    if os.path.isdir(wt):
        ok, out, _ = git(wt, "status", "--porcelain", "--untracked-files=no")
        if not ok or out or not git(main, "worktree", "remove", "--force", wt)[0]:
            return
    if br:
        git(main, "branch", "-D", br)
