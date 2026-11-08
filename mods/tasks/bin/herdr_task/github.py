"""GitHub and merging: pull requests, checks, and finishing a merged task."""

import hashlib
import json
import os
import re
import shutil
from urllib.parse import quote

from .base import Fail, GH, git, now, run, STORE
from .agents import agent_running, live_agents


# ---- GitHub ---------------------------------------------------------------------------------

GH_MISSING = "gh isn't installed here (GitHub CLI)"
# gh's own words for a repo whose remotes it can't place on GitHub: the one failure that is a real no.
NOT_GITHUB = "none of the git remotes configured for this repository point to a known GitHub host"


def gh(*args, cwd=None):
    # gh not installed (or not on this caller's PATH, as a background service's) is GH_MISSING, and
    # means only that: the default gh, with nothing of that name on PATH. FileNotFoundError alone
    # doesn't say so, as a folder that's gone and a wrapper's missing interpreter raise it too. Any
    # other that can't run, HERDR_TASK_GH above all, is gh failing: github() never takes that for a no.
    try:
        r = run([GH, *args], cwd=cwd or STORE)
    except OSError as e:
        missing = isinstance(e, FileNotFoundError) and not os.environ.get("HERDR_TASK_GH") and not shutil.which(GH)
        return False, "", GH_MISSING if missing else f"{GH} can't run here: {e}"
    return r.returncode == 0, r.stdout.strip(), (r.stderr or r.stdout).strip()


HANDOFF = "say why in your chat and end your turn."
GH_ACCESS = "gh's own access (gh auth status; HERDR_TASK_GH names the gh command to run)"
STAYS = "The task stays as it was"
NO_PR = "Couldn't open a pull request"
NO_PUSH = "git couldn't push"
SECOND_PR = "A branch gets no second pull request"
NO_ASK = "Couldn't ask for the merge"
# How attention left by publishing starts (a reviewer's refused pass keeps its words, whatever
# cmd_review() does to STAYS, and finalize() keeps a failed ask) when adoption answers it: the pull
# request exists, GitHub holds this tip, its base is proved and it merges on Accept. "Couldn't push"
# is an older version's words. Never gh's failures: gh answering adopt repairs no one else's access.
ADOPTION_ANSWERS = (NO_PR, NO_PUSH, "Couldn't push", SECOND_PR, NO_ASK)


def plain(err):
    """gh's or git's own words on one line, as output and a saved task hold them: a URL's user and
    password go, as a remote URL can carry a token."""
    return re.sub(r"\b([a-z][a-z0-9+.-]*://)[^/\s]*@", r"\1", " ".join(str(err).split()), flags=re.I)


class Caused(Fail):
    """A refusal gh or git caused, whose access differs: --json says which (cause)."""

    def __init__(self, cause, words):
        super().__init__(words)
        self.cause = cause


class GhFailed(Caused):
    """gh couldn't answer: gh's own access, never git's (push_problem()). Worded for the agent that
    ran ready, whose next step is to hand it over; .person is for whoever runs Accept, merge or adopt."""

    def __init__(self, doing, err):
        said = f"gh couldn't {doing} ({plain(err)}). {STAYS} and nothing merged here."
        super().__init__("gh", f"{said} {GH_ACCESS} is the person's to repair: {HANDOFF}")
        self.person = f"{said} Repair {GH_ACCESS}, then try again."


def push_problem(wt, branch, remote, there, err):
    """git couldn't push, in git's own words, since a refused sign-in, a moved branch and a rule on
    the remote all end here. there: what GitHub holds for the branch. The one cause checked here is
    a lease refused on this clone's tracking ref, which a branch published without a push leaves behind."""
    said = f"{NO_PUSH} {branch} to {remote}: {plain(err)}. {STAYS}."
    tracked = git(wt, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}")[1]
    if there and tracked != there:
        said += (f" This clone's tracking ref {remote}/{branch} is at {tracked[:7] or 'nothing'} and GitHub has {there[:7]}, so "
                 "--force-with-lease won't overwrite it: a fetch that shows what is there comes first.")
    return said + f" git push works apart from gh's sign-in, and it's the person's to repair: {HANDOFF}"


def host_url(hosts):
    """A remote URL's host, with or without a scheme and user, and exact: github.com.example.org isn't github.com."""
    return re.compile(rf"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/]+@)?(?:{hosts})[:/]", re.I)


GITHUB_URL = host_url(r"(?:ssh\.)?github\.com")
# Public hosts that are their own forges, so never GitHub and never a host gh can sign in to. Any
# other host could be GitHub Enterprise or an alias for one.
ELSEWHERE_URL = host_url(r"bitbucket\.org|gitlab\.com|(?:ssh\.)?dev\.azure\.com")


def remote_urls(main):
    """Every remote's configured URL, sorted; [] for a repo with no remotes."""
    ok, out, _ = git(main, "config", "--get-regexp", r"^remote\..*\.url$")
    return sorted(line.split(None, 1)[-1] for line in out.splitlines()) if ok else []


def github(s, fresh=False):
    """The repo on GitHub ("owner/name"), asked again after an hour or once the remotes change (a
    saved answer keeps a hash of them, as a URL can hold a token). None: tasks merge locally. That
    takes a repo with no remotes, or only remotes on another forge (ELSEWHERE_URL): gh isn't asked,
    and any saved name goes. Or gh's own word that its remotes aren't on GitHub, which is saved. But
    those words mean only "not a host gh knows": a github.com remote overrules them, and so does a
    name saved for these same remotes (one saved before hashes were kept counts as that), as gh may
    have lost that host's sign-in. Every other failure refuses (GhFailed), saving nothing: signed
    out, no network, or a host only gh can place. gh not installed refuses for a github.com remote
    or a saved name, and is taken as a no otherwise; a gh that is there and can't run isn't that (gh()).
    fresh: gh is asked whatever was saved. s.github_saved says whether this answer was a saved one."""
    s.github_saved = False
    if s.loc["kind"] != "repo":
        return None
    g, urls = s.data.get("github") or {}, remote_urls(s.loc["folder"])
    if all(ELSEWHERE_URL.match(url) for url in urls):
        if s.data.pop("github", None) is not None:
            s.dirty = True
        return None
    mark = hashlib.sha256("\n".join(urls).encode()).hexdigest()[:16]
    if not fresh and g.get("remotes") == mark and now() - g.get("at", 0) < 3600000:
        s.github_saved = True
        return g.get("repo")
    ok, out, err = gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner", cwd=s.loc["folder"])
    named = any(GITHUB_URL.match(url) for url in urls)
    confirmed = g.get("repo") and g.get("remotes") in (None, mark)
    said_no = NOT_GITHUB in err and not (named or confirmed)
    absent = err == GH_MISSING and not (named or g.get("repo"))
    if not (ok and out) and not said_no and not absent:
        raise GhFailed("say which GitHub repository this folder is", err or "no answer")
    s.data["github"] = {"repo": out if ok and out else None, "at": now(), "remotes": mark}
    s.dirty = True
    return s.data["github"]["repo"]


def no_local_merge(s, task):
    """Refuses a local merge of a task in a repo on GitHub (Fail): there it goes through its pull
    request, and with no answer from gh (github()) nobody can say none exists. A saved "not on
    GitHub" is asked once more first, as a merge here can't be taken back; reads keep the saved one."""
    repo = github(s)
    if not repo and getattr(s, "github_saved", False):
        repo = github(s, fresh=True)
    if repo:
        raise Fail(f"{s.ref(task)} has no pull request recorded, and this repo merges through one. Run ready to open it, "
                   f"or `herdr-task adopt {s.ref(task)} --pr <number>` to record the one that exists.")


def remote_of(main):
    names = git(main, "remote")[1].split()
    return "origin" if "origin" in names else (names[0] if names else "origin")


ONLY_A_COMMIT = "only a commit, not a branch"


def is_branch(main, base):
    """The base is a branch here: its own, or its remote's copy. A commit id never is one."""
    return not OID.fullmatch(base) and any(git(main, "rev-parse", "--verify", "--quiet", ref)[0]
                                           for ref in (f"refs/heads/{base}", f"refs/remotes/{remote_of(main)}/{base}"))


def only_a_commit(main, base):
    """The base names a commit here, by its id or a tag, and no branch: nothing to merge into."""
    return not is_branch(main, base) and git(main, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")[0]


def merge_into_branch(s, task):
    """Refuses (Fail) a merge here into a base that is only a commit: there's no branch to land it on."""
    base = task.get("base") or "main"
    if only_a_commit(s.loc["folder"], base):
        shown = base[:7] if OID.fullmatch(base) else base
        raise Fail(f"{s.ref(task)}'s base {shown} is {ONLY_A_COMMIT}, so there's nowhere here to merge it. {STAYS}. "
                   f"Merge it where you want it by hand, then run `herdr-task done {s.ref(task)}`.")


OID = re.compile(r"[0-9a-f]{40,64}")


def branch_commit(repo, branch):
    """The commit GitHub holds for a branch now, read through gh, so on gh's own access; None when
    it has no such branch, which is an answer. No answer refuses (Fail), never read as there or as not."""
    ok, out, err = gh("api", f"repos/{repo}/git/ref/heads/{quote(branch, safe='/')}", "--jq", ".object.sha")
    if not ok and "HTTP 404" in err:
        return None
    if not ok or not OID.fullmatch(out):
        raise GhFailed(f"read {branch} on GitHub", err or "no answer")
    return out


def publish(s, task, repo):
    """The task's branch on its remote: pushed, unless GitHub already holds exactly its tip, so a
    published branch needs no git credentials. The branch goes by its full name: a bare one reads a
    tag of that name first, and git push refuses it."""
    wt, br = task["worktree"], task["branch"]
    head = f"refs/heads/{br}"
    ok, tip, err = git(wt, "rev-parse", "--verify", head)
    if not ok or not tip:
        raise Caused("git", f"Couldn't read {br} here: {plain(err)}")
    there = branch_commit(repo, br)
    if there == tip:
        return
    remote = remote_of(s.loc["folder"])
    ok, _, err = git(wt, "push", "--force-with-lease", "-u", remote, f"{head}:{head}")
    if not ok:
        raise Caused("git", push_problem(wt, br, remote, there, err))


def pr_open(s, task, repo, summary=None):
    """Publishes the task's branch and opens its pull request (or keeps the open one, also one
    opened by hand or by its agent for the branch: SHEP-13's "already exists"). Refuses (Fail) when
    gh or git can't: a saved pull request gh can't read is never replaced by a new one, and one
    adopted (adopt_existing()) is never replaced at all. Nor does a branch whose open pull request
    targets another base get a second one (no_other_base())."""
    br, pr = task["branch"], task.get("pr") or {}
    state = None
    if pr.get("number"):
        ok, state, err = gh("pr", "view", str(pr["number"]), "--repo", repo, "--json", "state", "-q", ".state")
        if not ok or not state:
            raise GhFailed(f"read pull request #{pr['number']}", err or "no answer")
        if state == "MERGED" and pr.get("adopted"):
            raise Fail(f"Pull request #{pr['number']}, adopted for {s.ref(task)}, already merged, so there is nothing to publish. "
                       f"The tick finishes the task if that was into {task.get('base') or 'main'}, and holds it for the "
                       "person if it wasn't: end your turn.")
        if state != "OPEN" and pr.get("adopted"):
            raise Fail(f"Pull request #{pr['number']}, adopted for {s.ref(task)}, is {state.lower()}, and adoption never opens "
                       f"another. Whether to reopen it is the person's call: {HANDOFF}")
    if state != "OPEN":
        no_other_base(s, task, repo)
    publish(s, task, repo)
    if state == "OPEN":
        if summary:
            gh("pr", "comment", str(pr["number"]), "--repo", repo, "--body", summary)
        return pr
    if pr_adopt(task, repo):
        if summary:
            gh("pr", "comment", str(task["pr"]["number"]), "--repo", repo, "--body", summary)
        return task["pr"]
    # SHEP-59: never a second pull request for a branch that already had one merged (one at its tip
    # is done before this: already_merged()); commits made since go on a new branch.
    done = pr_merged(task, repo)
    if done:
        raise Fail(f"Pull request #{done['number']} for {br} is already merged, and {br} has commits since. "
                   f"Put them on a new branch (a new task) rather than a second pull request.")
    body = (task.get("prompt") or "").strip() or task["title"]
    if summary:
        body += "\n\n## Summary\n\n" + summary.strip()
    if (task.get("details") or "").strip():
        body += "\n\n## Details\n\n" + task["details"].strip()
    ok, out, err = gh("pr", "create", "--repo", repo, "--head", br, "--base", task.get("base") or "main",
                      "--title", f"{s.ref(task)} {task['title']}", "--body", body)
    if not ok or not out:
        raise Caused("gh", f"{NO_PR}: {plain(err)}. {STAYS}: {HANDOFF}")
    url = out.split()[-1]
    task["pr"] = {"number": int(url.rstrip("/").split("/")[-1]), "url": url, "repo": repo}
    return task["pr"]


def open_prs(task, repo):
    """This repo's open pull requests for the task's branch, never a fork's branch of the same name."""
    doing = f"list the pull requests for {task['branch']}"
    ok, out, err = gh("pr", "list", "--repo", repo, "--head", task["branch"], "--state", "open",
                      "--json", "number,url,isCrossRepository,baseRefName,headRefOid")
    if not ok:
        raise GhFailed(doing, err)
    try:
        prs = [p for p in json.loads(out) if not p["isCrossRepository"]] if out else []
        if all(isinstance(p["number"], int) and isinstance(p["url"], str) and isinstance(p["baseRefName"], str) for p in prs):
            return prs
    except (ValueError, TypeError, KeyError):
        pass
    raise GhFailed(doing, "an answer it couldn't read")


def no_other_base(s, task, repo):
    """Refuses (Fail), before anything is published, a branch whose open pull requests all target
    another base: gh would open a second one, or fail with no way forward. adopt can record it, once
    the commits prove its base. One into the task's own base goes on to pr_adopt()."""
    base, prs = task.get("base") or "main", open_prs(task, repo)
    if prs and not any(p["baseRefName"] == base for p in prs):
        n, other = prs[0]["number"], prs[0]["baseRefName"]
        raise Fail(f"{SECOND_PR}: #{n} is open for {task['branch']} into {other}, not {base}. "
                   f"`herdr-task adopt {s.ref(task)} --pr {n}` records it once its base is proved. {STAYS}: {HANDOFF}")


def pr_adopt(task, repo):
    """The open pull request for the task's branch, opened by hand or by its agent, recorded on the
    task; None when there is none (SHEP-13: ready failed with "already exists"). Only one from this
    repo (open_prs()), into the task's base, at the branch's tip here."""
    base, prs = task.get("base") or "main", open_prs(task, repo)
    tip_ok, tip, _ = git(task["worktree"], "rev-parse", "--verify", "--quiet", f"refs/heads/{task['branch']}")
    found = next((p for p in prs if p["baseRefName"] == base and tip_ok and tip and p.get("headRefOid") == tip), None)
    if found:
        task["pr"] = {"number": found["number"], "url": found["url"], "repo": repo}
    return task.get("pr") if found else None


PR_NUMBER = r"[0-9]{1,18}"  # ASCII digits only: "²" passes isdigit(), and int() refuses it
PR_LINK = re.compile(rf"https://[^/]+/([^/]+/[^/]+)/pull/({PR_NUMBER})/?")
BRANCH = re.compile(r"[\w./@+-]+")  # as launch.base_ref(), which imports from here


def adopt_existing(s, task, given):
    """Records a pull request that already exists on a started task, by hand (herdr-task adopt): its
    number, or its link, and the head it verified (adopted_head), the one Accept merges. True:
    recorded. False: it already was, at this branch tip, and nothing changed; adopting it again once
    the branch has moved verifies it again and records the new head. Refuses (Fail)
    with what to do, leaving the task as it was, unless it is this repo's own open pull request for
    the task's branch, at exactly its tip, and its base is proved from commits (below). On success
    the task's base becomes the pull request's, the old one kept in adopted_from, and it merges only
    on the person's Accept. Never creates a pull request, pushes, fetches or merges.

    The proof, on the commit GitHub's base branch holds now: the task's start commit is the one and
    only merge base of the tip and that commit. So the base holds everything the task started from
    and none of the task's own work: the pull request carries exactly the task's commits, whatever
    the two branches are called. --all: two merge bases prove nothing. A branch that has since taken
    in that base's commits refuses too, stricter than it need be and simple to check. And the
    recorded base, on GitHub and here, must be in that commit, so a base that went its own way isn't
    silently dropped as the merge target."""
    ref, main, br, start = s.ref(task), s.loc["folder"], task.get("branch"), task.get("start")
    if task.get("mode") != "worktree" or task.get("state") not in ("running", "ready") or not (task.get("worktree") and br and start):
        raise Fail(f"{ref} isn't a started worktree task ({task.get('state')}): adoption is for one with its branch and start "
                   "commit recorded. Start it, or reopen it.")
    repo = github(s)
    if not repo:
        raise Fail(f"{main} has no remote gh can place on GitHub, so there is no pull request to adopt.")
    link = PR_LINK.fullmatch(given.strip())
    word = link.group(2) if link else given.strip().lstrip("#")
    if not re.fullmatch(PR_NUMBER, word):
        raise Fail(f"{given!r} isn't a pull request: give its number or its link.")
    number = int(word)
    if link and link.group(1).lower() != repo.lower():
        raise Fail(f"{given} is in {link.group(1)}, and this folder's repository is {repo}. Give a pull request of {repo}.")
    have = task.get("pr") or {}
    if have.get("number"):
        if have["number"] == number and str(have.get("repo")).lower() == repo.lower():
            # Adopted again: verified again, and its head recorded again, once the branch has moved
            # from the head adoption recorded (or none was recorded). Otherwise nothing changes.
            here = git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{br}")[1]
            if not have.get("adopted") or (have.get("adopted_head") and have["adopted_head"] == here):
                return False
        else:
            raise Fail(f"{ref} already records pull request #{have['number']} of {have.get('repo')}, and a task keeps the one it "
                       f"records. Carry on with that one, or use a new task for #{number}.")
    ok, out, err = gh("pr", "view", str(number), "--repo", repo, "--json",
                      "number,url,state,isCrossRepository,headRefName,headRefOid,baseRefName")
    if not ok:
        raise GhFailed(f"read pull request #{number} of {repo}", err)
    try:
        p = json.loads(out)
        answered = PR_LINK.fullmatch(p["url"])
        base, state = p["baseRefName"], p["state"]
        cross, head, head_oid = p["isCrossRepository"], p["headRefName"], p["headRefOid"]
        if not isinstance(cross, bool) or not all(isinstance(x, str) for x in (base, state, head, head_oid)):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise GhFailed(f"read pull request #{number} of {repo}", "an answer it couldn't read")
    for name in (head, base):
        if not BRANCH.fullmatch(name) or name.startswith("-"):
            raise Fail(f"GitHub answered #{number} with the branch {name!r}, which isn't a branch name herdr-task takes. "
                       "Nothing was adopted.")
    if not answered or answered.group(1).lower() != repo.lower() or int(answered.group(2)) != number:
        raise Fail(f"GitHub answered #{number} with {p['url']}, not a pull request of {repo}. Check the repository's name and "
                   "the number, then adopt again.")
    if cross is not False:
        raise Fail(f"Pull request #{number} comes from another repository (a fork). Adopt only one whose branch is in {repo}.")
    if head != br:
        raise Fail(f"Pull request #{number} is for branch {head}, and {ref} works on {br}. Adopt the one for {br}.")
    if state != "OPEN":
        raise Fail(f"Pull request #{number} is {state.lower()}, not open. Reopen it on GitHub, then adopt again.")
    ok, tip, _ = git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{br}")
    if not ok or not tip:
        raise Fail(f"Branch {br} isn't here to compare. Restore it, then adopt again.")
    if head_oid != tip:
        raise Fail(f"Pull request #{number} is at {head_oid[:7]}, and {br} is at {tip[:7]} here. Bring them to the same "
                   "commit, then adopt again.")
    if tip == start:
        raise Fail(f"{br} has no commits of its own past its start, so there is nothing for #{number} to carry. Commit the "
                   "task's work first.")
    base_oid = branch_commit(repo, base)
    if not base_oid:
        raise Fail(f"{base}, the base of #{number}, isn't on GitHub, so it can't be proved to match where {ref} started. "
                   "Retarget the pull request to a branch that exists, then adopt again.")
    if not git(main, "cat-file", "-e", f"{base_oid}^{{commit}}")[0]:
        raise Fail(f"The base of #{number} ({base} at {base_oid[:7]}) isn't here, so it can't be proved to match where {ref} "
                   f"started. Run `git fetch {remote_of(main)} {base}` in {main}, then adopt again.")
    ok, bases, _ = git(main, "merge-base", "--all", tip, base_oid)
    if not ok or bases.split() != [start]:
        met = ", ".join(b[:7] for b in bases.split()) or "nowhere"
        raise Fail(f"Can't prove #{number}'s base {base} matches {ref}: the task started at {start[:7]}, and its tip meets "
                   f"{base_oid[:7]} at {met}, so the pull request wouldn't carry exactly the task's work. Retarget it or rebase "
                   "the branch so they meet at the start, or leave it unadopted.")
    # The task's base as it merges today: none recorded is main. A commit isn't a branch to merge into.
    recorded = task.get("base")
    old = recorded or "main"
    if old != base:
        if OID.fullmatch(old):
            raise Fail(f"{ref}'s recorded base {old[:7]} is {ONLY_A_COMMIT}, so nothing shows {base} holds it. Nothing was "
                       "adopted.")
        copies = [c for c in (branch_commit(repo, old), git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{old}")[1]) if c]
        if not copies and only_a_commit(main, old):
            raise Fail(f"{ref}'s recorded base {old} is {ONLY_A_COMMIT}, so nothing shows {base} holds it. Nothing was adopted.")
        if not copies:
            raise Fail(f"{ref}'s recorded base {old} isn't on GitHub or here, so nothing shows {base} holds it. Restore it, then "
                       "adopt again.")
        for commit in copies:
            if not git(main, "merge-base", "--is-ancestor", commit, base_oid)[0]:
                raise Fail(f"{ref}'s recorded base {old} at {commit[:7]} isn't in {base} at {base_oid[:7]}, so adopting would "
                           f"silently replace its merge target. Bring {old} into {base} (or fetch it, if that commit isn't here), "
                           "then adopt again.")
    # The head verified here is the one Accept merges (adopted_moved()): only adopting again records another.
    task["pr"] = {**have, "number": number, "url": p["url"], "repo": repo, "adopted": now(), "adopted_head": tip}
    if old != base:
        task["adopted_from"] = {"base": old, "at": now(), "pr": number}
    if recorded != base:
        task["base"], task["base_set"], task["base_by"] = base, True, "pull-request"
    # Adoption decides no merge: a merge the tick would start, or a refusal it answers, goes with it.
    task.pop("auto_merge", None)
    if (task.get("attention") or "").startswith(ADOPTION_ANSWERS):
        task.pop("attention")
    s.dirty = True
    return True


def pr_merged(task, repo):
    """The merged pull request for the task's branch (from this repo, into its base), or None
    (SHEP-59: a squash merge leaves the branch's commits out of the base)."""
    ok, out, _ = gh("pr", "list", "--repo", repo, "--head", task["branch"], "--state", "merged",
                    "--json", "number,url,isCrossRepository,baseRefName,headRefOid,mergeCommit")
    try:
        return next((p for p in json.loads(out) if not p.get("isCrossRepository")
                     and p.get("baseRefName") == (task.get("base") or "main")), None) if ok and out else None
    except (ValueError, TypeError, AttributeError):
        return None


def landed(s, task):
    """Its own work is in its base branch, though not as its commits (squash-merged, SHEP-59):
    merging its tip into the base, here or on its remote, would change nothing. Only a branch with
    work of its own (own_work()): one that just caught up with its base is never merged."""
    if not own_work(s, task):
        return False
    main, base = s.loc["folder"], task.get("base") or "main"
    ok, tip, _ = git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{task.get('branch')}")
    tip = tip if ok and tip else task.get("head")
    # The base by its full names, as a same-named tag would otherwise be read first (PR 19).
    for ref in (local_base(base), f"refs/remotes/{remote_of(main)}/{base}"):
        ok, tree, _ = git(main, "merge-tree", "--write-tree", ref, tip)
        has, have, _ = git(main, "rev-parse", "--verify", "--quiet", f"{ref}^{{tree}}")
        if ok and has and tree and tree.split()[0] == have:
            return True
    return False


def already_merged(s, task):
    """SHEP-59: its work is already in its base (its pull request merged, squash too, or nothing left
    to merge): ready and the tick mark it done instead of opening a pull request. Returns the merged
    pull request ({} when merged without one), or None. Its pull request is recorded on the task."""
    if merged_here(s, task):
        return {}
    repo = github(s)
    tip = task.get("head")
    if repo:
        main, base = s.loc["folder"], task.get("base") or "main"
        remote = remote_of(main)
        # Fetched as a branch: a bare name reads the remote's same-named tag first (as update_main()).
        git(main, "fetch", "--quiet", remote, f"+refs/heads/{base}:refs/remotes/{remote}/{base}")
        tip = git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{task.get('branch')}")[1] or tip
        if task.get("pr"):
            v = pr_view(task)
            if v and v.get("state") == "MERGED" and v.get("headRefOid") == tip:
                return {**task["pr"], "mergeCommit": v.get("mergeCommit")}
        found = pr_merged(task, repo)
        if found and found.get("headRefOid") == tip:
            task["pr"] = {"number": found["number"], "url": found["url"], "repo": repo}
            return {**task["pr"], "mergeCommit": found.get("mergeCommit")}
    if landed(s, task):
        # Squashed in with no pull request to read: finish() keeps the branch (its tip isn't in the
        # base), and its note says the work landed (kept_because()).
        task["landed"] = True
        return {}
    return None


BAD = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
PENDING = {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING", "REQUESTED", "EXPECTED"}


def pr_read(task):
    """A pull request as gh answers it, and why not: (its view, None), or (None, gh's reason)."""
    pr = task["pr"]
    ok, out, err = gh("pr", "view", str(pr["number"]), "--repo", pr["repo"], "--json", "state,mergeable,headRefOid,baseRefName,statusCheckRollup,mergeCommit")
    if not ok:
        return None, err or "no answer"
    try:
        v = json.loads(out)
    except ValueError:
        v = None
    return (v, None) if isinstance(v, dict) else (None, "an answer it couldn't read")


def pr_view(task):
    """pr_read()'s view alone, for those that wait quietly for the next look: None when gh can't say."""
    return pr_read(task)[0]


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
    """After a merge on GitHub: the base branch here catches up when it's checked out and clean.
    Named in full wherever a commit lands on it: a same-named tag there, or a tag here called
    remote/base, would otherwise move it to that tag's commit. So is what's fetched: a bare name
    reads the remote's same-named tag first, and the remote's copy of the branch wouldn't move."""
    main, base = s.loc["folder"], task.get("base") or "main"
    remote, head = remote_of(main), f"refs/heads/{base}"
    git(main, "fetch", remote, f"+{head}:refs/remotes/{remote}/{base}")
    ok, cur, _ = git(main, "symbolic-ref", "HEAD")
    if ok and cur == head and not git(main, "status", "--porcelain", "--untracked-files=no")[1]:
        git(main, "merge", "--ff-only", f"refs/remotes/{remote}/{base}")
    elif not (ok and cur == head):
        # A base not checked out here (a task's own --base): its branch fast-forwards (git refuses
        # anything else, and a branch checked out in another worktree).
        git(main, "fetch", remote, f"{head}:{head}")


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


def local_base(base):
    """A task's base here by its full name, as a tag of the same name reads first; a commit stays
    one (a folder on no branch: current_base())."""
    return base if OID.fullmatch(base) else f"refs/heads/{base}"


def base_commit(main, base):
    """A task's base as it can be read here: its branch, else its remote's copy (a target this clone
    never checked out, as an adopted pull request's can be)."""
    ref = local_base(base)
    return ref if git(main, "rev-parse", "--verify", "--quiet", ref)[0] else f"refs/remotes/{remote_of(main)}/{base}"


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
            git(main, "merge-base", "--is-ancestor", tip, ref)[0] for ref in (local_base(base), f"refs/remotes/{remote_of(main)}/{base}")):
        task["own"] = tip
        s.dirty = True
    return task.get("own")


def merged_head(s, task, tip):
    """The commit of the task's branch that merged, for finish(); None when that can't be said. One
    a merge recorded (merged_head: what merge_now() asked GitHub to merge, or the tip a fast-forward
    landed) stands. A pull request merged by hand: its head, as gh says it merged; never its squash
    commit, which the branch never holds. No pull request: the branch tip, once it is in the task's
    base branch (base_commit(), never a same-named tag)."""
    if task.get("merged_head"):
        return task["merged_head"]
    if task.get("pr"):
        v = pr_view(task)
        head = (v or {}).get("headRefOid") if (v or {}).get("state") == "MERGED" else None
    else:
        main = s.loc["folder"]
        head = tip if tip and git(main, "merge-base", "--is-ancestor", tip, base_commit(main, task.get("base") or "main"))[0] else None
    if isinstance(head, str) and OID.fullmatch(head):
        task["merged_head"] = head
        return head
    return None


def kept_because(s, task):
    """Why finish() keeps the task's branch and worktree, for the done task's note; None when both go:
    the branch tip is exactly what merged, and the worktree holds nothing uncommitted (ignored files
    aside). The worktree goes with its branch, never alone."""
    wt, br, main = task["worktree"], task.get("branch"), s.loc["folder"]
    kept = f"Kept {br} and its worktree {wt}"
    tip = git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{br}")[1] if br else ""
    if not tip:
        # No branch left: nothing of it to lose, and a worktree still here is kept, as nothing shows what merged.
        return (f"Kept the worktree {wt}: its branch {br or ''} isn't here to compare with what merged, so nothing was removed."
                if os.path.isdir(wt) else None)
    head = merged_head(s, task, tip)
    if not head:
        if task.get("pr"):
            return f"{kept}: gh didn't confirm which commit of pull request #{task['pr'].get('number')} merged, so nothing was removed."
        if task.get("landed"):
            return (f"{kept}: its work is in {task.get('base') or 'main'} as other commits (squashed), not as {br} at "
                    f"{tip[:7]}, so nothing was removed.")
        return f"{kept}: {br} at {tip[:7]} isn't in {task.get('base') or 'main'}, so it holds work that didn't merge."
    if tip != head:
        # Ahead of it, beside it or behind it (GitHub's "Update branch", a committed suggestion): not
        # what merged, so neither goes, whichever it is.
        return f"{kept}: {br} is at {tip[:7]} here and what merged was {head[:7]}, so nothing was removed."
    if os.path.isdir(wt):
        ok, out, _ = git(wt, "status", "--porcelain", "--untracked-files=normal")
        if not ok or out:
            return f"{kept}: the worktree has uncommitted changes or files git doesn't track, so nothing was removed."
    return None


def finish(s, task, even_if_busy=False):
    """Done, its branch merged: removes the worktree and branch when the branch holds nothing that
    didn't merge, nothing is left uncommitted there and (unless the person merged from Herdr) no agent
    still works in it. Whatever stays is said on the done task (kept), which needs nothing more."""
    task["state"], task["done_at"] = "done", now()
    for k in ("attention", "merge_requested", "queue", "queued_at", "kept"):
        task.pop(k, None)
    s.dirty = True
    wt, br, main = task.get("worktree"), task.get("branch"), s.loc["folder"]
    if not wt or (not even_if_busy and any(agent_running(k) for k in live_agents(s.key(task)))):
        return
    why = kept_because(s, task)
    if why:
        task["kept"] = why
        return
    if os.path.isdir(wt) and not git(main, "worktree", "remove", "--force", wt)[0]:
        task["kept"] = f"Kept {br} and its worktree {wt}: git couldn't remove the worktree, so the branch stays too."
        return
    if br:
        git(main, "branch", "-D", br)
