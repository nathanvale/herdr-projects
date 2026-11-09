"""Agents come back after a crash, a power loss or a reboot (SHEP-30), through launch admission (L2).

herdr-core keeps a kept terminal (hc run --keep) through a lost program, but never runs it again:
the terminal comes back with its labels and a plain shell (its argv becomes that shell, its
template goes). So while an Assistant or a task's agent runs, each tick here records on its
terminal (label herdr.resume) how to start it again on its own session: the agent's flags, the
exact session id and log (session_of(), as the chat finds them), its Claude Code folder when it
isn't ~/.claude, an Assistant's provider binding (a task's stays on its task) and the terminal's
own process. A terminal whose process changed since (the core gave it a new shell) and where no
agent runs now gets its agent typed back into that shell: the same terminal, labels, chat and
task, resuming that very session on the binding it recorded (providers.plan_of_record: the same
route, resource or endpoint, sign-in and deployment, or held with the reason; never Personal in
its place). Its session gone (no log, or the CLI says "No conversation found"): a new conversation
starts there with a short handover (as the chat's lostSession), on the same binding, reported as
missing history and never as a resume.

Each typing is a start in launch admission's journal under the agent's own identity
(launch_admission.agent_identity): claimed before anything is typed, recorded submission-uncertain
before `hc send`, confirmed by hc's success. So a revival and any start of the same agent (a task's
resume, restart.sh) fence each other, a send hc doesn't confirm is never typed again until
`launch reconcile` finds an agent running there, and an open start of that agent holds it. Each
machine's tick does its own terminals only, under the tick's lock; the service's and the window's
lost-session recovery come through `herdr-task launch revive TERMINAL --lost` (cmd_revive), the
same owner, so one agent never comes back twice."""

import json
import os
import re
import shlex

from .base import Fail, HOME, hc_json, now, run, SHELLS
from .agents import agent_running, status_word
from .sessions import claude_dir, session_of
from .settings import ASSISTANT_TEMPLATES, bare
from .launch import CLEAN_ENV, NO_CREDENTIAL

LABEL = "herdr.resume"
# Claude Code: "No conversation found with session ID: …". Codex: "ERROR: No saved session found with ID …"
# (core/chat-view.js LOST).
LOST = re.compile(r"\bno (?:saved )?(?:conversation|session|rollout)\b.*\bfound\b|\b(?:conversation|session)\b.*\bnot found\b", re.I)
# What a new agent hears when its earlier session is gone (core/chat-view.js FRESH and lostMessage).
FRESH = ("Your earlier session is gone, so this is a new one that remembers none of it. Check what is already here "
         "and preserve existing work.")
# What a resumed agent hears when the restart cut its turn short.
CUT = ("Herdr restarted (a crash, power loss or reboot) while you were working, and your session is resumed. "
       "Carry on where you left off.")
# A resume that fails within this long is looked at once more (its screen says why).
LOOK_MS = 10 * 60000

# Flags whose next word is their value (core/agents.js CLAUDE_VALUE, CODEX_VALUE), so it isn't taken
# for a first message.
CLAUDE_VALUE = {"--add-dir", "--mcp-config", "--append-system-prompt", "--system-prompt", "--allowedTools", "--allowed-tools",
                "--disallowedTools", "--disallowed-tools", "--agent", "--agents", "--plugin-dir", "--fallback-model",
                "--output-format", "--input-format", "--name", "--setting-sources", "--betas", "--debug-file",
                "--model", "--effort", "--settings", "--permission-mode"}
CODEX_VALUE = {"-c", "--config", "-m", "--model", "-p", "--profile", "-s", "--sandbox", "-a", "--ask-for-approval",
               "-C", "--cd", "--add-dir", "-i", "--image", "--enable", "--disable", "--local-provider", "--oss"}


def kind_of(word):
    b = os.path.basename(str(word))
    return b if b in ("claude", "codex") else None


def base_argv(argv):
    """(kind, argv) for starting the agent in `argv` again: from its claude or codex word on, without
    what resumed a conversation or its first message (core/agents.js freshArgv), or (None, None)."""
    argv = list(argv or [])
    at = next((i for i, a in enumerate(argv) if (i == 0 or not str(a).startswith("-")) and kind_of(a)), None)
    if at is None:
        return None, None
    kind, rest, out = kind_of(argv[at]), argv[at + 1:], [argv[at]]
    i = 0
    while i < len(rest):
        a = rest[i]
        if kind == "claude":
            if a in ("--resume", "-r", "--session-id"):
                i += 2 if i + 1 < len(rest) and not rest[i + 1].startswith("-") else 1
                continue
            if re.match(r"^--(resume|session-id)=", a) or a in ("--continue", "-c", "--fork-session"):
                i += 1
                continue
            if a in CLAUDE_VALUE and i + 1 < len(rest):
                out += [a, rest[i + 1]]
                i += 2
                continue
        else:
            if i == 0 and a in ("resume", "fork"):
                i += 2 if i + 1 < len(rest) and not rest[i + 1].startswith("-") else 1
                continue
            if a == "--last":
                i += 1
                continue
            if a in CODEX_VALUE and i + 1 < len(rest):
                out += [a, rest[i + 1]]
                i += 2
                continue
        # A word that isn't a flag or a flag's value: a session's id or a first message.
        if a.startswith("-"):
            out.append(a)
        i += 1
    return kind, out


def resume_argv(kind, argv, session, message=None):
    """argv (base_argv's) resuming `session`, with a first message when given."""
    tail = [message] if message else []
    if kind == "claude":
        return [*argv, "--resume", session, *tail]
    return [argv[0], "resume", *argv[1:], session, *tail]


def lost_message(ref=None, template=None):
    """A new agent's first message once its session is gone (core/chat-view.js lostMessage)."""
    msg = f"<restart>{FRESH}</restart>"
    if ref:
        msg += f"\n\nYou work on task {ref}: read its brief with `herdr-task show {ref}` and carry on from what is already done."
    body = "---".join(re.split(r"^---[ \t]*$", template or "", flags=re.M)[2:]).strip()
    if body:
        msg += f"\n\n{body}"
    return msg


LINE_SHELLS = ("bash", "zsh", "sh", "dash", "ksh", "fish")


def shell_line(shell, cwd, env, argv, direct=False, need=None):
    """The line typed into the recovered shell: into the agent's folder, then the agent. POSIX shells
    and fish (3.1+) take `&&` and VAR=value before a command; others get the agent alone (plan()
    holds an agent whose binding or folder needs more). `direct`: it started without the person's
    shell, so their aliases and functions (a claude() adding flags) stay out now too (`command`).
    need: an Azure plan's credential variable: the agent starts only when it is set and not empty,
    else the shell says which (launch.provider_words' check, typed)."""
    words = " ".join(shlex.quote(str(a)) for a in argv)
    if os.path.basename(shell or "") not in LINE_SHELLS:
        return words
    if direct:
        words = f"command {words}"
    pre = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in sorted((env or {}).items()))
    cmd = f"{pre} {words}" if pre else words
    if need and re.fullmatch(r"[A-Z][A-Z0-9_]*", need):
        said = shlex.quote(NO_CREDENTIAL.format(need))
        cmd = (f'if test -n "${need}"; {cmd}; else; echo {said} >&2; end' if os.path.basename(shell) == "fish" else
               f'if [ -z "${{{need}:-}}" ]; then printf "%s\\n" {said} >&2; else {cmd}; fi')
    line = f"cd {shlex.quote(cwd)} && {cmd}" if cwd else cmd
    # The recovered shell has the holder's environment: clear a parent Claude Code session's markers
    # first (SHEP-86, launch.CLEAN_ENV; POSIX shells: fish has no for-in-do).
    return line if os.path.basename(shell or "") == "fish" else f"{CLEAN_ENV} {line}"


def read_record(k):
    try:
        rec = json.loads(((k.get("labels") or {}).get(LABEL)) or "null")
    except ValueError:
        return None
    return rec if isinstance(rec, dict) else None


def write_record(k, rec):
    return run(["hc", "label", k["address"], f"{LABEL}={json.dumps(rec, separators=(',', ':'))}"]).returncode == 0


def watched(k):
    """An Assistant or a task's agent (its worker or reviewer): what comes back."""
    labels = k.get("labels") or {}
    return labels.get("herdr.role") == "coordinator" or k.get("template") in ASSISTANT_TEMPLATES or bool(labels.get("herdr.task"))


def task_ref(k):
    """A task agent's task id (herdr-task names its agents shep-30-fix-login)."""
    m = re.match(r"^([a-z][a-z0-9]*)-(\d+)(?:-|$)", k.get("name") or "")
    return f"{m.group(1).upper()}-{m.group(2)}" if m and (k.get("labels") or {}).get("herdr.task") else None


def env_of(k):
    """What the agent's launch set besides its argv: a task's browser (launch.launch)."""
    key = (k.get("labels") or {}).get("herdr.task")
    return {"HERDR_BROWSER_TASK": key} if key else {}


def record_of(k):
    """How to start the running agent in `k` again on its own session, or None."""
    fg = k.get("foreground") or {}
    pid = fg.get("pid")
    if not pid:
        return None
    # Its launch argv says how it started (in the person's shell, as a task's agent, or not); one typed
    # into a shell (argv: the shell) has only its process's.
    kind, argv = base_argv(k.get("argv"))
    launch = k.get("argv") or []
    shell = any(os.path.basename(str(a)) in SHELLS for a in launch[:launch.index(argv[0])]) if kind else True
    if not kind:
        kind, argv = base_argv(fg.get("argv"))
        if kind:
            argv[0] = kind
    if not kind:
        return None
    # Its Claude Code folder, read from its own process (C1's rule): revival carries it, so a session under another
    # folder is recorded too (L2). Unreadable records nothing, as before: it could come back on another profile.
    folder = claude_dir(pid) if kind == "claude" else None
    other = folder if folder and folder != os.path.join(HOME, ".claude") else None
    sid, log = session_of(pid, any_folder=True) if other else session_of(pid)
    if not sid:
        return None
    rec = {"kind": kind, "session": sid, "log": log, "argv": argv, "cwd": fg.get("cwd") or k.get("cwd"),
           "pid": k.get("pid"), "working": status_word(k) in ("working", "blocked"), "shell": shell}
    if other:
        rec["config_dir"] = other
    return rec


def task_of(k):
    """A task agent's task (read only), or None (gone, archived)."""
    from .store import read_list
    from .base import STORE
    key = (k.get("labels") or {}).get("herdr.task") or ""
    slug, _, n = key.rpartition("#")
    d = read_list(os.path.join(STORE, slug + ".json")) if slug and n.isdigit() else None
    return next((t for t in (d or {}).get("tasks") or [] if t.get("id") == int(n)), None)


def task_record(k, t):
    """A task agent with no record of its own: the session its task recorded (sessions.refresh_sessions)."""
    from .launch import own_argv
    a = next((a for a in (t.get("agents") or []) + (t.get("reviewers") or []) if a.get("address") == k["address"]), None)
    kind, argv = base_argv((a or {}).get("argv"))
    if not kind:
        return None
    if (k.get("labels") or {}).get("herdr.role") != "reviewer":
        argv = own_argv(argv)
    rec = {"kind": kind, "session": a.get("session"), "log": a.get("log"), "argv": argv, "cwd": k.get("cwd"),
           "pid": None, "working": t.get("state") == "running", "shell": True}
    if a.get("config_dir"):
        rec["config_dir"] = a["config_dir"]
    return rec


def template_of(name="assistant"):
    """(command, text) of a herdr-core template on this machine."""
    try:
        with open(os.path.join(HOME, ".config", "herdr-core", "templates", f"{name}.md")) as f:
            text = f.read()
    except OSError:
        return None, None
    head = re.match(r"^---\n([\s\S]*?)\n---", text)
    m = re.search(r"^command:[ \t]*(.+)$", head.group(1), re.M) if head else None
    cmd = re.sub(r"^exec\s+", "", m.group(1).strip()) if m else None
    return cmd, text


def space_of(labels):
    space = labels.get("herdr.task.space") or labels.get("herdr.space") or labels.get("herdr.coordinator.space")
    return bare(str(space)) if space else ""


def who_of(k):
    ref = task_ref(k)
    labels = k.get("labels") or {}
    if ref:
        return f"{ref}'s agent ({k['address']})"
    if labels.get("herdr.task"):
        return f"The task agent in {k['address']}"
    if labels.get("herdr.role") == "coordinator" or k.get("template") in ASSISTANT_TEMPLATES:
        return f"The Assistant in {k['address']}"
    return f"The agent in {k['address']}"


UNREAD, FIND = object(), object()


def binding_here(k, rec, task, kind, bound=FIND):
    """The plan the agent in k comes back on (L2): the binding its start recorded (launch_admission.recorded_binding:
    its task's row, the copy on its terminal, its start's journal record), rebuilt by the provider owner against the
    settings at its space now (providers.plan_of_record: the same route, resource or endpoint and sign-in; the recorded
    deployment kept). UNREAD when the settings file can't be read now (it may be mid-write: the next tick looks
    again); a Fail with the reason when it can't come back on that binding (held, never started on another). bound: the
    recorded binding found already (planning finds it once, as it may read the launch journal: the recheck under the
    journal's lock must not open it again)."""
    from .launch_admission import NO_BINDING, recorded_binding, space_scope
    from .providers import binding_for, plan_of_record, read_strict
    labels = k.get("labels") or {}
    space = space_of(labels)
    # One read, used for every answer: a second read landing mid-write could never be told from a lasting fault.
    try:
        d = read_strict()
    except Fail:
        return UNREAD
    if bound is FIND:
        bound = recorded_binding(k, task, rec)
    if bound is None:
        raise Fail(NO_BINDING.format(who=who_of(k)))
    return plan_of_record(bound, binding_for(space_scope(space, d), space, d), kind, who_of(k))


def shell_of(k):
    """The shell a line typed into k runs in: the terminal's foreground program when it is a shell (what the core gave
    it, or the person's own after an agent's launch shell exec'd it), else its launch's first word."""
    fg = os.path.basename((k.get("foreground") or {}).get("name") or "")
    return fg if fg in SHELLS else os.path.basename(str((k.get("argv") or [""])[0]))


def restarted(k):
    """A terminal the core gave a new process (a plain shell) since its agent ran there, and where
    no agent runs now."""
    fg = os.path.basename((k.get("foreground") or {}).get("name") or (k.get("argv") or [""])[0])
    return k.get("state") == "live" and fg in SHELLS and not agent_running(k)


def bare_shell(k):
    argv = k.get("argv") or []
    return len(argv) == 1 and os.path.basename(argv[0]) in SHELLS


def plan(k, rec, running):
    """What to type into `k` now: (how, argv, direct, carry) or None (direct: shell_line's). how is resume (its own
    session), fresh (its session is gone: a new conversation, missing history), running (that session runs elsewhere:
    nothing typed) or held (argv is then the reason). carry: what the line sets besides argv, {env, need, plan,
    config_dir, previous, kind, bound}. `running`: the sessions agents run here now."""
    from .providers import compose
    labels = k.get("labels") or {}
    assistant = labels.get("herdr.role") == "coordinator" or k.get("template") in ASSISTANT_TEMPLATES
    # A task's agent only while its task is at work (Working, or Ready for follow-ups): a finished
    # task's stays a shell, as its end would leave it.
    task = task_of(k) if labels.get("herdr.task") else None
    if labels.get("herdr.task") and (task or {}).get("state") not in ("running", "ready"):
        return None
    previous = (rec or {}).get("session")
    if rec and rec.get("pid") == k.get("pid"):
        # Typed here already: once more only when the resume said its session is gone.
        if rec.get("how") != "resume" or now() - (rec.get("sent") or 0) > LOOK_MS:
            return None
        screen = run(["hc", "read", k["address"], "--lines", "40"]).stdout
        if not LOST.search("\n".join(screen.split("\n")[-30:])):
            return None
        rec = dict(rec, session=None)
    if not rec:
        # From before records (or lost before the first one): only a terminal the core plainly gave a shell.
        if not bare_shell(k):
            return None
        rec = task_record(k, task) if task else None
        previous = (rec or {}).get("session")
    if rec and rec.get("session") and rec["session"] in running:
        return ("running", None, False, None)
    command, template = template_of() if assistant and not (rec or {}).get("argv") else (None, None)
    base = (rec or {}).get("argv") or (shlex.split(command) if command else None)
    kind = (rec or {}).get("kind") or (kind_of(base[0]) if base else None)
    if not base or not kind:
        return None
    # The binding it comes back on: its recorded one, under today's routing (L2). Anything else holds it, said once.
    # Found here, outside any lock (it may read the launch journal), and carried to the recheck before it is sent.
    from .launch_admission import recorded_binding
    try:
        bound = recorded_binding(k, task, rec)
        p = binding_here(k, rec, task, kind, bound)
    except Fail as e:
        return ("held", str(e), False, None)
    if p is UNREAD:
        return None  # its settings can't be read now (a write in flight, say): nothing typed, looked at again next tick
    folder = (rec or {}).get("config_dir")
    shell = shell_of(k)
    if (p["route"] != "personal" or folder) and shell not in LINE_SHELLS:
        return ("held", f"Its shell ({shell or 'unknown'}) can't be given the provider binding or Claude Code folder this "
                        f"agent started with, so it isn't typed back. Nothing was started.", False, None)
    if rec and rec.get("session") and rec.get("log") and os.path.isfile(rec["log"]):
        how, argv = "resume", resume_argv(kind, base, rec["session"], CUT if rec.get("working") else None)
    else:
        # Its session is gone: a new one, with the handover (and an Assistant's role, its template's words), on the
        # same binding: missing history, never a resume.
        if assistant and template is None:
            template = template_of()[1]
        how, argv = "fresh", [*base, lost_message(task_ref(k), template)]
    try:
        argv, env = compose(p, argv)
    except Fail as e:
        return ("held", str(e), False, None)
    if folder:
        env = dict(env, CLAUDE_CONFIG_DIR=folder)
    # Without a record, an Assistant starts as its template does: without the person's shell.
    return (how, argv, not (rec or {}).get("shell"),
            {"env": env, "need": p.get("credential"), "plan": p, "config_dir": folder, "previous": previous, "kind": kind,
             "bound": bound})


def keep_binding(k, new, old):
    """An Assistant's binding copied onto its revival record while it runs (its start's journal record isn't kept
    forever), so it comes back on it; a task's agent's stays on its task. Personal adds nothing."""
    from .launch_admission import recorded_binding
    from .providers import PERSONAL
    labels = k.get("labels") or {}
    if labels.get("herdr.task") or labels.get("herdr.provider") in (None, "", PERSONAL):
        return new
    try:
        b = recorded_binding(k, None, old)
    except Fail:
        b = (old or {}).get("provider")
    return dict(new, provider=b) if b else new


def bring_back(k, rec, step, report):
    """Types step's line into k through launch admission (Admission.type_into), under the agent's own identity: an open
    start of that agent holds it, and a send hc doesn't confirm is kept uncertain. Records it on the terminal as
    handled (pid, how, sent, launch) once it was or may have been typed."""
    from .launch_admission import Admission, agent_identity, digest
    from .providers import recorded
    how, argv, direct, carry = step
    rec = dict(rec or {}, pid=k.get("pid"), how=how, sent=now())
    if how in ("held", "running"):
        # Nothing to type: said once (its record marks it handled).
        write_record(k, rec)
        if how == "held":
            report.setdefault("revive_held", []).append({"terminal": k["address"], "why": argv})
        else:
            report.setdefault("revived", []).append({"terminal": k["address"], "how": how, "session": rec.get("session")})
        return
    line = shell_line(shell_of(k), rec.get("cwd") or k.get("cwd"), {**env_of(k), **carry["env"]}, argv, direct, carry["need"])
    p = carry["plan"]
    labels = k.get("labels") or {}
    task = task_of(k) if labels.get("herdr.task") else None
    identity = agent_identity(k)
    fixed = {"terminal": k["address"], "pid": k.get("pid"), "line": line}

    seen = (k.get("labels") or {}).get(LABEL)

    def unchanged():
        # Its terminal as this revival planned from it: the same process, still at its shell, its record unchanged. Read
        # once its claim is held (outside the journal's lock, so a slow hc never holds up other starts): another sender
        # of this agent (the tick, or a lost-session recovery) marks the terminal before it lets its claim go, so this
        # sees that and types nothing twice.
        now_k = hc_json("get", k["address"])
        if (not now_k or now_k.get("pid") != k.get("pid") or not restarted(now_k)
                or (now_k.get("labels") or {}).get(LABEL) != seen):
            raise Fail(f"{who_of(k)} in {k['address']} changed since this revival was planned (another sender brought it "
                       f"back, or an agent runs there). Nothing was typed.")

    def revise():
        # The binding again from a fresh read of the settings only: a route, resource, endpoint or sign-in changed since
        # refuses the typing (run under the journal's lock: nothing here reads the journal or calls hc).
        q = binding_here(k, rec, task, carry["kind"], carry["bound"])
        if q is UNREAD:
            raise Fail("Shepherdr settings can't be read now, so this revival waits. Nothing was typed.")
        return digest({**fixed, "route": q["route"], "fingerprint": q["fingerprint"]})
    facts = {"revival": {"how": how, "missing_history": how == "fresh", "session": rec.get("session") if how == "resume" else None,
                         "previous_session": carry.get("previous")},
             "provider": recorded(p), "terminal_pid": k.get("pid")}
    try:
        adm = Admission(identity, "revive", space_of(labels) or None, None, revise, who=who_of(k))
        # claimed(): an open start of the same agent refuses here (its task as read now releases a start it records).
        adm.task, adm.config_dir = task, carry.get("config_dir")
        with adm.claimed():
            unchanged()
            out = adm.type_into(k["address"], line, facts, run, lambda lid: write_record(k, dict(rec, launch=lid)))
    except Fail as e:
        launch = getattr(e, "launch", None)
        if launch:
            # It may have been typed: marked handled before its claim was kept (type_into), so nothing types it again;
            # its launch id says how to confirm it.
            report.setdefault("revive_uncertain", []).append({"terminal": k["address"], "how": how, **launch, "why": str(e)})
        else:
            # Nothing was typed (an open start of the same agent, settings changed): looked at again next tick.
            report.setdefault("revive_held", []).append({"terminal": k["address"], "why": str(e)})
        return
    # Marked as handled (type_into, before its claim went): the next tick types nothing here again.
    row = {"terminal": k["address"], "how": how, "session": rec.get("session") if how == "resume" else None,
           "launch": out["launch"]}
    if how == "fresh":
        # Missing history: a new conversation, never said as its session resumed.
        row.update(missing_history=True, previous_session=carry.get("previous"))
    report.setdefault("revived", []).append(row)


def revive_pass(report):
    """Records each running Assistant's and task agent's session here, and brings back the ones the
    core gave a plain shell."""
    d = hc_json("ls") or {}
    mine = [k for k in d.get("terminals") or [] if "/" not in k.get("address", "") and k.get("state") == "live"]
    terms = [x for x in (hc_json("get", k["address"]) for k in mine) if x and watched(x)]
    running, back = set(), []
    for k in terms:
        rec = read_record(k)
        if agent_running(k):
            new = record_of(k)
            if new:
                new = keep_binding(k, new, rec)
                running.add(new["session"])
                if {x: v for x, v in (rec or {}).items() if x not in ("how", "sent", "launch")} != new:
                    write_record(k, new)
        elif restarted(k):
            back.append((k, rec))
    for k, rec in back:
        step = plan(k, rec, running)
        if step:
            bring_back(k, rec, step, report)


def lost_record(k):
    """For `launch revive --lost`: what the terminal's own launch says when it has no revival record yet (an agent the
    tick hasn't recorded, or one a person or a chat resumed), marked as a resume typed here just now, so plan() looks
    at its screen and starts a new conversation."""
    kind, argv = base_argv(k.get("argv"))
    if not kind:
        task = task_of(k) if (k.get("labels") or {}).get("herdr.task") else None
        rec = task_record(k, task) if task else None
        return rec
    launch = k.get("argv") or []
    return {"kind": kind, "session": None, "log": None, "argv": argv, "cwd": k.get("cwd"), "pid": k.get("pid"),
            "working": False, "shell": any(os.path.basename(str(a)) in SHELLS for a in launch[:launch.index(argv[0])])}


def cmd_revive(args, say):
    """`launch revive [TERMINAL] [--lost]`: the tick's pass, or one terminal here. --lost: its CLI said its session is
    gone (the service's and the window's lost-session recovery): checked on its screen here, then a new conversation
    there, once. Nothing is typed where an agent runs."""
    report = {}
    if bool(args.identity) != bool(args.lost):
        # Two shapes only: the tick's pass (no terminal), or one terminal whose CLI said its session is gone (--lost).
        # One terminal on its own isn't one: it can't tell which sessions run elsewhere, as the pass does.
        raise Fail("launch revive is the tick's pass (no terminal), or one terminal with --lost (its CLI said its session "
                   "is gone). Nothing was typed.")
    if not args.identity:
        revive_pass(report)
        lines = [f"{r['terminal']}: {r['how']}" + (" (missing history: a new conversation)" if r.get("missing_history") else "")
                 for r in report.get("revived", [])]
        lines += [f"{r['terminal']}: held. {r['why']}" for r in report.get("revive_held", []) + report.get("revive_uncertain", [])]
        return say(args, report, "\n".join(lines) or "Nothing to bring back here.")
    if "/" in args.identity:
        raise Fail("launch revive acts on this machine's terminals: run it there (herdr-task --on MACHINE).")
    k = hc_json("get", args.identity)
    # Any agent's terminal a chat follows, as the window and the service brought back before L2 (a tab agent too, under
    # its own identity); the tick's pass keeps to Assistants and task agents.
    if not k or not (watched(k) or base_argv(k.get("argv"))[0]):
        raise Fail(f"{args.identity} isn't an agent's terminal here (no claude or codex in how it started, and not an "
                   f"Assistant's or a task's). Nothing was typed.")
    if not restarted(k):
        return say(args, {"terminal": args.identity, "how": "none"}, f"{args.identity}: an agent runs there, or it has "
                   f"ended. Nothing was typed.")
    rec = read_record(k)
    if args.lost:
        # Brought back here already: nothing again. Held before: planned again, so the caller hears why.
        if not (rec and rec.get("pid") == k.get("pid") and rec.get("how") == "fresh"):
            rec = dict(rec or lost_record(k) or {}, pid=k.get("pid"), how="resume", sent=now())
    step = plan(k, rec, set())
    if not step:
        return say(args, {"terminal": args.identity, "how": "none"}, f"{args.identity}: nothing to bring back (its screen "
                   f"doesn't say its session is gone, or it was brought back already). Nothing was typed.")
    bring_back(k, rec, step, report)
    for key in ("revive_uncertain", "revive_held"):
        if report.get(key):
            e = Fail(report[key][0]["why"])
            if key == "revive_uncertain":
                e.launch = {x: report[key][0][x] for x in ("launch", "identity", "state")}
            raise e
    row = report["revived"][0]
    said = ("a new conversation was typed there (its earlier session is gone)" if row["how"] == "fresh" else
            f"its session {row['session']} was typed back to resume" if row["how"] == "resume" else "its session runs elsewhere")
    say(args, row, f"{args.identity}: {said}.")
