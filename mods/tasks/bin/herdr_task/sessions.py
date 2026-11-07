"""Agent sessions: the Claude Code or Codex session a task's agent runs, so it can resume."""

import json
import os
import re
import shutil
import sys

from .base import HOME, run
from .agents import agent_running, detail


# ---- agent sessions -------------------------------------------------------------------------

CONFIG_DIR = b"CLAUDE_CONFIG_DIR="
SESSION_ID = re.compile(r"[0-9a-fA-F-]+")  # as FIND reads one: it never leaves the folder


def kids(pid):
    r = run(["pgrep", "-P", str(pid)])
    out = []
    for p in r.stdout.split():
        out.append(p)
        out.extend(kids(p))
    return out


def environment(pid):
    """Process pid's own environment as it started, entry by entry; [] when it can't be read. Only
    claude_dir() reads this, and it keeps nothing but the one variable."""
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                return [e for e in f.read().split(b"\0") if e]
        except OSError:
            return []
    if sys.platform != "darwin":
        return []
    try:
        import ctypes  # here alone: a python built without it still runs everything else
    except ImportError:
        return []
    size = ctypes.c_size_t(os.sysconf("SC_ARG_MAX"))
    buf = ctypes.create_string_buffer(size.value)
    mib = (ctypes.c_int * 3)(1, 49, int(pid))  # CTL_KERN, KERN_PROCARGS2
    if ctypes.CDLL(None).sysctl(mib, ctypes.c_uint(3), buf, ctypes.byref(size), None, ctypes.c_size_t(0)):
        return []
    data = buf.raw[:size.value]
    # argc, the executable and its padding, then argv, then the environment up to an empty string.
    words = data[4:].split(b"\0")
    i = 1
    while i < len(words) and not words[i]:
        i += 1
    argc = int.from_bytes(data[:4], sys.byteorder)
    start = i + argc
    # A short title zero-fills argv past itself, so the environment starts at the next word. Only
    # with argc of 2 or more and every word after argv[0] empty: with 1 there is nothing to check.
    if argc >= 2 and not any(words[i + 1:start]):
        while start < len(words) and not words[start]:
            start += 1
    env = words[start:]
    env = env[:env.index(b"")] if b"" in env else []
    # What follows the environment: a system binary shows these with no environment before them.
    if env and env[0].startswith(b"executable_path="):
        env = []
    # argc counts argv as it started. A title that fills argv collapses it, so the count can land
    # past the variable: seen anywhere but here, where the environment starts is not known.
    if not any(e.startswith(CONFIG_DIR) for e in env) and any(w.startswith(CONFIG_DIR) for w in words):
        return []
    return env


def claude_dir(pid):
    """The folder Claude Code uses in process pid, from that process's own environment, never this
    one's: its CLAUDE_CONFIG_DIR, or ~/.claude when it has none. None, so no other folder is tried,
    when that can't be read exactly: no way to read it here, an empty environment (macOS shows a
    system binary's so, and a set variable looks unset), a macOS block whose start moved
    (environment()), a value that isn't one absolute path, or another folder called .claude,
    which sessionOf (core/agents.js) would take for ~/.claude. FIND in core/chat-log.js is the
    same rule."""
    entries = environment(pid)
    if not entries:
        return None
    value = next((e[len(CONFIG_DIR):] for e in entries if e.startswith(CONFIG_DIR)), None)
    if value is None:
        return os.path.join(HOME, ".claude")
    path = os.fsdecode(value)
    path = path[:-1] if path.endswith("/") else path
    if not path.startswith("/") or re.search(r"[\x00-\x1f\x7f]", path):
        return None
    if os.path.basename(path) == ".claude" and path != os.path.join(HOME, ".claude"):
        return None
    return path


def session_of(pid, any_folder=False):
    """(session id, log path) of the agent process pid (or a child), as FIND in core/chat-log.js
    finds it: Claude Code names its session in <folder>/sessions/<pid>.json under that process's
    own folder (claude_dir()), and the file must say that pid; Codex holds its rollout open.

    Only one under ~/.claude, unless any_folder: nearly everything here keeps the answer to start
    or resume that agent, and neither carries CLAUDE_CONFIG_DIR, so it would come back on another
    profile (L1, L2). any_folder is for what only reads the log."""
    for p in [str(pid)] + kids(pid):
        folder = claude_dir(p)
        if not any_folder and folder != os.path.join(HOME, ".claude"):
            folder = None
        j = os.path.join(folder, "sessions", p + ".json") if folder else None
        if j and os.path.isfile(j):
            try:
                with open(j) as f:
                    meta = json.load(f)
                sid = meta.get("sessionId") if meta.get("pid") == int(p) else None
            except (OSError, ValueError, AttributeError):
                sid = None
            if isinstance(sid, str) and SESSION_ID.fullmatch(sid):
                log = None
                base = os.path.join(folder, "projects")
                try:
                    projects = os.listdir(base)
                except OSError:  # none yet, or not this user's to read: no log, as for a session just begun
                    projects = []
                for d in projects:
                    f = os.path.join(base, d, sid + ".jsonl")
                    if os.path.isfile(f):
                        log = f
                        break
                return sid, log
        files = []
        fd = f"/proc/{p}/fd"
        if os.path.isdir(fd):
            try:
                names = os.listdir(fd)
            except OSError:  # a process this user can't look into, or one just gone
                names = []
            for n in names:
                try:
                    files.append(os.readlink(os.path.join(fd, n)))
                except OSError:
                    pass
        elif shutil.which("lsof"):
            files = [l[1:] for l in run(["lsof", "-p", p, "-Fn"]).stdout.split("\n") if l.startswith("n")]
        for f in files:
            m = re.search(r"/rollout-.*?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", f)
            if m:
                return m.group(1), f
    return None, None


def refresh_sessions(s, task, live):
    """Records each live agent's current session (it changes on /clear)."""
    for k in live:
        k = detail(k)
        pid = (k.get("foreground") or {}).get("pid")
        a = next((a for a in task["agents"] if a["address"] == k["address"]), None)
        if not pid or not a or not agent_running(k):
            continue
        sid, log = session_of(pid)
        if sid and (a.get("session"), a.get("log")) != (sid, log):
            a["session"], a["log"] = sid, log
            s.dirty = True
