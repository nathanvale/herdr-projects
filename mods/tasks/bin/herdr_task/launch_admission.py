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

from .base import Fail, guard, now, run, STORE
from .providers import admit_assistant, admit_launch, read_strict
from .settings import bare

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
          "Nothing was started; move it aside only once every start it names is known.")
SHUTDOWN = "stopped before it was sent ({})"


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
                f"Nothing was started. `herdr-task launch status {identity}` shows it.")
    if rec["state"] == NEVER:
        return (f"{who} is already starting (launch {lid}, claimed and not sent). Nothing was started. If that start's "
                f"herdr-task has ended, release it with `herdr-task launch recover {identity} {lid}`.")
    return (f"{who}'s last start ({lid}) may have started an agent that no reply confirmed (submission uncertain). Nothing "
            f"was started or retried. `herdr-task launch reconcile {identity} {lid}` looks for its terminal.")


def refuse_busy(d, identity, who=None):
    lid = d["claims"].get(identity)
    if not lid:
        return
    rec = d["launches"].get(lid)
    if rec and rec.get("state") not in OPEN:
        return
    raise Fail(busy_words(identity, rec, lid, who))


def open_start(identity, who=None):
    """Refuses while `identity` has an unresolved start (preflight's look, before any effect)."""
    with journal() as d:
        refuse_busy(d, identity, who)


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
            refuse_busy(d, self.identity, self.who)
            d["launches"][lid] = {"launch": lid, "identity": self.identity, "role": self.role, "state": NEVER, "at": now(),
                                  "updated": now(), "revision": self.revision, "space": self.space,
                                  "machine": self.machine or "local", "parent": self.parent, "pid": os.getpid()}
            d["claims"][self.identity] = lid
        self.launch = lid
        old = {}

        def stop(sig, _frame):
            raise SystemExit(128 + sig)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            try:
                old[sig] = signal.signal(sig, stop)
            except (ValueError, OSError):
                pass
        try:
            yield self
        except BaseException as e:
            why = str(e) if isinstance(e, Fail) else SHUTDOWN.format(type(e).__name__)
            self.cancel(why[:300])
            raise
        finally:
            for sig, h in old.items():
                if h is not None:  # a handler not set from Python can't be put back from here
                    signal.signal(sig, h)

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

    def submit(self, hc_args, parent_live=None):
        """Sends the start: `hc` with hc_args (they carry label()). Before it, its Assistant must
        still be live (parent_live), and under the journal's lock its claim must still be its own
        and its revision unchanged; it is then recorded submission-uncertain and hc runs next.
        Returns hc's reply as {address, ...} once confirmed; refuses, keeping it uncertain, when
        no terminal is known to carry its launch id."""
        if self.parent and parent_live and not parent_live(self.parent):
            raise Fail(PARENT_CHANGED.format(self.parent))
        guard(["hc"])  # a refused environment sends nothing: refused while the claim is still unsent
        changed = False
        with journal() as d:
            rec = d["launches"].get(self.launch)
            if not rec or rec["state"] != NEVER or d["claims"].get(self.identity) != self.launch:
                raise Fail(REVOKED.format(self.launch))
            if self.revise() != self.revision:
                rec.update(state=CANCELLED, reason="settings changed before it was sent", updated=now())
                d["claims"].pop(self.identity, None)
                changed = True
            else:
                rec.update(state=UNCERTAIN, sent_at=now(), updated=now())
        if changed:
            raise Fail(CHANGED.format("sent"))
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
        said = ((r.stderr or r.stdout or "").strip().splitlines() or ["no reply"])[-1][:200]
        self._close(UNCERTAIN, UNCERTAIN, reply=said)
        e = Fail(f"hc didn't confirm this start ({said}), and it may have started anyway, so it is kept as launch "
                 f"{self.launch}, submission uncertain. Nothing will retry it. `herdr-task launch reconcile {self.identity} "
                 f"{self.launch}` confirms it once its terminal shows up.")
        e.launch = {"launch": self.launch, "identity": self.identity, "state": UNCERTAIN}
        raise e

    def _close(self, was, state, **facts):
        with journal() as d:
            rec = d["launches"].get(self.launch)
            if not rec or rec["state"] != was:
                return
            rec.update(state=state, updated=now(), **facts)
            if state != UNCERTAIN and d["claims"].get(self.identity) == self.launch:
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


# ---- a task's agent ---------------------------------------------------------------------------

def task_identity(s, task, role=None):
    return f"task:{s.key(task)}" + (f"/{role}" if role else "")


def admit_task(s, task, argv, space, parent=None, role=None, select=None, resolve_parent=True):
    """Preflight for a task's agent, before any effect: the settings read strictly, its route
    (providers.py: Personal passes, Azure is held, anything unsupported refuses), an earlier start
    still open, and its Assistant (parent_for: `parent` while live, else the space's). select:
    how its argv is chosen again from settings (None: argv was given as it is)."""
    from .launch import parent_for
    identity = task_identity(s, task, role)

    def revise():
        d = read_strict()
        plan = admit_launch(s, argv, space, d)
        return digest({"role": role or "task", "route": plan["route"], "fingerprint": plan["fingerprint"],
                       "argv": select() if select else list(argv), "space": bare(space) if space else None})
    adm = Admission(identity, role or "task", bare(space) if space else None, None, revise, who=s.ref(task))
    open_start(identity, s.ref(task))
    adm.parent = parent_for(parent, space) if resolve_parent else parent
    return adm


# ---- an Assistant's start (`herdr-task launch run`) -----------------------------------------

def assistant_identity(role, machine, space, slot=None):
    return f"{role}:{machine or 'local'}/{space}" + (f"/{slot}" if slot else "")


def admit_assistant_start(role, space, hc_args, slot=None):
    """Preflight for an Assistant's (role coordinator) or a tab agent's (role agent) start through
    hc_args, its `hc run` words: only Personal is admitted (its start sites can't apply a plan),
    here or on the machine its --on names; an earlier start of the same space (and slot) still
    open refuses."""
    machine = on_machine(hc_args)

    def revise():
        d = read_strict()
        # The space's own layer is the one settings_layers() picks for its folder; a space the file
        # doesn't have gets a folder no layer has, so only Everywhere's and this machine's apply.
        spaces = d.get("spaces") if isinstance(d.get("spaces"), dict) else {}
        entry = spaces.get(space)
        folder = entry.get("folder") if isinstance(entry, dict) else f"\0{space}"
        route = admit_assistant(types.SimpleNamespace(loc={"folder": folder}), space, d, machine)
        return digest({"role": role, "route": route, "space": space, "machine": machine, "hc": list(hc_args)})
    identity = assistant_identity(role, machine, space, slot)
    adm = Admission(identity, role, space, machine, revise)
    open_start(identity)
    return adm


def cmd_launch(args):
    from .output import say
    if args.launch == "run":
        return launch_run(args, say)
    if args.launch == "status":
        if args.identity and not IDENTITY.fullmatch(args.identity):
            raise Fail("That isn't a launch identity: `herdr-task launch status` lists them.")
        with journal() as d:
            rows = sorted((r for r in d["launches"].values() if not args.identity or r.get("identity") == args.identity),
                          key=lambda r: (r.get("state") not in OPEN, -(r.get("at") or 0)))
        text = "\n".join(f"{r['identity']} {r['launch']} {r['state']}" + (f" {r['address']}" if r.get("address") else "")
                         for r in rows) or "No starts in the launch journal."
        return say(args, {"launches": rows}, text)
    ident, lid = args.identity, args.id
    if not ident or not IDENTITY.fullmatch(ident) or not LAUNCH_ID.fullmatch(lid or ""):
        raise Fail("Give the start's exact identity and launch id, as `herdr-task launch status` shows them.")
    if args.launch == "reconcile":
        with journal() as d:
            rec = d["launches"].get(lid)
            if not rec or rec.get("identity") != ident:
                raise Fail(f"No start {lid} of {ident} in the launch journal.")
            state = rec["state"]
        if state != UNCERTAIN:
            return say(args, {**rec}, f"{ident} {lid} is {state}: nothing to reconcile.")
        found = labelled(lid)
        with journal() as d:
            rec = d["launches"][lid]
            if rec["state"] == UNCERTAIN and len(found) == 1:
                rec.update(state=CONFIRMED, address=found[0], reconciled=True, updated=now())
                if d["claims"].get(ident) == lid:
                    d["claims"].pop(ident, None)
            out = dict(rec)
        if out["state"] == CONFIRMED:
            return say(args, out, f"{ident} {lid} confirmed: its terminal {found[0]} carries its launch id.")
        why = (f"{len(found)} terminals carry its launch id ({', '.join(found)})" if found else
               "no terminal carries its launch id, which doesn't prove it never started (herdr-core keeps no receipt)")
        e = Fail(f"{ident} {lid} stays submission uncertain: {why}. Nothing was started or released.")
        e.launch = {"launch": lid, "identity": ident, "state": UNCERTAIN}
        raise e
    # recover: only a start that was never sent, which revokes its claim; its sender, if it still
    # runs, is fenced when it tries to send. A start that may have been sent can't be released.
    with journal() as d:
        rec = d["launches"].get(lid)
        if not rec or rec.get("identity") != ident:
            raise Fail(f"No start {lid} of {ident} in the launch journal.")
        if rec["state"] == UNCERTAIN:
            e = Fail(f"{ident} {lid} may have been sent (submission uncertain): herdr-core gives no receipt or revocation for "
                     f"an hc run, and an empty terminal list doesn't prove it never started, so it can't be released here. "
                     f"`herdr-task launch reconcile {ident} {lid}` confirms it once its terminal shows up; releasing it "
                     f"without that is a decision this version leaves to the person. Nothing was changed.")
            e.launch = {"launch": lid, "identity": ident, "state": UNCERTAIN}
            raise e
        if rec["state"] == NEVER and d["claims"].get(ident) == lid:
            rec.update(state=CANCELLED, revoked=True, reason="released by launch recover: never sent", updated=now())
            d["claims"].pop(ident, None)
        out = dict(rec)
    say(args, out, f"{ident} {lid} is {out['state']}" + (": released, and its sender can no longer send it." if out.get("revoked") else "."))


def launch_run(args, say):
    """`launch run`: an Assistant's or a tab agent's start, admitted, claimed, sent and confirmed
    here; the hc run words after "--" are its start site's own, given the launch's label and
    --json."""
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
    if args.check:
        # Preflight only, before the start site changes anything: its route and an earlier start still open.
        adm = admit_assistant_start(args.role, space, words, args.slot if args.role == "agent" else None)
        return say(args, {"admitted": True, "identity": adm.identity}, f"{adm.identity}: admitted.")
    if not words:
        raise Fail("Give the hc run words after \"--\".")
    if any(a.startswith(f"{LABEL}=") or a.startswith(f"--label={LABEL}=") for a in options_of(words)):
        raise Fail("A start's launch label is the launch owner's own: leave it out.")
    adm = admit_assistant_start(args.role, space, words, args.slot if args.role == "agent" else None)
    with adm.claimed():
        extra = adm.label() + ([] if "--json" in options_of(words) else ["--json"])
        out = adm.submit(["run", *extra, *words])
    say(args, out, out["address"])
