"""Native revival and restart through launch admission (L2 of docs/migration/upstream-v3.1.3.md): an agent the core
gave a plain shell is typed back by `herdr-task launch revive` (the tick's pass, or one terminal with --lost for the
service's and the window's lost-session recovery), and restart.sh restarts an Assistant, each through the one owner,
with its recorded provider binding. Each test reopens the launch journal, the task list and the terminals' labels as
files, apart from the process that wrote them.

These run on CI only, as herdr-task's other command-line tests: HOME stays the account's own, the task lists,
settings and templates are throwaway ones, and `hc` is a stateful stand-in first on PATH that keeps its terminals
(their labels, screens and what was typed into them) in a file, so no agent, terminal or model request exists. They
prove what herdr-task does with its journal, its records and the line it types; they don't prove herdr-core's own
receipts (there are none), a real crash or reboot, a real CLI resuming its session, or an agent's sign-in."""
import json
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_launch_admission as la  # noqa: E402

UUID = la.UUID
# hc with whole terminals kept in FAKE_HC_STATE: ls (by label), get, label (kept), read (its "screen"), send (logged;
# FAKE_HC_SEND_FILE says "fail" to answer 1, as a lost or failed reply), run (a new terminal from its labels, its
# one-off template's words logged as la's stand-in does), and kill, rm and wait (nothing). A process whose
# FAKE_HC_GATE_MATCH is in a call's words waits there while FAKE_HC_GATE exists, after FAKE_HC_GATE_SKIP such calls
# went through (FAKE_HC_GATE.reached says it got there).
REVIVE_HC = r'''#!/usr/bin/env python3
import fcntl, json, os, sys, time
args = sys.argv[1:]
with open(os.environ["FAKE_HC_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
gate, match = os.environ.get("FAKE_HC_GATE"), os.environ.get("FAKE_HC_GATE_MATCH")
if gate and match and os.path.exists(gate) and match in " ".join(args):
    seen = gate + ".seen"
    n = len(open(seen).read()) if os.path.exists(seen) else 0
    with open(seen, "a") as f:
        f.write(".")
    if n >= int(os.environ.get("FAKE_HC_GATE_SKIP", "0")):
        open(gate + ".reached", "w").close()
        for _ in range(1200):
            if not os.path.exists(gate):
                break
            time.sleep(0.05)
path = os.environ["FAKE_HC_STATE"]
lock = open(path + ".lock", "a")
fcntl.flock(lock, fcntl.LOCK_EX)
try:
    with open(path) as f:
        st = json.load(f)
except (OSError, ValueError):
    st = {"terminals": [], "n": 0}
def save():
    with open(path, "w") as f:
        json.dump(st, f)
def find(a):
    return next((t for t in st["terminals"] if a in (t["address"], t.get("name"))), None)
def labels_of(words):
    out = {}
    for i, a in enumerate(words):
        if a == "--label" and i + 1 < len(words):
            k, _, v = words[i + 1].partition("=")
            out[k] = v
    return out
verb = args[0] if args else ""
if verb == "ls":
    want = args[args.index("--label") + 1].partition("=") if "--label" in args else None
    print(json.dumps({"terminals": [t for t in st["terminals"] if not want or (t.get("labels") or {}).get(want[0]) == want[2]]}))
    sys.exit(0)
if verb == "get":
    t = find(args[1]) if len(args) > 1 else None
    if not t:
        sys.exit(1)
    print(json.dumps(t))
    sys.exit(0)
if verb == "label":
    t = find(args[1])
    if not t:
        sys.exit(1)
    for kv in args[2:]:
        k, _, v = kv.partition("=")
        t.setdefault("labels", {})[k] = v
    save()
    sys.exit(0)
if verb == "read":
    t = find(args[1])
    print((t or {}).get("screen", ""))
    sys.exit(0)
if verb == "send":
    try:
        with open(os.environ["FAKE_HC_SEND_FILE"]) as f:
            mode = f.read().strip()
    except OSError:
        mode = "ok"
    if mode == "fail":
        print("hc: timed out", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
if verb == "run":
    tdir = os.environ.get("HERDR_TASK_TEMPLATES")
    for w in args:
        tp = os.path.join(tdir, w + ".md") if tdir and "/" not in w else None
        if tp and w.startswith("herdr-") and os.path.isfile(tp):
            with open(tp) as tf, open(os.environ["FAKE_HC_LOG"], "a") as f:
                f.write(json.dumps(["template", w, tf.read()]) + "\n")
    words = args[1:args.index("--")] if "--" in args else args[1:]
    st["n"] += 1
    t = {"address": "t%d" % st["n"], "state": "live", "pid": 1000 + st["n"], "cwd": "/", "argv": ["claude"], "labels": labels_of(words)}
    st["terminals"].append(t)
    save()
    print(json.dumps({"address": t["address"], "first_message": {"sent": True}}))
    sys.exit(0)
if verb in ("kill", "rm", "wait"):
    sys.exit(0)
sys.exit(1)
'''
SESSION = "11111111-2222-4333-8444-555555555555"
LOST = "$ claude --resume x\nNo conversation found with session ID: x\n$ "
CLAUDE = {"claude_resource": "example", "claude_deployment": "claude-deployment"}
CODEX = {"codex_endpoint": "https://example.openai.azure.com/openai/v1", "codex_deployment": "code-deployment"}


class Fixture(la.Fixture):
    """la's fixture (a throwaway repo, task store, settings, templates and journal) with REVIVE_HC as its hc."""

    def __init__(self, test, settings=la.PERSONAL):
        super().__init__(test, settings)
        with open(os.path.join(self.tmp, "bin", "hc"), "w") as f:
            f.write(REVIVE_HC)
        self.send_mode = os.path.join(self.tmp, "send-mode")
        self.env["FAKE_HC_SEND_FILE"] = self.send_mode
        self.log_file = os.path.join(self.tmp, f"{SESSION}.jsonl")
        open(self.log_file, "w").close()

    def provider(self, section, **worker):
        d = json.loads(json.dumps(la.PERSONAL))
        d["everywhere"]["provider"] = section
        d["everywhere"]["worker"].update(worker)
        self.write_settings(d)

    def plan(self, agent="claude", role="worker"):
        return self.ok("provider", "plan", "--agent", agent, "--space", "sp1", "--folder", self.repo, "--role", role)

    def binding(self, agent="claude", role="worker"):
        """The nonsecret binding a start on today's settings records, as the provider owner plans it."""
        out = self.plan(agent, role)
        return {k: out[k] for k in ("route", "agent", "target", "deployment", "auth", "fingerprint")}

    def new_assistant(self, *labels):
        """An Assistant's new start through launch admission (A2's --new-start), as the window's chat sends it."""
        p = self.run("launch", "run", "--role", "coordinator", "--space", "sp1", "--new-start", "assistant", "--json", "--",
                     "--bg", "--json", "--no-parent", "--keep", "--label", "herdr.role=coordinator", *labels, "assistant", "hi")
        self.test.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)["address"]

    def list_path(self):
        return next(os.path.join(self.store, n) for n in os.listdir(self.store) if n.endswith(".json") and not n.startswith("."))

    def task_on(self, tid=1, state="running", argv=("claude",), provider=None, address="t5"):
        """The task as its start left it: running, its agent recorded on its list (address, argv, session, binding).
        Gives the task's key (its herdr.task label)."""
        path = self.list_path()
        with open(path) as f:
            d = json.load(f)
        t = next(x for x in d["tasks"] if x["id"] == tid)
        t["state"] = state
        t["agents"] = [{"address": address, "agent": os.path.basename(argv[0]), "argv": list(argv), "at": 1, "session": SESSION,
                        "log": self.log_file, **({"provider": provider} if provider else {})}]
        with open(path, "w") as f:
            json.dump(d, f, indent=2)
        return f"{os.path.basename(path)[:-5]}#{tid}"

    def record(self, **more):
        """Revival's record on a terminal (herdr.resume), as the tick wrote it while the agent ran."""
        return {"kind": "claude", "session": SESSION, "log": self.log_file, "argv": ["claude"], "cwd": self.repo, "pid": 100,
                "working": False, "shell": True, **more}

    def lost(self, address, labels, rec, pid=200, name=None, screen=""):
        """A kept terminal the core gave a plain shell after its agent was lost (labels kept, argv a shell)."""
        self.seed(address=address, state="live", pid=pid, cwd=self.repo, argv=["/bin/bash"], name=name, screen=screen,
                  foreground={"pid": pid, "name": "bash", "argv": ["/bin/bash"], "cwd": self.repo},
                  labels={**labels, **({"herdr.resume": json.dumps(rec)} if rec else {})})

    def update(self, address, **fields):
        with open(self.state) as f:
            st = json.load(f)
        for t in st["terminals"]:
            if t["address"] == address:
                t.update(fields)
        with open(self.state, "w") as f:
            json.dump(st, f)

    def terminal(self, address):
        return next(t for t in self.terminals() if t["address"] == address)

    def sends(self):
        return [c for c in self.calls() if c[:1] == ["send"]]

    def revivals(self):
        return [r for r in self.starts("") if r.get("revival")]

    def revive(self, *args):
        return self.ok("launch", "revive", *args)

    def worker(self, labels=None, rec=None, **task):
        """A running task's Claude Code worker lost in t5: the task on its list, the terminal as the core left it."""
        self.add()
        key = self.task_on(**task)
        self.lost("t5", {"herdr.task": key, "herdr.task.space": "sp1", **(labels or {})}, rec or self.record(),
                  name="repo-1-fix-login")
        return key


def shell_ok(test, line):
    """The typed line is one a POSIX shell parses (sh -n): nothing is run."""
    p = subprocess.run(["sh", "-n", "-c", line], capture_output=True, text=True)
    test.assertEqual(p.returncode, 0, line + p.stderr)


@la.ON_CI
class Revival(unittest.TestCase):

    def test_a_lost_agent_resumes_its_own_session_once_through_the_journal(self):
        f = Fixture(self)
        key = f.worker()
        before = f.task()
        [row] = f.revive()["revived"]
        self.assertEqual((row["terminal"], row["how"], row["session"]), ("t5", "resume", SESSION))
        self.assertNotIn("missing_history", row)
        [send] = f.sends()
        self.assertEqual(send[1], "t5")
        self.assertIn(f"cd {f.repo} && HERDR_BROWSER_TASK='{key}' claude --resume {SESSION}", send[2])
        shell_ok(self, send[2])
        # A start in the journal under the task's own identity, confirmed by hc, its claim let go.
        [rec] = f.revivals()
        self.assertRegex(rec["launch"], UUID)
        self.assertEqual((rec["identity"], rec["role"], rec["state"], rec["terminal"], rec["launch"]),
                         (f"task:{key}", "revive", "confirmed", "t5", row["launch"]))
        self.assertEqual((rec["revival"]["how"], rec["revival"]["missing_history"], rec["revival"]["session"]), ("resume", False, SESSION))
        self.assertEqual(rec["provider"], {"route": "personal"})
        self.assertEqual(f.journal()["claims"], {})
        # Handled on its terminal: a second pass types nothing.
        self.assertEqual(json.loads(f.terminal("t5")["labels"]["herdr.resume"])["launch"], row["launch"])
        f.revive()
        self.assertEqual(len(f.sends()), 1)
        # Revival never writes the task list: its state, holds, dependencies, approval and worktree stay as they were.
        self.assertEqual(f.task(), before)

    def test_missing_history_is_a_new_conversation_never_reported_as_a_resume(self):
        f = Fixture(self)
        f.worker()
        os.remove(f.log_file)
        [row] = f.revive()["revived"]
        self.assertEqual((row["how"], row["session"], row["missing_history"], row["previous_session"]), ("fresh", None, True, SESSION))
        [send] = f.sends()
        self.assertNotIn("--resume", send[2])
        self.assertIn("<restart>Your earlier session is gone", send[2])
        self.assertIn("herdr-task show REPO-1", send[2])
        [rec] = f.revivals()
        self.assertEqual(rec["revival"], {"how": "fresh", "missing_history": True, "session": None, "previous_session": SESSION})

    def test_a_send_hc_doesnt_confirm_stays_uncertain_and_holds_the_agent(self):
        f = Fixture(self)
        key = f.worker()
        with open(f.send_mode, "w") as fh:
            fh.write("fail")
        out = f.revive()
        [held] = out["revive_uncertain"]
        self.assertNotIn("revived", out)
        [rec] = f.revivals()
        self.assertEqual((held["launch"], held["state"], rec["state"], rec["reply"]), (rec["launch"], "submission-uncertain",
                                                                                         "submission-uncertain", "hc exited 1"))
        self.assertEqual(f.journal()["claims"], {f"task:{key}": rec["launch"]})
        os.remove(f.send_mode)
        # Never typed again, even when its screen says the session is gone, and no start of that task goes past it.
        f.update("t5", screen=LOST)
        self.assertIn(f"launch reconcile task:{key} {rec['launch']}", f.revive()["revive_held"][0]["why"])
        self.assertEqual(len(f.sends()), 1)
        self.assertIn(f"launch reconcile task:{key} {rec['launch']}",
                      f.refused("resume", "1", "--folder", f.repo, "--space", "sp1")["error"])
        self.assertEqual([c for c in f.calls() if c[:1] == ["run"]], [])
        # No agent there: reconcile keeps it uncertain. An agent running there is the positive evidence that confirms it.
        why = f.refused("launch", "reconcile", f"task:{key}", rec["launch"])["error"]
        self.assertIn("no agent runs in t5", why)
        f.update("t5", foreground={"pid": 300, "name": "claude", "argv": ["claude"], "cwd": f.repo})
        self.assertEqual(f.ok("launch", "reconcile", f"task:{key}", rec["launch"])["state"], "confirmed")
        self.assertEqual(f.journal()["claims"], {})

    def test_an_open_start_of_the_same_agent_holds_its_revival_until_released(self):
        f = Fixture(self)
        key = f.worker()
        lid = "0b1c2d3e-4f5a-4b6c-8d7e-001122334455"
        os.makedirs(f.store, exist_ok=True)
        with open(os.path.join(f.store, ".launches.json"), "w") as fh:
            json.dump({"version": 1, "claims": {f"task:{key}": lid},
                       "launches": {lid: {"launch": lid, "identity": f"task:{key}", "role": "task", "state": "never-submitted", "at": 1,
                                          "updated": 1, "revision": "r", "space": "sp1", "machine": "local", "parent": None,
                                          "pid": 1, "config_dir": None}}}, fh)
        [held] = f.revive()["revive_held"]
        self.assertIn(f"herdr-task launch recover task:{key} {lid}", held["why"])
        self.assertEqual(f.sends(), [])
        # Not marked handled: once that start is released, the next pass brings it back, once.
        f.ok("launch", "recover", f"task:{key}", lid)
        self.assertEqual(f.revive()["revived"][0]["how"], "resume")
        f.revive()
        self.assertEqual(len(f.sends()), 1)

    def test_a_second_sender_that_planned_before_the_first_typed_types_nothing(self):
        """Two senders of the same agent at once (the tick's pass and a lost-session recovery): the second plans from the
        terminal as it was, then waits; the first types it back and marks its terminal while it still holds its claim;
        the second, let go, finds the terminal changed and types nothing (two processes, the journal reopened)."""
        f = Fixture(self)
        f.worker()
        held_env = dict(f.env, FAKE_HC_GATE_MATCH="get t5 --json", FAKE_HC_GATE_SKIP="1")
        open(f.gate, "w").close()
        second = subprocess.Popen(f.argv("launch", "revive", "--json"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, env=held_env)
        f.procs.append(second)
        f.reached()  # planned from the record as it was, waiting before its claim
        first = f.revive()["revived"][0]["launch"]
        f.release()
        out, err = second.communicate(timeout=120)
        self.assertEqual(second.returncode, 0, out + err)
        [held] = json.loads(out)["revive_held"]
        self.assertIn("changed since this revival was planned", held["why"])
        self.assertEqual(len(f.sends()), 1)
        self.assertEqual([r["launch"] for r in f.revivals() if r["state"] == "confirmed"], [first])
        self.assertEqual(f.journal()["claims"], {})

    def test_a_second_loss_in_the_same_shell_starts_anew_again(self):
        """A lost session typed anew into its shell, running, then lost again in that same shell (no core restart): the
        record the tick wrote while it ran is the one planned from, so it starts anew again (once)."""
        f = Fixture(self)
        f.add()
        key = f.task_on()
        f.lost("t5", {"herdr.task": key, "herdr.task.space": "sp1"}, f.record(pid=200), name="repo-1-fix-login", screen=LOST)
        self.assertEqual(f.revive("t5", "--lost")["how"], "fresh")
        # It ran (the tick recorded it, without how), and its session was lost again in the same shell.
        f.update("t5", labels={**f.terminal("t5")["labels"], "herdr.resume": json.dumps(f.record(pid=200, session=None))})
        self.assertEqual(f.revive("t5", "--lost")["how"], "fresh")
        self.assertEqual(len(f.sends()), 2)

    def test_a_finished_tasks_agent_stays_a_shell(self):
        f = Fixture(self)
        f.worker(state="done")
        self.assertEqual(f.revive(), {})
        self.assertEqual(f.sends(), [])
        self.assertFalse(os.path.exists(os.path.join(f.store, ".launches.json")) and f.revivals())

    def test_its_own_claude_code_folder_comes_back_with_it(self):
        f = Fixture(self)
        profile = os.path.join(f.tmp, "profile")
        f.worker(rec=f.record(config_dir=profile))
        f.revive()
        [send] = f.sends()
        self.assertIn(f"CLAUDE_CONFIG_DIR={profile} ", send[2])
        self.assertEqual(f.revivals()[0]["config_dir"], profile)


@la.ON_CI
class RevivalOnAzure(unittest.TestCase):

    def test_a_task_agent_resumes_on_its_recorded_binding_not_todays_default(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE, "claude_auth": "api-key"})
        bound = f.binding()
        f.worker(labels={"herdr.provider": "azure-foundry"}, provider=bound)
        f.provider({"route": "azure-foundry", **CLAUDE, "claude_auth": "api-key", "claude_deployment": "new-default"})
        f.revive()
        [send] = f.sends()
        line = send[2]
        shell_ok(self, line)
        self.assertIn('if [ -z "${ANTHROPIC_FOUNDRY_API_KEY:-}" ]', line)
        self.assertIn("--model claude-deployment", line)
        self.assertIn('"CLAUDE_CODE_USE_FOUNDRY": "1"', line)
        self.assertIn(f"--resume {SESSION}", line)
        self.assertNotIn("new-default", line)
        self.assertEqual(f.revivals()[0]["provider"], bound)

    def test_changed_routing_holds_it_with_the_reason(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE})
        bound = f.binding()
        f.worker(labels={"herdr.provider": "azure-foundry"}, provider=bound)
        for section, words in (({"route": "azure-foundry", **CLAUDE, "claude_resource": "other"}, "Azure Foundry other with Entra ID"),
                               ({"route": "personal"}, "Personal (the CLI's own sign-in)")):
            with self.subTest(words=words):
                f.update("t5", labels={**f.terminal("t5")["labels"], "herdr.resume": json.dumps(f.record())})
                f.provider(section)
                [held] = f.revive()["revive_held"]
                self.assertIn("conversation started on Azure Foundry example with Entra ID", held["why"])
                self.assertIn(words, held["why"])
                self.assertEqual(f.sends(), [])

    def test_codex_resumes_with_its_provider_table_before_resume_and_its_effort_and_fast(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CODEX})
        bound, table = f.binding("codex"), f.plan("codex")["args"]
        own = ["codex", "-c", 'model_reasoning_effort="high"', "-c", 'service_tier="fast"']
        # What the tick recorded from its launch: the provider table its start put in front of its own words.
        f.worker(labels={"herdr.provider": "azure-foundry"}, provider=bound, argv=own,
                 rec=f.record(kind="codex", argv=["codex", *table, *own[1:]]))
        f.revive()
        [send] = f.sends()
        line = send[2]
        shell_ok(self, line)
        self.assertIn('if [ -z "${AZURE_OPENAI_API_KEY:-}" ]', line)
        self.assertIn("OPENAI_BASE_URL='' ", line)
        table = line.index("model_provider=")
        self.assertLess(table, line.index(" resume "))
        self.assertLess(line.index("-m code-deployment"), line.index(" resume "))
        self.assertLess(line.index(" resume "), line.index("model_reasoning_effort"))
        self.assertIn("service_tier=", line[line.index(" resume "):])
        self.assertTrue(line.rstrip().endswith(f"{SESSION}; fi"), line)

    def test_an_assistant_comes_back_on_its_starts_journal_record_and_never_on_personal(self):
        f = Fixture(self)
        os.makedirs(os.path.join(f.tmp, "templates"), exist_ok=True)
        with open(os.path.join(f.tmp, "templates", "assistant.md"), "w") as fh:
            fh.write("---\nname: assistant\ndescription: the Assistant\ncommand: claude --dangerously-skip-permissions\n---\nYou are the Assistant.\n")
        f.provider({"route": "azure-foundry", **CLAUDE, "coordinator_claude_deployment": "assistant-deployment"})
        address = f.new_assistant("--label", "herdr.coordinator.space=sp1")
        labels = f.terminal(address)["labels"]
        self.assertEqual(labels["herdr.provider"], "azure-foundry")
        # Lost: the core gave its terminal a shell; the tick had recorded its session (no binding copy yet).
        f.update(address, pid=200, argv=["/bin/bash"], foreground={"pid": 200, "name": "bash", "argv": ["/bin/bash"]}, cwd=f.repo,
                 labels={**labels, "herdr.resume": json.dumps(f.record(argv=["claude", "--dangerously-skip-permissions"], shell=False))})
        f.provider({"route": "azure-foundry", **CLAUDE, "coordinator_claude_deployment": "newer"})
        f.revive()
        [send] = f.sends()
        self.assertIn("command claude --settings ", send[2])
        self.assertIn("--model assistant-deployment", send[2])
        self.assertIn(f"--resume {SESSION}", send[2])
        [rec] = f.revivals()
        self.assertEqual((rec["identity"], rec["provider"]["deployment"]), ("coordinator:local/sp1", "assistant-deployment"))
        # One whose terminal says Azure and whose binding is nowhere: held with why, nothing typed.
        f.lost("t50", {"herdr.role": "coordinator", "herdr.space": "sp2", "herdr.provider": "azure-foundry"}, f.record())
        [held] = f.revive()["revive_held"]
        self.assertEqual(held["terminal"], "t50")
        self.assertIn("its recorded provider binding can't be found", held["why"])
        self.assertIn("never moved to Personal", held["why"])
        self.assertEqual(len(f.sends()), 1)


@la.ON_CI
class LostSession(unittest.TestCase):
    """`launch revive TERMINAL --lost`: the service's and the window's lost-session recovery at the agent's shell, through
    the same owner as the tick's pass, so it comes back once."""

    def test_a_gone_session_starts_anew_once_whoever_asks(self):
        f = Fixture(self)
        f.add()
        key = f.task_on()
        # Its shell kept its process (no crash): the record the tick wrote while it ran names the same process.
        f.lost("t5", {"herdr.task": key, "herdr.task.space": "sp1"}, f.record(pid=200), name="repo-1-fix-login")
        # Its screen doesn't say the session is gone: nothing typed.
        self.assertEqual(f.revive("t5", "--lost")["how"], "none")
        self.assertEqual(f.sends(), [])
        f.update("t5", screen=LOST)
        out = f.revive("t5", "--lost")
        self.assertEqual((out["how"], out["missing_history"], out["session"]), ("fresh", True, None))
        [send] = f.sends()
        self.assertIn("<restart>", send[2])
        # The other chat, and the tick, find it handled.
        self.assertEqual(f.revive("t5", "--lost")["how"], "none")
        f.revive()
        self.assertEqual(len(f.sends()), 1)

    def test_any_chats_agent_comes_back_under_its_own_identity(self):
        """A chat's agent that is neither an Assistant nor a task's (a tab agent, one restarted behind its chat, a fork),
        with no labels at all: brought back by the real owner as the window and the service did before L2, claimed as
        a tab agent of its own (never as the space's Assistant)."""
        f = Fixture(self)
        f.seed(address="t8", state="live", pid=800, cwd=f.repo, argv=["claude", "--resume", SESSION], screen=LOST,
               foreground={"pid": 800, "name": "zsh", "argv": ["zsh"], "cwd": f.repo}, labels={})
        out = f.revive("t8", "--lost")
        self.assertEqual((out["how"], out["missing_history"]), ("fresh", True))
        [send] = f.sends()
        self.assertTrue(send[2].startswith("claude '<restart>Your earlier session is gone"), send[2])
        self.assertNotIn("--resume", send[2])
        [rec] = f.revivals()
        self.assertEqual((rec["identity"], rec["state"]), ("agent:local/unplaced/t8", "confirmed"))
        self.assertEqual(f.revive("t8", "--lost")["how"], "none")
        self.assertEqual(len(f.sends()), 1)

    def test_its_refusal_is_the_owners_words_and_nothing_is_typed(self):
        f = Fixture(self)
        f.lost("t7", {"herdr.role": "coordinator", "herdr.space": "sp1", "herdr.provider": "azure-foundry"}, f.record(pid=200),
               screen=LOST)
        self.assertIn("its recorded provider binding can't be found", f.refused("launch", "revive", "t7", "--lost")["error"])
        self.assertEqual(f.sends(), [])
        self.assertIn("isn't an agent's terminal here", f.refused("launch", "revive", "t99", "--lost")["error"])
        # Two shapes only: the tick's pass, or one terminal with --lost; a misused flag refuses with one error, nothing typed.
        for words in (["t7"], ["--lost"]):
            self.assertIn("launch revive is the tick's pass", f.refused("launch", "revive", *words)["error"])
        self.assertIn("--continues is for a restart", f.refused("launch", "run", "--role", "coordinator", "--space", "sp1",
                                                                  "--continues", "--check")["error"])
        self.assertEqual(f.sends(), [])


@la.ON_CI
class RestartOnAzure(unittest.TestCase):
    """restart.sh restarting an Assistant that started on Azure Foundry: continuing its conversation keeps the binding
    its start recorded; a new conversation never moves it to another route."""

    def assistant(self, f):
        os.makedirs(os.path.join(f.tmp, "templates"), exist_ok=True)
        with open(os.path.join(f.tmp, "templates", "assistant.md"), "w") as fh:
            fh.write("---\nname: assistant\ndescription: the Assistant\ncommand: claude\n---\nYou are the Assistant.\n")
        f.provider({"route": "azure-foundry", **CLAUDE, "coordinator_claude_deployment": "assistant-deployment"})
        address = f.new_assistant("--label", "herdr.space=sp1", "--label", "herdr.tab=tb1")
        f.update(address, cwd=f.repo, template="assistant")
        return address

    def restart(self, f, old, argv=None, resume=False):
        env = dict(f.env, **({"HERDR_RESTART_RESUME": "1"} if resume else {}))
        return subprocess.run(["bash", la.RESTART, old, *([json.dumps(argv)] if argv else [])], capture_output=True, text=True,
                              env=env, timeout=120)

    def test_continuing_its_conversation_keeps_its_recorded_deployment(self):
        f = Fixture(self)
        old = self.assistant(f)
        f.provider({"route": "azure-foundry", **CLAUDE, "coordinator_claude_deployment": "newer"})
        p = self.restart(f, old, ["claude", "--resume", SESSION, "--effort", "high"], resume=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        new = p.stdout.strip()
        # The owner's one-off for this restart (the Assistant's own new start logged the first).
        one = [c for c in f.calls() if c[0] == "template" and "-az-" in c[1]][-1]
        command = re.search(r"^command: (.+)$", one[2], re.M).group(1)
        self.assertIn("exec claude --settings ", command)
        self.assertIn("--model assistant-deployment", command)
        self.assertIn(f"--resume {SESSION} --effort high", command)
        self.assertNotIn("newer", command)
        rec = next(r for r in f.starts("coordinator:") if r.get("address") == new)
        self.assertEqual((rec["state"], rec["provider"]["deployment"]), ("confirmed", "assistant-deployment"))
        self.assertEqual(f.terminal(new)["labels"]["herdr.provider"], "azure-foundry")
        self.assertIn(["kill", old], f.calls())
        # No one-off template is left behind.
        self.assertEqual([n for n in os.listdir(os.path.join(f.tmp, "templates")) if n.startswith("herdr-")], [])

    def test_a_lost_session_behind_its_chat_keeps_its_binding_and_its_message_whole(self):
        """The window's and the service's ended-terminal recovery (restart.sh, no handoff): a new conversation for a lost
        one, on the binding the old agent recorded (not today's default), its multi-line first message one argv word,
        and its record saying missing history."""
        f = Fixture(self)
        old = self.assistant(f)
        f.provider({"route": "azure-foundry", **CLAUDE, "coordinator_claude_deployment": "newer"})
        p = self.restart(f, old, ["claude", "--effort", "high", "<restart>gone.\n\nYou are the Assistant."], resume=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        one = [c for c in f.calls() if c[0] == "template" and "-az-" in c[1]][-1]
        command = re.search(r"^command: (.+)$", one[2], re.M).group(1)
        self.assertIn("--model assistant-deployment", command)
        word = '"$(printf \'<restart>gone.\\n\\nYou are the Assistant.\')"'
        self.assertIn(word, command)
        echoed = subprocess.run(["sh", "-c", f"printf %s {word}"], capture_output=True, text=True).stdout
        self.assertEqual(echoed, "<restart>gone.\n\nYou are the Assistant.")
        rec = next(r for r in f.starts("coordinator:") if r.get("address") == p.stdout.strip())
        self.assertEqual((rec["missing_history"], rec["provider"]["deployment"]), (True, "assistant-deployment"))

    def test_a_model_its_recorded_deployment_would_replace_is_refused(self):
        f = Fixture(self)
        old = self.assistant(f)
        calls = len(f.calls())
        p = self.restart(f, old, ["claude", "--resume", SESSION, "--model", "other-model"], resume=True)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("recorded on Azure Foundry deployment assistant-deployment", p.stderr)
        self.assertEqual({c[0] for c in f.calls()[calls:]}, {"get"})

    def test_a_new_conversation_is_never_moved_to_another_route(self):
        f = Fixture(self)
        old = self.assistant(f)
        f.provider({"route": "personal"})
        calls = len(f.calls())
        p = self.restart(f, old)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("would move its work to another provider", p.stderr)
        self.assertEqual({c[0] for c in f.calls()[calls:]}, {"get"})
        # On the same route it starts with a handoff on today's settings for the Assistant's role.
        f.provider({"route": "azure-foundry", **CLAUDE, "coordinator_claude_deployment": "newer"})
        p = self.restart(f, old)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        [one] = [c for c in f.calls() if c[0] == "template" and "-az-" in c[1]][-1:]
        self.assertIn("--model newer", re.search(r"^command: (.+)$", one[2], re.M).group(1))
        self.assertIn("You are taking over this tab", one[2])



@la.ON_CI
class Fork(unittest.TestCase):
    """The window's and the web's fork ask the launch owner first (`launch run --role agent --slot fork --replaces
    TERMINAL --argv FORK --check`): a fork is a tab agent continuing the conversation, so the owner plans it from the
    forked agent's recorded binding and refuses what a tab agent can't carry. The window then makes the tab."""

    FORK = ["claude", "--resume", SESSION, "--fork-session"]

    def check(self, f, address):
        return f.run("launch", "run", "--role", "agent", "--space", "sp1", "--slot", "fork", "--replaces", address,
                     "--argv", json.dumps(self.FORK), "--check", "--json")

    def test_a_personal_fork_is_admitted_and_one_on_azure_is_refused_by_the_owner(self):
        f = Fixture(self)
        f.seed(address="t60", state="live", pid=60, cwd=f.repo, argv=["claude"], labels={"herdr.space": "sp1"})
        p = self.check(f, "t60")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(json.loads(p.stdout), {"admitted": True, "identity": "agent:local/sp1/fork", "route": "personal"})
        # An Assistant that started on Azure Foundry: a tab agent would move its conversation to Personal.
        f.provider({"route": "azure-foundry", **CLAUDE, "coordinator_claude_deployment": "assistant-deployment"})
        azure = f.new_assistant("--label", "herdr.space=sp1")
        p = self.check(f, azure)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("conversation is recorded on Azure Foundry", json.loads(p.stdout)["error"])
        self.assertIn("tab agent", json.loads(p.stdout)["error"])
        # A Personal conversation under an Azure route now: a tab agent starts Personal only, said as A2 says it.
        p = self.check(f, "t60")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("a tab agent starts Personal only", json.loads(p.stdout)["error"])
        # A check runs nothing.
        self.assertEqual([c for c in f.calls() if c[:1] == ["run"] and "herdr.launch=" not in " ".join(c)], [])
        self.assertEqual(len([c for c in f.calls() if c[:1] == ["run"]]), 1)  # the Assistant's own new start only


if __name__ == "__main__":
    unittest.main()
