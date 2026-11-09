"""Launch admission (L1): the one owner every agent start on this machine goes through, a task's
agent's (start, the tick's queue, an automation's run, resume, switch, a backup) and an
Assistant's (its five start sites run `herdr-task launch run`), with a durable journal of each.

A start is admitted around its preparation, in this order:

- Preflight (admit_task, admit_assistant): the settings file is read once, strictly (one that is
  there but unreadable refuses, never reads as Personal), the provider owner (providers.py)
  admits the route, a task's coordinator is resolved, and a start of the same identity that is
  still unresolved refuses. Nothing has an effect before it.
- Claim (Admission.claimed): the revision is checked again and the start recorded as
  never-submitted before its first effect (a task's state, a worktree, a terminal). A refusal,
  an error or a shutdown (SIGTERM, SIGHUP, Ctrl-C) before submission cancels the claim itself.
- Submit (Admission.submit): in one step under the journal's lock, the claim is checked to be
  still this start's own (a recovery revokes it: the delayed sender is fenced here) and the
  revision unchanged, and the start is recorded submission-uncertain. Then `hc run` is the very
  next thing done: no settings read, no other process and no wait between. A reply naming the
  terminal confirms it (confirmed).

The revision is a digest of what the start was admitted on (route and plan fingerprint, the CLI
words or hc words it will run, its space and role), recomputed from a fresh read: independent of
the launch id, which is new for every attempt. It is content, not a counter: settings changed
away and back to the same words are the same revision (the settings file keeps no counter).

States: never-submitted (no `hc run` was sent; its owner, or the person with `launch recover`,
can cancel it), submission-uncertain (`hc run` was or may have been sent: kept until positive
evidence), confirmed, cancelled. A lost reply keeps its launch id: the one look afterwards (and
`launch reconcile` later) confirms it only on a terminal carrying that id's herdr.launch label.
An empty or failed lookup keeps it uncertain, and no start of that identity is retried.

What this does not establish (held, not invented here): herdr-core keeps no receipt, idempotency
key or revocation for an `hc run` it may have been sent, so nothing releases a
submission-uncertain start without positive evidence; the journal fences this application's
senders only, never an unknown process already running; and no recovery is automatic: which
evidence would allow one is a human decision."""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import types
import uuid

from .base import Fail, guard, HOME, now, run, STORE
from .providers import (admit_assistant, admit_launch, AZURE, NO_BINDING, PERSONAL, read_strict, STALE_SELECTION,
                        STALE_TASK_CHOICE)
# TEMPLATES_DIR: herdr-core's templates folder (HERDR_TASK_TEMPLATES, else ~/.config/herdr-core/templates).
from .settings import agent_key, bare, TEMPLATES as TEMPLATES_DIR

LABEL = "herdr.launch"
NEVER, UNCERTAIN, CONFIRMED, CANCELLED = "never-submitted", "submission-uncertain", "confirmed", "cancelled"
OPEN = (NEVER, UNCERTAIN)
ROLES = ("coordinator", "agent")
# Closed starts (confirmed, cancelled) are kept this long for status; an open one is never dropped.
KEEP_MS = 30 * 24 * 3600 * 1000
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,79}")
SLOT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@:/-]{0,119}")
IDENTITY = re.compile(r"(?:task|coordinator|agent):[A-Za-z0-9._:/#@-]{1,240}")
LAUNCH_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

CHANGED = ("The settings this start was admitted on changed before it was {}: its route or agent selection is not what "
           "was checked. Nothing was started; start it again to use the new settings.")
REVOKED = ("This start's claim ({}) was revoked or already used before it was sent, so it sends nothing: a recovery "
           "released it, or another start owns it now. Nothing was started.")
PARENT_CHANGED = ("Its Assistant ({}) ended or was replaced while this start was being prepared. Nothing was started; "
                  "start it again to report to the current one.")
BROKEN = ("The launch journal ({}) can't be read. It is never read as empty, since it may hold a start that was sent. "
          "Nothing was started or changed; move it aside only once every start it names is known.")
SHUTDOWN = "stopped before it was sent ({})"
NO_CONFIG_DIR = ("CLAUDE_CONFIG_DIR isn't one absolute path to a Claude Code folder, so this start can't say which "
                 "profile its agent would use. Nothing was started; set it to an absolute path, or unset it.")
# A submission-uncertain start that no terminal ever confirms stays held: herdr-core gives no
# receipt, so releasing it on any other evidence is a decision this version leaves held (the
# migration inventory's manual-recovery), not a command here.
HELD_UNCERTAIN = ("If no terminal ever carries its launch id, releasing it is a held decision (manual recovery in the "
                  "migration inventory): this version has no command that releases it, and only a later, separately "
                  "approved change can.")


def _path():
    return os.path.join(STORE, ".launches.json")


def _load():
    try:
        with open(_path()) as f:
            d = json.load(f)
    except FileNotFoundError:
        return {"version": 1, "launches": {}, "claims": {}}
    except (OSError, ValueError, UnicodeDecodeError):
        raise Fail(BROKEN.format(_path()))
    if not isinstance(d, dict) or not isinstance(d.get("launches"), dict) or not isinstance(d.get("claims"), dict):
        raise Fail(BROKEN.format(_path()))
    return d


def _save(d):
    """Written whole, synced, then renamed over the journal and the folder synced: a crash leaves
    the old journal or the new one, never part of one."""
    t = now()
    keep = set(d["claims"].values())
    d["launches"] = {k: r for k, r in d["launches"].items()
                     if k in keep or r.get("state") in OPEN or t - (r.get("updated") or r.get("at") or 0) < KEEP_MS}
    path = _path()
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(os.path.dirname(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def journal():
    """The journal under its own lock (machine-wide, apart from any task list's): changes made
    inside are saved when the block ends without an error, and dropped when it raises."""
    os.makedirs(STORE, exist_ok=True)
    lock = open(os.path.join(STORE, ".launches.lock"), "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        d = _load()
        before = json.dumps(d, sort_keys=True)
        yield d
        if json.dumps(d, sort_keys=True) != before:
            _save(d)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def digest(parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def busy_words(identity, rec, lid, who=None):
    """Why a start of `identity` can't begin while its earlier one is open, and the exact next step."""
    who = who or identity
    if not rec:
        return (f"{who} has a claimed start ({lid}) the journal no longer describes, so whether it was sent is unknown. "
                f"Nothing was started. `herdr-task launch status {identity}` shows the claim. {HELD_UNCERTAIN}")
    if rec["state"] == NEVER:
        return (f"{who} is already starting (launch {lid}, claimed and not sent). Nothing was started. If that start's "
                f"herdr-task has ended, release it with `herdr-task launch recover {identity} {lid}`.")
    return (f"{who}'s last start ({lid}) may have started an agent that no reply confirmed (submission uncertain). Nothing "
            f"was started or retried. `herdr-task launch reconcile {identity} {lid}` looks for its terminal. {HELD_UNCERTAIN}")


def recorded_on(t, rec):
    """Whether task t's list already holds the agent rec started (by launch id or address)."""
    rows = t.get("reviewers" if (rec.get("task") or {}).get("role") else "agents") or []
    return any(x.get("launch") == rec["launch"] or (rec.get("address") and x.get("address") == rec["address"]) for x in rows)


def put_on(t, rec):
    """The agent of confirmed start rec on task t, as its own start would have put it, once (in memory)."""
    job = rec["task"]
    if recorded_on(t, rec):
        return False
    t.setdefault("reviewers" if job.get("role") else "agents", []).append({**job["agent"], "address": rec["address"], "launch": rec["launch"]})
    # What the start set up before it was sent (its worktree, branch, base and start commit): the agent runs there.
    for k, v in (job.get("made") or {}).items():
        if t.get(k) in (None, "") or k == "mode":
            t[k] = v
    if not job.get("role"):
        if t["state"] in ("todo", "scheduled", "queued", "done"):
            t["state"] = "running"
            t.setdefault("started", now())
        for k in ("queue", "queued_at", "held", "scheduled_for", "attention"):
            t.pop(k, None)
        if job.get("space"):
            t["space"] = job["space"]
    return True


def on_its_task(rec):
    """Whether confirmed task start rec's agent is in its task list as saved (read only): a
    claim can be held after its own start saved, until the next start of that task releases it."""
    from .store import locate, read_list, store_path
    job = rec.get("task") or {}
    try:
        path = store_path(locate(job["folder"])["folder"])[1]
    except (Fail, KeyError, TypeError):
        return False
    t = next((x for x in (read_list(path) or {}).get("tasks") or [] if x.get("id") == job.get("id")), None)
    return bool(t) and recorded_on(t, rec)


def refuse_busy(d, identity, who=None, task=None, repair=False):
    """Refuses while `identity` has a start that isn't resolved: never submitted, submission
    uncertain, or confirmed while its task list hasn't recorded its agent (its herdr-task ended
    before saving). With task (the task as this start reads it): a recorded one releases its
    claim. An unrecorded one refuses this start, so it never runs twice; with repair (a caller
    that saves its task list after a refusal: the tick) it is put on the task too, and the
    refusal carries its address (Fail.put_on)."""
    lid = d["claims"].get(identity)
    if not lid:
        return
    rec = d["launches"].get(lid)
    if rec and rec.get("state") == CONFIRMED and isinstance(rec.get("task"), dict):
        if task is not None and recorded_on(task, rec):
            rec.update(recorded=True, updated=now())
            d["claims"].pop(identity, None)
            return
        on = repair and task is not None and put_on(task, rec)
        e = Fail(f"{who or identity}'s last start ({lid}) runs as {rec.get('address')}, but its task list never recorded it "
                 f"(its herdr-task ended before saving). Nothing was started. "
                 + ("It is on the task now." if on else f"`herdr-task launch reconcile {identity} {lid}` records it on its task."))
        if on:
            e.put_on = rec["address"]
        raise e
    if rec and rec.get("state") not in OPEN:
        return
    raise Fail(busy_words(identity, rec, lid, who))


def open_start(identity, who=None, task=None, repair=False):
    """Refuses while `identity` has an unresolved start (preflight's look, before any effect)."""
    with journal() as d:
        refuse_busy(d, identity, who, task, repair)


def options_of(words):
    """An hc run's own options: its words before a bare "--"."""
    return words[:words.index("--")] if "--" in words else list(words)


def on_machine(words):
    """The machine an hc run's --on names, or None for this one."""
    opts = options_of(words)
    for i, a in enumerate(opts):
        if a == "--on" and i + 1 < len(opts):
            return opts[i + 1]
        if a.startswith("--on="):
            return a.split("=", 1)[1]
    return None


class Admission:
    """One admitted start: its identity, what it was admitted on (revision) and, once claimed,
    its launch id."""

    def __init__(self, identity, role, space, machine, revise, parent=None, who=None):
        self.identity, self.role, self.space, self.machine = identity, role, space, machine
        self.revise, self.parent, self.who = revise, parent, who or identity
        self.revision = revise()
        self.launch = None
        # sent: recorded submission-uncertain (hc run follows), so nothing may treat it as unstarted.
        self.sent = False
        self._old = {}
        # task: the task as its start reads it (refuse_busy's record check); config_dir: a Claude
        # Code start's folder, carried explicitly (None: the terminal's own environment decides).
        # fence(d): a start's own last check, under the journal's lock just before it is recorded as
        # sent (revival's: the same terminal process wasn't brought back by another sender).
        self.task, self.config_dir, self.fence = None, None, None

    def label(self):
        return ["--label", f"{LABEL}={self.launch}"]

    @contextlib.contextmanager
    def claimed(self):
        """Records the start as never-submitted (its revision checked first, nothing recorded if
        it changed), runs the block, and cancels its own claim if the block ends before submit()
        recorded it as sent: a refusal, an error, Ctrl-C, SIGTERM or SIGHUP."""
        if self.revise() != self.revision:
            raise Fail(CHANGED.format("recorded"))
        lid = str(uuid.uuid4())
        with journal() as d:
            refuse_busy(d, self.identity, self.who, self.task)
            d["launches"][lid] = {"launch": lid, "identity": self.identity, "role": self.role, "state": NEVER, "at": now(),
                                  "updated": now(), "revision": self.revision, "space": self.space,
                                  "machine": self.machine or "local", "parent": self.parent, "pid": os.getpid(),
                                  "config_dir": self.config_dir}
            d["claims"][self.identity] = lid
        self.launch = lid

        def stop(sig, _frame):
            raise SystemExit(128 + sig)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            try:
                self._old[sig] = signal.signal(sig, stop)
            except (ValueError, OSError):
                pass
        try:
            yield self
        except BaseException as e:
            why = str(e) if isinstance(e, Fail) else SHUTDOWN.format(type(e).__name__)
            self.cancel(why[:300])
            raise
        finally:
            self._restore()

    def _restore(self):
        """The shutdown handlers claimed() set, put back: once a start is sent, a SIGTERM or SIGHUP
        ends this process as it always did and leaves hc to finish (never kills it mid-start)."""
        for sig, h in self._old.items():
            if h is not None:  # a handler not set from Python can't be put back from here
                signal.signal(sig, h)
        self._old = {}

    def cancel(self, reason):
        """Its own claim, cancelled while it is still never-submitted and still its own; once sent
        (or revoked) this changes nothing."""
        if not self.launch:
            return
        with journal() as d:
            rec = d["launches"].get(self.launch)
            if rec and rec["state"] == NEVER and d["claims"].get(self.identity) == self.launch:
                rec.update(state=CANCELLED, reason=reason, updated=now())
                d["claims"].pop(self.identity, None)

    def submit(self, hc_args, parent_live=None, record=None):
        """Sends the start: `hc` with hc_args (they carry label()). Before it, its Assistant must
        still be live (parent_live), and under the journal's lock its claim must still be its own
        and its revision unchanged; it is then recorded submission-uncertain (with record: what a
        later reconcile needs, a task's agent record) and hc runs next. Returns hc's reply as
        {address, ...} once confirmed; refuses, keeping it uncertain, when no terminal is known to
        carry its launch id."""
        if self.parent and parent_live and not parent_live(self.parent):
            raise Fail(PARENT_CHANGED.format(self.parent))
        self._mark_sent(record)
        try:
            r = run(["hc", *hc_args])
        except (FileNotFoundError, PermissionError):
            # hc itself couldn't be executed (Popen reports the failed exec before it returns):
            # nothing reached herdr-core, the one local refusal that proves non-submission.
            self._close(UNCERTAIN, CANCELLED, reason="hc could not be started")
            raise Fail("hc could not be started, so nothing was sent. Nothing was started.")
        except OSError:
            r = types.SimpleNamespace(returncode=1, stdout="", stderr="hc's reply was lost")
        try:
            out = json.loads(r.stdout)
        except ValueError:
            out = None
        out = out if isinstance(out, dict) else {}
        if r.returncode == 0 and out.get("address"):
            self._close(UNCERTAIN, CONFIRMED, address=out["address"])
            return {**out, "launch": self.launch, "state": CONFIRMED}
        # A lost or failed reply: one look, for positive evidence only.
        found = labelled(self.launch)
        if len(found) == 1:
            self._close(UNCERTAIN, CONFIRMED, address=found[0], reconciled=True)
            return {**out, "address": found[0], "first_message": {"sent": False}, "launch": self.launch, "state": CONFIRMED,
                    "reconciled": True}
        # hc's own words are never repeated (they could carry an argv word or an environment value):
        # only how it ended.
        said = f"hc exited {r.returncode}" + ("" if (r.stdout or "").strip() else " with no reply")
        self._close(UNCERTAIN, UNCERTAIN, reply=said)
        e = Fail(f"hc didn't confirm this start ({said}), and it may have started anyway, so it is kept as launch "
                 f"{self.launch}, submission uncertain. Nothing will retry it. `herdr-task launch reconcile {self.identity} "
                 f"{self.launch}` confirms it once its terminal shows up. {HELD_UNCERTAIN}")
        e.launch = {"launch": self.launch, "identity": self.identity, "state": UNCERTAIN}
        raise e

    def _mark_sent(self, record=None):
        """The step before anything is sent: under the journal's lock the claim must still be this start's own (a
        recovery revokes it) and its revision unchanged; it is then recorded submission-uncertain (with record's
        facts). Settings changed meanwhile cancel it, and it refuses."""
        guard(["hc"])  # a refused environment sends nothing: refused while the claim is still unsent
        changed = False
        with journal() as d:
            rec = d["launches"].get(self.launch)
            if not rec or rec["state"] != NEVER or d["claims"].get(self.identity) != self.launch:
                raise Fail(REVOKED.format(self.launch))
            if self.fence:
                self.fence(d)
            if self.revise() != self.revision:
                rec.update(state=CANCELLED, reason="settings changed before it was sent", updated=now())
                d["claims"].pop(self.identity, None)
                changed = True
            else:
                rec.update(state=UNCERTAIN, sent_at=now(), updated=now(), **(record or {}))
        if changed:
            raise Fail(CHANGED.format("sent"))
        self.sent = True
        self._restore()

    def type_into(self, address, line, record=None, sender=None):
        """Revival's send (L2): the agent's command line typed into its own kept terminal (`hc send`), the same steps
        as submit() around it. hc's success confirms it (its terminal is the one it was typed into, so the claim is
        released at once); anything else keeps it submission uncertain under its launch id, since the line may have
        been pasted: nothing types it again until `launch reconcile` finds an agent running there. sender: what runs
        hc (revive's own run)."""
        self._mark_sent(dict(record or {}, terminal=address))
        try:
            r = (sender or run)(["hc", "send", address, line])
        except (FileNotFoundError, PermissionError):
            self._close(UNCERTAIN, CANCELLED, reason="hc could not be started")
            raise Fail("hc could not be started, so nothing was typed. Nothing was started.")
        except OSError:
            r = types.SimpleNamespace(returncode=1, stdout="", stderr="hc's reply was lost")
        if r.returncode == 0:
            self._close(UNCERTAIN, CONFIRMED, address=address)
            return {"launch": self.launch, "state": CONFIRMED, "address": address}
        said = f"hc exited {r.returncode}"
        self._close(UNCERTAIN, UNCERTAIN, reply=said)
        e = Fail(f"hc didn't confirm typing {self.who} back into {address} ({said}), and it may have been typed anyway, "
                 f"so it is kept as launch {self.launch}, submission uncertain. Nothing will type it again. "
                 f"`herdr-task launch reconcile {self.identity} {self.launch}` confirms it once an agent runs there. "
                 f"{HELD_UNCERTAIN}")
        e.launch = {"launch": self.launch, "identity": self.identity, "state": UNCERTAIN}
        raise e

    def _close(self, was, state, **facts):
        with journal() as d:
            rec = d["launches"].get(self.launch)
            if not rec or rec["state"] != was:
                return
            rec.update(state=state, updated=now(), **facts)
            # A confirmed task start keeps its claim until its task list records the agent (refuse_busy):
            # if this herdr-task ends before it saves, the next start finds it instead of starting again.
            held = state == CONFIRMED and isinstance(rec.get("task"), dict)
            if held:
                rec["recorded"] = False
            if state != UNCERTAIN and not held and d["claims"].get(self.identity) == self.launch:
                d["claims"].pop(self.identity, None)


def labelled(lid):
    """The terminals carrying launch id lid's label (positive evidence only; empty proves nothing)."""
    r = run(["hc", "ls", "--label", f"{LABEL}={lid}", "--json"])
    if r.returncode != 0:
        return []
    try:
        rows = json.loads(r.stdout).get("terminals") or []
    except (ValueError, AttributeError):
        return []
    return [k["address"] for k in rows if isinstance(k, dict) and k.get("address")]


def revived_in(rec):
    """A revival's positive evidence (launch reconcile): an agent runs now in the terminal its line was typed into.
    Empty proves nothing (the line may still be starting, or the terminal can't be read)."""
    from .agents import agent_running
    from .base import hc_json
    k = hc_json("get", rec["terminal"]) if rec.get("terminal") else None
    return [rec["terminal"]] if k and k.get("state") == "live" and agent_running(k) else []


def attach(rec):
    """A confirmed task start its own herdr-task never recorded (a lost reply reconciled later, or
    a crash after dispatch): its agent goes on its task once, as the start would have put it, and
    its watcher starts, so the task is never taken for unstarted and its session is recorded.
    Not redone: what its command did after the start (switch ending the old agent, a backup's
    state). True when it was put on now; refuses when the task or its folder has gone."""
    job = rec.get("task")
    if not isinstance(job, dict) or not rec.get("address"):
        return False
    from .store import Store, locate
    from .launch import track
    with Store(locate(job["folder"])) as s:
        t = s.find(str(job["id"]))
        if not put_on(t, rec):
            return False
        s.dirty = True
        if not job.get("role"):
            try:
                track(s, t, rec["address"])
            except OSError:
                pass
    return True


def config_dir_for(argv, prev=None):
    """The Claude Code folder a task's agent starts on, passed to it explicitly and recorded. After
    a previous Claude Code agent (switch, resume, a backup): its recorded folder, or None when it
    has none (started before L1, or on an inherited folder), so it inherits as it did and is never
    moved to the caller's profile. A first start: this herdr-task's CLAUDE_CONFIG_DIR when set,
    else None (the terminal's own environment decides, as before L1). As C1's rule
    (sessions.claude_dir): one absolute path, and no other folder called .claude. Codex and other
    CLIs: None."""
    if agent_key(argv) != "claude":
        return None
    if prev and prev.get("agent") == "claude":
        return prev.get("config_dir") or None
    v = os.environ.get("CLAUDE_CONFIG_DIR")
    if not v:
        return None
    path = v[:-1] if v.endswith("/") and len(v) > 1 else v
    if not path.startswith("/") or re.search(r"[\x00-\x1f\x7f]", path) or \
            (os.path.basename(path) == ".claude" and path != os.path.join(HOME, ".claude")):
        raise Fail(NO_CONFIG_DIR)
    return path


# ---- a task's agent ---------------------------------------------------------------------------

def task_identity(s, task, role=None):
    return f"task:{s.key(task)}" + (f"/{role}" if role else "")


KEEP = object()


def admit_task(s, task, argv, space, parent=None, role=None, select=None, resolve_parent=True, prev=None, folder=KEEP,
               repair=False, bound=None):
    """Preflight for a task's agent, before any effect: the settings read strictly, its plan (providers.py: a new
    conversation plans from today's settings, with the task's own save-only deployment when its CLI is the one chosen;
    a recorded conversation's resume, bound, plans from its recorded binding and refuses changed routing), its Claude
    Code folder (config_dir_for, carried from prev: the agent it follows), an earlier start still open, and its
    Assistant (parent_for: `parent` while live, else the space's). select: how its argv is chosen again from settings
    (None: argv was given as it is). folder: the one a queued plan kept (None: inherit), never this herdr-task's own;
    repair: see refuse_busy. The admission's plan is what the start composes and records (launch.launch)."""
    from .launch import parent_for
    from .settings import task_deployment
    identity = task_identity(s, task, role)
    folder = config_dir_for(argv, prev) if folder is KEEP else (folder if agent_key(argv) == "claude" else None)
    # A choice `select` saved (a deployment or a model, for this CLI) is for the task's first start only, and bound to the
    # routing it was made under. Later starts (resume, switch, --fresh, a backup) take today's settings or the record.
    first = not (role or bound is not None or task.get("agents"))
    chosen = task_deployment(task, agent_key(argv)) if first else None
    picked = task.get("selection_routing") if first and task.get("agent") == agent_key(argv) else None
    held = {}

    def revise():
        d = read_strict()
        if chosen or picked:
            # The task's choice was saved under one routing (select): under another it refuses, never runs elsewhere.
            from .providers import binding_for, selection_revision
            if task.get("selection_routing") != selection_revision(binding_for(s, space, d), agent_key(argv)):
                raise Fail(STALE_TASK_CHOICE.format(who=s.ref(task)))
        plan = admit_launch(s, argv, space, d, "worker", chosen, bound, s.ref(task))
        from .providers import binding_for
        held["plan"], held["binding"] = plan, binding_for(s, space, d)
        return digest({"role": role or "task", "route": plan["route"], "fingerprint": plan["fingerprint"], "argv": list(argv),
                       "selected": select() if select else None, "space": bare(space) if space else None,
                       "config_dir": folder, "bound": (bound or {}).get("fingerprint") if bound is not None else None})
    adm = Admission(identity, role or "task", bare(space) if space else None, None, revise, who=s.ref(task))
    # binding: the settings' routing it was planned under (a restart's new conversation is checked against it).
    adm.task, adm.config_dir, adm.plan, adm.binding = task, folder, held["plan"], held["binding"]
    # The argv chosen from settings a moment ago must still be what they choose: the revision binds both.
    if select and select() != list(argv):
        raise Fail(CHANGED.format("admitted"))
    open_start(identity, s.ref(task), task, repair)
    adm.parent = parent_for(parent, space) if resolve_parent else parent
    return adm


# ---- an Assistant's start (`herdr-task launch run`) -----------------------------------------

def assistant_identity(role, machine, space, slot=None):
    return f"{role}:{machine or 'local'}/{space}" + (f"/{slot}" if slot else "")


def space_scope(space, d):
    """A store-like scope for a space's settings: the space's own layer is the one settings_layers() picks for its
    folder; a space the file doesn't have gets a folder no layer has, so only Everywhere's and this machine's apply."""
    spaces = d.get("spaces") if isinstance(d.get("spaces"), dict) else {}
    entry = spaces.get(space)
    return types.SimpleNamespace(loc={"folder": entry.get("folder") if isinstance(entry, dict) else f"\0{space}"})


def space_binding(space):
    """The provider binding at a space, read strictly (the route a new start would plan on now)."""
    from .providers import binding_for
    d = read_strict()
    return binding_for(space_scope(space, d), space, d)


# ---- the agent already in a terminal (L2: revival and restart) ------------------------------------

def agent_identity(k):
    """The launch identity of the agent in terminal k (hc get's record): the one its own starts are claimed under, a
    task's agent (herdr.task; a reviewer's adds /reviewer) or an Assistant (coordinator:local/<its space>, as
    restart.sh names it). Revival is claimed under it too, so a revival and any start of the same agent fence each
    other in the journal: one owner, never two agents."""
    labels = k.get("labels") or {}
    if labels.get("herdr.task"):
        return f"task:{labels['herdr.task']}" + ("/reviewer" if labels.get("herdr.role") == "reviewer" else "")
    space = bare(str(labels.get("herdr.space") or labels.get("herdr.coordinator.space") or "")) or "unplaced"
    return assistant_identity("coordinator", None, space)


def read_resume(k):
    """The record revival keeps on terminal k (label herdr.resume, revive.py), or None."""
    try:
        rec = json.loads(((k.get("labels") or {}).get("herdr.resume")) or "null")
    except (ValueError, TypeError):
        return None
    return rec if isinstance(rec, dict) else None


def recorded_binding(k, task=None, resume=None):
    """The nonsecret provider binding the agent in terminal k started on (providers.recorded's shape), from the first
    owner that has it: its task's agent row (task: its task as read now), the copy revival keeps on its terminal
    (resume: its herdr.resume record), then its start's journal record (its herdr.launch label). An agent whose
    terminal says Personal (no herdr.provider label) with nothing else recorded is Personal. None when it started on
    another route and no record of it is found, or two owners disagree on the route: never read as Personal."""
    from .providers import PERSONAL_RECORD
    labels = k.get("labels") or {}
    route = labels.get("herdr.provider") or PERSONAL

    def fits(b):
        return isinstance(b, dict) and b.get("route") == route
    if task is not None:
        rows = (task.get("agents") or []) + (task.get("reviewers") or [])
        row = next((a for a in rows if a.get("address") == k.get("address")), None)
        if row is not None:
            b = row.get("provider") or dict(PERSONAL_RECORD)
            return b if fits(b) else None
    if isinstance(resume, dict) and resume.get("provider") is not None:
        return resume["provider"] if fits(resume["provider"]) else None
    lid = labels.get(LABEL)
    if route != PERSONAL and isinstance(lid, str) and LAUNCH_ID.fullmatch(lid):
        with journal() as d:
            rec = d["launches"].get(lid) or {}
        b = rec.get("provider") or ((rec.get("task") or {}).get("agent") or {}).get("provider")
        return b if fits(b) else None
    return dict(PERSONAL_RECORD) if route == PERSONAL else None


def admit_assistant_start(role, space, hc_args, slot=None, config_dir=None, argv=None, deployment=None, revision=None,
                          replaces=None):
    """Preflight for an Assistant's (role coordinator) or a tab agent's (role agent) start through hc_args, its `hc run`
    words. A new start (argv: the agent's own argv, `--new-start`) is planned: Personal as it always was, Azure
    Foundry for the Assistant's role here (providers.admit_assistant), and a chat's save-only choice (deployment)
    must still be on the routing it was chosen under (revision). A restart or a fork (replaces: the replaced or forked
    agent's recorded binding, route, argv and words, L2) continuing the same conversation plans from that binding, and
    one starting a new conversation plans from today's settings as a new start does (providers.admit_assistant). An
    earlier start of the same space (and slot) still open refuses."""
    machine = on_machine(hc_args)
    if machine is not None and not WORD.fullmatch(machine):
        raise Fail("`hc run --on` names a machine as a single word (letters, digits, dots, underscores, @ and dashes). "
                   "Nothing was started.")
    held = {}

    def revise():
        from .providers import binding_for, selection_revision
        d = read_strict()
        # The space's own layer is the one settings_layers() picks for its folder; a space the file
        # doesn't have gets a folder no layer has, so only Everywhere's and this machine's apply.
        s = space_scope(space, d)
        if revision and argv:
            now = selection_revision(binding_for(s, space, d), agent_key(argv))
            if now != revision:
                raise Fail(STALE_SELECTION.format(revision))
        plan = admit_assistant(s, space, d, machine, argv, deployment, replaces, tab=role == "agent")
        held["plan"] = plan
        return digest({"role": role, "route": plan["route"], "fingerprint": plan["fingerprint"], "space": space,
                       "machine": machine, "hc": list(hc_args), "argv": list(argv) if argv else None, "config_dir": config_dir,
                       "bound": ((replaces or {}).get("bound") or {}).get("fingerprint")})
    identity = assistant_identity(role, machine, space, slot)
    adm = Admission(identity, role, space, machine, revise)
    adm.config_dir, adm.plan = config_dir, held["plan"]
    open_start(identity)
    return adm


def cmd_launch(args):
    from .output import say
    if args.launch == "run":
        return launch_run(args, say)
    if args.launch == "folder":
        return launch_folder(args, say)
    if args.launch == "revive":
        from .revive import cmd_revive
        return cmd_revive(args, say)
    if args.launch == "status":
        if args.identity and not IDENTITY.fullmatch(args.identity):
            raise Fail("That isn't a launch identity: `herdr-task launch status` lists them.")
        with journal() as d:
            recs = [r for r in d["launches"].values() if not args.identity or r.get("identity") == args.identity]
            claims = dict(d["claims"])
            known = {r["launch"] for r in d["launches"].values()}
        rows = []
        for rec in recs:
            r = {k: v for k, v in rec.items() if k != "task"}
            # Claimed still: unresolved (never submitted, uncertain, or confirmed but not yet on its task). A confirmed
            # start whose task list holds it is resolved, though its claim waits for that task's next start.
            r["held"] = claims.get(rec["identity"]) == rec["launch"] and not (
                rec.get("state") == CONFIRMED and isinstance(rec.get("task"), dict) and on_its_task(rec))
            rows.append(r)
        # A claim whose record is gone: held, and shown, since nothing can say whether it was sent.
        rows += [{"identity": i, "launch": l, "state": "unknown", "held": True} for i, l in claims.items()
                 if l not in known and (not args.identity or i == args.identity)]
        rows.sort(key=lambda r: (not r["held"], -(r.get("at") or 0)))

        def line(r):
            w = f"{r['identity']} {r['launch']} {r['state']}" + (f" {r['address']}" if r.get("address") else "")
            if r["held"] and r["state"] == CONFIRMED:
                w += f": held, not yet on its task; `herdr-task launch reconcile {r['identity']} {r['launch']}` records it"
            elif r["held"] and r["state"] == "unknown":
                w += ": held, its record is gone; whether it was sent is unknown"
            elif r["held"]:
                w += ": held"
            return w
        return say(args, {"launches": rows}, "\n".join(map(line, rows)) or "No starts in the launch journal.")
    ident, lid = args.identity, args.id
    if not ident or not IDENTITY.fullmatch(ident) or not LAUNCH_ID.fullmatch(lid or ""):
        raise Fail("Give the start's exact identity and launch id, as `herdr-task launch status` shows them.")
    if args.launch == "reconcile":
        return reconcile(args, say, ident, lid)
    # recover: only a start that was never sent, which revokes its claim; its sender, if it still
    # runs, is fenced when it tries to send. A start that may have been sent can't be released.
    with journal() as d:
        rec = d["launches"].get(lid)
        if not rec or rec.get("identity") != ident:
            raise Fail(f"No start {lid} of {ident} in the launch journal.")
        if rec["state"] == UNCERTAIN:
            e = Fail(f"{ident} {lid} may have been sent (submission uncertain): herdr-core gives no receipt or revocation for "
                     f"an hc run, and an empty terminal list doesn't prove it never started, so it can't be released here. "
                     f"`herdr-task launch reconcile {ident} {lid}` confirms it once its terminal shows up. {HELD_UNCERTAIN} "
                     f"Nothing was changed.")
            e.launch = {"launch": lid, "identity": ident, "state": UNCERTAIN}
            raise e
        released = rec["state"] == NEVER and d["claims"].get(ident) == lid
        if released:
            rec.update(state=CANCELLED, revoked=True, reason="released by launch recover: never sent", updated=now())
            d["claims"].pop(ident, None)
        held = d["claims"].get(ident) == lid and not (isinstance(rec.get("task"), dict) and on_its_task(rec))
        out = {k: v for k, v in rec.items() if k != "task"}
    out["released"] = released
    if released:
        said = ": released, and its sender can no longer send it."
    elif out["state"] == CONFIRMED and held:
        said = (f": it was sent and confirmed, so there is nothing to release; its task doesn't hold it yet, and "
                f"`herdr-task launch reconcile {ident} {lid}` records it there.")
    else:
        said = ": nothing to release." + (" It was released earlier." if out.get("revoked") else "")
    say(args, out, f"{ident} {lid} is {out['state']}{said}")


def reconcile(args, say, ident, lid):
    """`launch reconcile`: a submission-uncertain start confirmed by exactly one terminal carrying
    its launch id, and a confirmed task start whose task list never recorded its agent put on its
    task (attach); its claim is released once the task holds it."""
    with journal() as d:
        rec = d["launches"].get(lid)
        if not rec or rec.get("identity") != ident:
            raise Fail(f"No start {lid} of {ident} in the launch journal.")
        state, held = rec["state"], d["claims"].get(ident) == lid
    if state == UNCERTAIN:
        found = revived_in(rec) if rec.get("revival") else labelled(lid)
        with journal() as d:
            rec = d["launches"][lid]
            if rec["state"] == UNCERTAIN and len(found) == 1:
                rec.update(state=CONFIRMED, address=found[0], reconciled=True, updated=now())
                if isinstance(rec.get("task"), dict):
                    rec["recorded"] = False
                elif d["claims"].get(ident) == lid:
                    d["claims"].pop(ident, None)
            state, held = rec["state"], d["claims"].get(ident) == lid
        if state != CONFIRMED:
            why = (f"{len(found)} terminals carry its launch id ({', '.join(found)})" if found else
                   f"no agent runs in {rec.get('terminal')}, which doesn't prove it was never typed there (herdr-core keeps "
                   f"no receipt)" if rec.get("revival") else
                   "no terminal carries its launch id, which doesn't prove it never started (herdr-core keeps no receipt)")
            e = Fail(f"{ident} {lid} stays submission uncertain: {why}. Nothing was started or released. {HELD_UNCERTAIN}")
            e.launch = {"launch": lid, "identity": ident, "state": UNCERTAIN}
            raise e
    elif not (state == CONFIRMED and held):
        hint = (f" It was never sent; if its herdr-task has ended, `herdr-task launch recover {ident} {lid}` releases it."
                if state == NEVER and held else "")
        return say(args, {k: v for k, v in rec.items() if k != "task"}, f"{ident} {lid} is {state}: nothing to reconcile.{hint}")
    # Confirmed, and its task may not hold its agent yet: put it there, then release the claim.
    with journal() as d:
        rec = dict(d["launches"][lid])
    gone = False
    try:
        attached = attach(rec)
    except Fail:
        attached, gone = False, True  # its task or folder has gone: nothing can start it again
    with journal() as d:
        if d["claims"].get(ident) == lid:
            d["claims"].pop(ident, None)
        d["launches"][lid].update(recorded=not gone, updated=now())
        out = {k: v for k, v in d["launches"][lid].items() if k != "task"}
    out["attached"] = attached
    said = (" Its task is gone, so it is on no task." if gone else " It is on its task now." if attached else "")
    say(args, out, f"{ident} {lid} confirmed: {out.get('address')} carries its launch id.{said}")


def launch_folder(args, say):
    """`launch folder PID`: the Claude Code folder process PID uses, read from its own environment
    (C1's rule, sessions.claude_dir), for restart.sh to carry into the agent it starts next."""
    from .sessions import claude_dir
    if not re.fullmatch(r"[1-9][0-9]{0,9}", args.identity or ""):
        raise Fail("Give the agent's process id.")
    folder = claude_dir(args.identity)
    if not folder:
        raise Fail("Can't read which Claude Code folder that agent uses (its environment isn't readable here, or "
                   "its CLAUDE_CONFIG_DIR isn't one absolute path), so a restart could start it on another profile. "
                   "Nothing was started.")
    say(args, {"folder": folder, "default": folder == os.path.join(HOME, ".claude")}, folder)


NOT_PLAIN = ("The {} template's command isn't one plain agent command (claude or codex and its words, nothing a shell "
             "expands, chains or redirects), so an Azure Foundry plan can't be applied to it. Nothing was started.")


def read_template(name):
    """(command, body) of a herdr-core template on this machine; refuses when it can't be read."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", name or ""):
        raise Fail("--source names a template (letters, digits, dots, dashes and underscores).")
    try:
        with open(os.path.join(TEMPLATES_DIR, f"{name}.md")) as f:
            text = f.read()
    except OSError:
        raise Fail(f"The {name} template can't be read on this machine, so its start can't be planned. Nothing was started.")
    head = re.match(r"^---\n([\s\S]*?)\n---\n?", text)
    m = re.search(r"^command:[ \t]*(.+)$", head.group(1), re.M) if head else None
    return (m.group(1).strip() if m else None), (text[head.end():] if head else text)


def template_argv(name, command):
    """The agent argv in a template's command line: its words when they are one plain claude or codex command."""
    import shlex
    cmd = re.sub(r"^exec\s+", "", command or "")
    if not cmd or re.search(r"[;&|<>`$()\n\\]", cmd):
        raise Fail(NOT_PLAIN.format(name))
    try:
        words = shlex.split(cmd)
    except ValueError:
        raise Fail(NOT_PLAIN.format(name))
    if not words or agent_key(words) not in ("claude", "codex"):
        raise Fail(NOT_PLAIN.format(name))
    return words


def one_line_word(a):
    """One argv word as POSIX shell words on a single line (a template's command is one line): quoted as it is, or one
    holding a newline (a lost session's first message) rebuilt by printf in place, the same word, never split."""
    import shlex
    if "\n" not in a:
        return shlex.quote(a)
    fmt = a.replace("\\", "\\\\").replace("%", "%%").replace("'", "'\\''").replace("\n", "\\n")
    return f'"$(printf \'{fmt}\')"'


def write_one_off(source, body, argv, env, need, lid, config_dir=None):
    """An owner-written one-off template for an Azure Assistant start: the source template's words, and a command
    that clears a parent Claude Code session's markers (launch.CLEAN_ENV), exports the plan's nonsecret variables (and
    config_dir, the Claude Code folder a restart carries, as CLAUDE_CONFIG_DIR), starts the agent only when its
    credential variable is set (launch.provider_words), then execs the planned argv. Named for its launch; removed once
    hc has run. Gives its name."""
    import shlex
    from .launch import CLEAN_ENV, provider_words
    before, after = provider_words(env, need)
    if config_dir:
        before = f"export CLAUDE_CONFIG_DIR={shlex.quote(config_dir)}; {before}"
    words = " ".join(one_line_word(a) for a in argv)
    command = f"{CLEAN_ENV} {before}exec {words}; {after}exit 1" if after else f"{CLEAN_ENV} {before}exec {words}"
    name = f"herdr-{source}-az-{lid[:8]}"
    text = (f"---\nname: {name}\ndescription: A one-off Azure Foundry {source} start (herdr-task launch run), removed "
            f"after use.\ncommand: {command}\n---\n{body}")
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    path = os.path.join(TEMPLATES_DIR, f"{name}.md")
    with open(path, "w") as f:
        f.write(text)
    return name, path


def launch_run(args, say):
    """`launch run`: an Assistant's or a tab agent's start, admitted, claimed, sent and confirmed
    here; the hc run words after "--" are its start site's own, given the launch's label and
    --json. A new start (--new-start WORD: the template word its hc words name) is planned: on
    Azure Foundry the owner writes its own one-off template from --source's words and the planned
    argv (--argv, else --source's command), puts it in WORD's place, labels the start with its
    route and records its binding. --replaces: the terminal of the agent a restart replaces (L2):
    continuing its conversation plans from its recorded binding (recorded_binding), a new one from
    today's settings; on Azure the restart's own one-off is WORD (--new-start) and --argv its argv."""
    from .providers import compose, recorded, resumes
    words = list(args.hc_args or [])
    if words[:1] == ["--"]:
        words = words[1:]
    space = bare(args.space or "")
    if args.role not in ROLES:
        raise Fail("--role is coordinator or agent.")
    if not WORD.fullmatch(space):
        raise Fail("--space names the space it starts in.")
    if args.role == "agent" and not (args.slot and SLOT.fullmatch(args.slot)):
        raise Fail("A tab agent's start names its tab: --slot.")
    folder = args.config_dir or None
    if folder and (not folder.startswith("/") or re.search(r"[\x00-\x1f\x7f]", folder)):
        raise Fail("--config-dir is the absolute Claude Code folder its start carries.")
    # The same refusals for --check as for the run: words that carry its own launch label, or name a machine
    # (--on) that can't be an identity, refuse either way; only the run needs words at all.
    if any(a.startswith((f"{LABEL}=", f"--label={LABEL}=", "herdr.provider=", "--label=herdr.provider="))
           for a in options_of(words)):
        raise Fail("A start's launch and provider labels are the launch owner's own: leave them out.")
    new = getattr(args, "new_start", None)
    old = getattr(args, "replaces", None)
    if old is not None and not SLOT.fullmatch(old):
        raise Fail("--replaces names the terminal of the agent a restart replaces.")
    if (getattr(args, "deployment", None) or getattr(args, "revision", None)) and not new:
        raise Fail("--deployment and --revision are for a new start (--new-start).")
    if getattr(args, "argv", None) and not (new or old):
        raise Fail("--argv is for a new start (--new-start) or a restart (--replaces).")
    if new and args.role != "coordinator":
        raise Fail("A new start's plan is an Assistant's (--role coordinator).")
    argv = None
    source = getattr(args, "source", None) or "assistant"
    if new or old:
        if getattr(args, "argv", None):
            try:
                argv = json.loads(args.argv)
            except ValueError:
                argv = None
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                raise Fail("--argv is the agent's argv as a JSON list of words.")
    # The agent a restart replaces (L2): the binding its start recorded (its task's row, revival's copy on its terminal
    # or its start's journal record), which continuing its conversation keeps. A terminal that can't be read refuses:
    # its binding is never guessed.
    replaces = None
    if old is not None:
        from .base import hc_json
        k = hc_json("get", old)
        if not isinstance(k, dict):
            raise Fail(f"The agent this restart replaces ({old}) can't be read, so the binding it started on can't be "
                       f"known. Nothing was started or changed.")
        replaces = {"bound": recorded_binding(k, None, read_resume(k)), "who": f"The agent in {old}",
                    "continues": bool(getattr(args, "continues", False)),
                    "route": (k.get("labels") or {}).get("herdr.provider") or PERSONAL,
                    "argv": (k.get("foreground") or {}).get("argv") or k.get("argv") or []}
    if not args.check and not words:
        raise Fail("Give the hc run words after \"--\".")
    # An Azure new start without its own argv runs its source template's command, planned; a Personal one keeps
    # its words as they are, so its template isn't read.
    if new and argv is None and on_machine(words) is None and space_binding(space)["route"] == AZURE:
        argv = template_argv(source, read_template(source)[0])
    adm = admit_assistant_start(args.role, space, words, args.slot if args.role == "agent" else None, folder,
                                (argv or ["claude"]) if new else argv, getattr(args, "deployment", None),
                                getattr(args, "revision", None), replaces)
    azure = adm.plan["route"] == AZURE
    if azure and argv is None:
        # The route read Personal when the template was skipped and Azure at admission: settings changed between the
        # two reads. Refused before anything is claimed or sent, never planned on a stand-in argv (--check too).
        raise Fail(CHANGED.format("planned"))
    if args.check:
        # Preflight only, before the start site changes anything: its route and an earlier start still open.
        return say(args, {"admitted": True, "identity": adm.identity, "route": adm.plan["route"]}, f"{adm.identity}: admitted.")
    if azure and not new:
        # A restart (restart.sh) gives its one-off template's word only once its check said Azure: Personal there and
        # Azure now means the settings changed between the two. Refused before anything is claimed or sent.
        raise Fail(CHANGED.format("planned"))
    if azure and words.count(new) != 1:
        raise Fail("--new-start names the template word its hc run words give once. Nothing was started.")
    made = None
    try:
        with adm.claimed():
            sent = list(words)
            extra = adm.label() + ([] if "--json" in options_of(words) else ["--json"])
            if azure:
                cmd, env = compose(adm.plan, argv)
                made = write_one_off(source, read_template(source)[1], cmd, env, adm.plan.get("credential"), adm.launch,
                                     folder)
                sent[sent.index(new)] = made[0]
                extra += ["--label", f"herdr.provider={adm.plan['route']}"]
            facts = {"provider": recorded(adm.plan)} if azure else {}
            if replaces and replaces["continues"] and not resumes(argv or []):
                # A lost session started anew behind its chat: missing history, said so, never a resume (L2).
                facts["missing_history"] = True
            out = adm.submit(["run", *extra, *sent], record=facts or None)
    finally:
        if made:
            try:
                os.remove(made[1])
            except OSError:
                pass
    say(args, out, out["address"])
