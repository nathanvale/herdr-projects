"""Launch admission (herdr_task/launch_admission.py, L1) across herdr-task's own command line and
mods/coordinator/restart.sh: every start is claimed in a durable journal before its first effect,
rechecked and recorded as sent before `hc run`, and confirmed only by hc's reply or a terminal
carrying its launch id. Each test reopens the journal and the task list as files, apart from the
process that wrote them.

These run on CI only, as herdr-task's other command-line tests: HOME stays the account's own, the
task lists, settings and templates are throwaway ones (herdr-task's own overrides), and `hc` is a
stateful stand-in first on PATH that keeps its terminals in a file, so no agent, terminal or model
request exists. They prove what herdr-task does with its journal; they don't prove herdr-core's
own receipts (there are none), a real crash of a real host, or an agent's sign-in."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "mods", "tasks", "bin")
RESTART = os.path.join(ROOT, "mods", "coordinator", "restart.sh")
CI = os.environ.get("CI") == "true"
ON_CI = unittest.skipUnless(CI, "runs only on CI: herdr-task's commands never run from a test on a person's machine")
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"

# hc with terminals kept in FAKE_HC_STATE. `run` answers as FAKE_HC_MODE says (ok, lost: started but
# no reply, hidden: no reply and no terminal, crash: started, then its caller is killed); a call whose
# words contain FAKE_HC_GATE_MATCH waits while FAKE_HC_GATE exists (FAKE_HC_GATE.reached says it got
# there). `get` answers only for terminals seeded with "keep" (an Assistant), so a started agent's
# watcher (_track) finds it gone and ends.
FAKE_HC = r'''#!/usr/bin/env python3
import fcntl, json, os, signal, sys, time
args = sys.argv[1:]
with open(os.environ["FAKE_HC_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
gate, match = os.environ.get("FAKE_HC_GATE"), os.environ.get("FAKE_HC_GATE_MATCH")
if gate and match and os.path.exists(gate) and match in " ".join(args):
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
def labels_of(words):
    out = {}
    for i, a in enumerate(words):
        if a == "--label" and i + 1 < len(words):
            k, _, v = words[i + 1].partition("=")
            out[k] = v
    return out
verb = args[0] if args else ""
if verb == "run":
    words = args[1:args.index("--")] if "--" in args else args[1:]
    mode = os.environ.get("FAKE_HC_MODE", "ok")
    try:
        with open(os.environ["FAKE_HC_MODE_FILE"]) as f:
            mode = f.read().strip() or mode
    except (KeyError, OSError):
        pass
    st["n"] += 1
    t = {"address": "t%d" % st["n"], "state": "live", "labels": labels_of(words)}
    if mode != "hidden":
        st["terminals"].append(t)
    save()
    if mode == "ok":
        print(json.dumps({"address": t["address"], "first_message": {"sent": True}}))
        sys.exit(0)
    if mode == "crash":
        os.kill(os.getppid(), signal.SIGKILL)
        time.sleep(1)
    print("hc: timed out waiting for the terminal", file=sys.stderr)
    sys.exit(1)
if verb == "ls":
    want = None
    if "--label" in args:
        want = args[args.index("--label") + 1].partition("=")
    rows = [t for t in st["terminals"] if not want or t["labels"].get(want[0]) == want[2]]
    print(json.dumps({"terminals": rows}))
    sys.exit(0)
if verb == "get":
    for t in st["terminals"]:
        if t.get("keep") and args[1:2] in ([t["address"]], [t.get("name")]):
            print(json.dumps(t))
            sys.exit(0)
    sys.exit(1)
if verb in ("label", "kill", "rm", "read", "send", "wait"):
    sys.exit(0)
sys.exit(1)
'''

# Settings' start limits off (the runner's own load never decides what a tick starts), and a worker
# selection a test can change. The space's folder is the fixture's repo.
PERSONAL = {"version": 1, "everywhere": {"worker": {"agent": "claude", "model": "first-model"},
                                         "machine": {"start_load": None, "start_memory": None, "start_disk": None}},
            "spaces": {"sp1": {"folder": None}}}
AZURE = {"route": "azure-foundry", "claude_resource": "example", "claude_deployment": "claude-deployment"}


class Fixture:
    """A throwaway git repo, task store, settings file and templates folder, and a stateful hc."""

    def __init__(self, test, settings=PERSONAL):
        self.test = test
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        for args in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True)
        fake = os.path.join(self.tmp, "bin")
        os.makedirs(fake)
        with open(os.path.join(fake, "hc"), "w") as f:
            f.write(FAKE_HC)
        os.chmod(os.path.join(fake, "hc"), 0o755)
        self.log, self.state = os.path.join(self.tmp, "hc.log"), os.path.join(self.tmp, "hc.json")
        self.gate, self.mode = os.path.join(self.tmp, "gate"), os.path.join(self.tmp, "mode")
        self.settings = os.path.join(self.tmp, "shepherdr.json")
        self.store = os.path.join(self.tmp, "tasks")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_", "ANTHROPIC_", "CLAUDE_", "AZURE_", "OPENAI_"))}
        self.env.update(PATH=fake + os.pathsep + os.environ.get("PATH", ""), SHELL="/bin/sh", FAKE_HC_LOG=self.log,
                        FAKE_HC_STATE=self.state, FAKE_HC_GATE=self.gate, FAKE_HC_MODE_FILE=self.mode,
                        HERDR_TASK_STORE=self.store, HERDR_TASK_SETTINGS=self.settings,
                        HERDR_TASK_TEMPLATES=os.path.join(self.tmp, "templates"))
        if settings is not None:
            self.write_settings(settings)
        self.procs = []
        test.addCleanup(self.reap)

    def reap(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait()

    def write_settings(self, d):
        d = json.loads(json.dumps(d))
        for sp in (d.get("spaces") or {}).values():
            if isinstance(sp, dict) and "folder" in sp and sp["folder"] is None:
                sp["folder"] = self.repo
        with open(self.settings, "w") as f:
            json.dump(d, f)

    def argv(self, *args):
        return [sys.executable, os.path.join(BIN, "herdr-task"), *args]

    def run(self, *args):
        return subprocess.run(self.argv(*args), capture_output=True, text=True, env=self.env, timeout=120)

    def ok(self, *args):
        p = self.run(*args, "--json")
        self.test.assertEqual(p.returncode, 0, f"herdr-task {' '.join(args)}: {p.stdout}{p.stderr}")
        return json.loads(p.stdout)

    def refused(self, *args):
        """A refusal as --json gives it: exit 1 and the reason on stdout."""
        p = self.run(*args, "--json")
        self.test.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def background(self, *args):
        p = subprocess.Popen(self.argv(*args, "--json"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        self.procs.append(p)
        return p

    def hold(self, match):
        """The next hc call whose words contain `match` waits until release()."""
        self.env["FAKE_HC_GATE_MATCH"] = match
        open(self.gate, "w").close()

    def reached(self):
        for _ in range(600):
            if os.path.exists(self.gate + ".reached"):
                return
            time.sleep(0.05)
        self.test.fail("the held hc call was never made")

    def release(self):
        os.remove(self.gate)

    def set_mode(self, mode):
        with open(self.mode, "w") as f:
            f.write(mode)

    def calls(self):
        try:
            with open(self.log) as f:
                return [json.loads(line) for line in f]
        except OSError:
            return []

    def runs(self):
        """The agents hc was asked to start, each carrying its launch label (the scheduler's own terminal,
        which a start ensures afterwards, isn't one)."""
        return [c for c in self.calls() if c[:1] == ["run"] and any(a.startswith("herdr.launch=") for a in c)]

    def carrying(self, lid):
        return [t["address"] for t in self.terminals() if t["labels"].get("herdr.launch") == lid]

    def terminals(self):
        with open(self.state) as f:
            return json.load(f)["terminals"]

    def seed(self, **t):
        try:
            with open(self.state) as f:
                st = json.load(f)
        except OSError:
            st = {"terminals": [], "n": 100}
        st["terminals"].append(t)
        with open(self.state, "w") as f:
            json.dump(st, f)

    def finish(self, address):
        with open(self.state) as f:
            st = json.load(f)
        for t in st["terminals"]:
            if t["address"] == address:
                t["state"] = "finished"
        with open(self.state, "w") as f:
            json.dump(st, f)

    def journal(self):
        """The launch journal as a file, read apart from herdr-task."""
        with open(os.path.join(self.store, ".launches.json")) as f:
            return json.load(f)

    def starts(self, prefix="task:"):
        return sorted((r for r in self.journal()["launches"].values() if r["identity"].startswith(prefix)), key=lambda r: r["at"])

    def task(self, tid=1):
        lists = [os.path.join(self.store, n) for n in os.listdir(self.store) if n.endswith(".json") and not n.startswith(".")]
        for p in lists:
            with open(p) as f:
                d = json.load(f)
            for t in d.get("tasks", []):
                if t["id"] == tid:
                    return t
        return None

    def add(self, *extra):
        return self.ok("add", "Fix login", "--folder", self.repo, "--space", "sp1", "--here", *extra)["id"]

    def start(self, tid=1):
        return self.run("start", str(tid), "--folder", self.repo, "--space", "sp1", "--now", "--json")

    def label_of(self, run):
        return next(run[i + 1].split("=", 1)[1] for i, a in enumerate(run) if a == "--label" and run[i + 1].startswith("herdr.launch="))


@ON_CI
class TaskStarts(unittest.TestCase):

    def test_a_start_is_claimed_sent_and_confirmed_under_one_launch_id(self):
        f = Fixture(self)
        f.add()
        p = f.start()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        [rec] = f.starts()
        self.assertRegex(rec["launch"], UUID)
        self.assertEqual((rec["state"], rec["address"], rec["role"]), ("confirmed", json.loads(p.stdout)["terminal"], "task"))
        [run] = f.runs()
        self.assertEqual(f.label_of(run), rec["launch"])
        self.assertEqual(f.task()["agents"][0]["launch"], rec["launch"])
        # Its claim is held until a later start sees the task list holding its agent, then released.
        self.assertEqual((f.journal()["claims"], rec["recorded"]), ({rec["identity"]: rec["launch"]}, False))
        f.finish(rec["address"])
        self.assertEqual(f.run("switch", "1", "--folder", f.repo, "--space", "sp1", "--json").returncode, 0)
        old, new = f.starts()
        self.assertEqual((old["recorded"], f.journal()["claims"]), (True, {new["identity"]: new["launch"]}))

    def test_competing_start_after_a_crash_before_dispatch_waits_for_recover(self):
        """The first start dies (SIGKILL) after its claim, before sending: the next start refuses
        with the exact recover command, which revokes it; then a start goes once."""
        f = Fixture(self)
        f.add()
        f.hold("get repo-1-fix-login")
        a = f.background("start", "1", "--folder", f.repo, "--space", "sp1", "--now")
        f.reached()
        [rec] = f.starts()
        self.assertEqual(rec["state"], "never-submitted")
        a.send_signal(signal.SIGKILL)
        a.wait()
        f.release()
        self.assertEqual(f.starts()[0]["state"], "never-submitted")
        before = f.task()
        err = f.refused("start", "1", "--folder", f.repo, "--space", "sp1", "--now")["error"]
        self.assertIn(f"herdr-task launch recover {rec['identity']} {rec['launch']}", err)
        self.assertEqual(f.task(), before)
        self.assertEqual(f.runs(), [])
        out = f.ok("launch", "recover", rec["identity"], rec["launch"])
        self.assertEqual((out["state"], out["revoked"]), ("cancelled", True))
        p = f.start()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len(f.runs()), 1)
        self.assertEqual([r["state"] for r in f.starts()], ["cancelled", "confirmed"])

    def test_a_delayed_sender_is_fenced_after_recovery(self):
        """recover revokes a claim whose sender still runs (paused in preparation): when it
        resumes it sends nothing, and a replacement start keeps its own grant."""
        f = Fixture(self)
        f.add()
        f.hold("get repo-1-fix-login")
        a = f.background("start", "1", "--folder", f.repo, "--space", "sp1", "--now")
        f.reached()
        [rec] = f.starts()
        f.ok("launch", "recover", rec["identity"], rec["launch"])
        f.release()
        out, _ = a.communicate(timeout=60)
        self.assertEqual(a.returncode, 1)
        self.assertIn("revoked or already used", json.loads(out)["error"])
        self.assertEqual(f.runs(), [])
        p = f.start()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        old, new = f.starts()
        self.assertEqual((old["launch"], old["state"], old.get("revoked")), (rec["launch"], "cancelled", True))
        self.assertEqual(new["state"], "confirmed")
        self.assertEqual(f.label_of(f.runs()[0]), new["launch"])

    def test_shutdown_before_dispatch_cancels_its_own_claim(self):
        f = Fixture(self)
        f.add()
        f.hold("get repo-1-fix-login")
        a = f.background("start", "1", "--folder", f.repo, "--space", "sp1", "--now")
        f.reached()
        a.send_signal(signal.SIGTERM)
        a.wait(timeout=60)
        f.release()
        [rec] = f.starts()
        self.assertEqual(rec["state"], "cancelled")
        self.assertIn("stopped before it was sent", rec["reason"])
        self.assertEqual((f.runs(), f.journal()["claims"]), ([], {}))
        self.assertEqual(f.task()["state"], "todo")

    def test_a_crash_after_dispatch_stays_uncertain_until_its_terminal_is_found(self):
        f = Fixture(self)
        f.add()
        f.set_mode("crash")
        p = f.start()
        self.assertEqual(p.returncode, -signal.SIGKILL)
        f.set_mode("ok")
        [rec] = f.starts()
        self.assertEqual(rec["state"], "submission-uncertain")
        # The task list never saw its agent (herdr-task died before saving): still to do.
        self.assertEqual((f.task()["state"], f.task()["agents"]), ("todo", []))
        err = f.refused("start", "1", "--folder", f.repo, "--space", "sp1", "--now")["error"]
        self.assertIn(f"herdr-task launch reconcile {rec['identity']} {rec['launch']}", err)
        refused = f.refused("launch", "recover", rec["identity"], rec["launch"])
        self.assertIn("can't be released here", refused["error"])
        self.assertEqual(refused["launch"]["state"], "submission-uncertain")
        self.assertEqual(len(f.runs()), 1)
        out = f.ok("launch", "reconcile", rec["identity"], rec["launch"])
        self.assertEqual((out["state"], [out["address"]], out["launch"], out["attached"]), ("confirmed", f.carrying(rec["launch"]), rec["launch"], True))
        # Its agent is on its task now, as its own start would have put it, and nothing starts it again.
        t = f.task()
        self.assertEqual((t["state"], [a["launch"] for a in t["agents"]]), ("running", [rec["launch"]]))
        self.assertEqual(len(f.runs()), 1)

    def test_a_lost_reply_is_confirmed_by_its_own_launch_label(self):
        f = Fixture(self)
        f.add()
        f.set_mode("lost")
        p = f.start()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        [rec] = f.starts()
        self.assertEqual((rec["state"], rec.get("reconciled"), rec["address"]), ("confirmed", True, json.loads(p.stdout)["terminal"]))
        self.assertEqual(len(f.runs()), 1)

    def test_an_unconfirmed_reply_keeps_its_launch_id_and_is_never_retried(self):
        f = Fixture(self)
        f.add()
        f.set_mode("hidden")
        refused = json.loads(f.start().stdout)
        [rec] = f.starts()
        self.assertEqual(refused["launch"], {"launch": rec["launch"], "identity": rec["identity"], "state": "submission-uncertain"})
        self.assertEqual(rec["state"], "submission-uncertain")
        f.set_mode("ok")
        self.assertIn("may have started an agent", f.refused("start", "1", "--folder", f.repo, "--space", "sp1", "--now")["error"])
        # An empty lookup proves nothing: reconcile keeps it, and still nothing is sent again.
        still = f.refused("launch", "reconcile", rec["identity"], rec["launch"])
        self.assertIn("doesn't prove it never started", still["error"])
        self.assertEqual(len(f.runs()), 1)
        # Its terminal shows up late (delivered after the reply was lost): the same id confirms it.
        f.seed(address="t50", state="live", labels={"herdr.launch": rec["launch"]})
        out = f.ok("launch", "reconcile", rec["identity"], rec["launch"])
        self.assertEqual((out["launch"], out["state"], out["address"]), (rec["launch"], "confirmed", "t50"))
        self.assertEqual(len(f.runs()), 1)

    def test_a_tick_start_whose_reply_was_lost_is_never_started_again(self):
        """Round 1's blocker: an unconfirmed tick start keeps the task started (not queued), and once
        reconciled its agent is on the task, so later ticks send nothing."""
        f = Fixture(self)
        first, second = f.add(), f.add("--after", "1")
        f.ok("start", str(second), "--folder", f.repo, "--space", "sp1")
        f.ok("rm", str(first), "--folder", f.repo)
        f.set_mode("hidden")
        self.assertEqual(f.ok("tick", "--folder", f.repo)["started"], [])
        f.set_mode("ok")
        [rec] = f.starts()
        t = f.task(second)
        self.assertEqual((rec["state"], t["state"], "queue" in t), ("submission-uncertain", "running", False))
        self.assertIn(rec["launch"], t["attention"])
        self.assertEqual(f.ok("tick", "--folder", f.repo)["started"], [])
        f.seed(address="t60", state="live", labels={"herdr.launch": rec["launch"]})
        f.ok("launch", "reconcile", rec["identity"], rec["launch"])
        self.assertEqual(f.ok("tick", "--folder", f.repo)["started"], [])
        self.assertEqual([a["address"] for a in f.task(second)["agents"]], ["t60"])
        self.assertEqual(len(f.runs()), 1)

    def test_a_confirmed_start_lost_before_its_list_is_saved_is_never_started_again(self):
        """Round 2's major: the tick confirms the first queued task, then is stopped (SIGTERM) inside the
        second's start, so its task list is never saved. The next tick finds the first task's confirmed,
        unrecorded start in the journal, puts its agent on the task, and starts nothing for it."""
        f = Fixture(self)
        blocker, first, second = f.add(), f.add("--after", "1"), f.add("--after", "1")
        f.ok("start", str(first), "--folder", f.repo, "--space", "sp1")
        f.ok("start", str(second), "--folder", f.repo, "--space", "sp1")
        f.ok("rm", str(blocker), "--folder", f.repo)
        f.hold(f"get repo-{second}-fix-login")
        a = f.background("tick", "--folder", f.repo)
        f.reached()
        a.send_signal(signal.SIGTERM)
        a.wait(timeout=60)
        f.release()
        self.assertEqual((f.task(first)["state"], len(f.runs())), ("queued", 1))
        done = next(r for r in f.starts() if r["identity"].endswith(f"#{first}"))
        self.assertEqual((done["state"], done["recorded"], f.journal()["claims"].get(done["identity"])), ("confirmed", False, done["launch"]))
        f.ok("tick", "--folder", f.repo)
        t = f.task(first)
        self.assertEqual((t["state"], [x["launch"] for x in t["agents"]]), ("running", [done["launch"]]))
        self.assertEqual(len([r for r in f.runs() if f"herdr.task=" in " ".join(r) and f"#{first}" in " ".join(r)]), 1)

    def test_a_command_refusing_a_lost_record_says_how_to_repair_it(self):
        """Round 3: a confirmed start its task list lost (herdr-task ended before saving; here the list
        is put back as it would then be) refuses a switch truthfully, naming reconcile, which repairs it."""
        f = Fixture(self)
        f.add()
        self.assertEqual(f.start().returncode, 0)
        [rec] = f.starts()
        path = next(os.path.join(f.store, n) for n in os.listdir(f.store) if n.endswith(".json") and not n.startswith("."))
        with open(path) as fh:
            d = json.load(fh)
        t = next(x for x in d["tasks"] if x["id"] == 1)
        t.update(state="todo", agents=[])
        with open(path, "w") as fh:
            json.dump(d, fh)
        err = f.refused("switch", "1", "--folder", f.repo, "--space", "sp1")["error"]
        self.assertIn(f"herdr-task launch reconcile {rec['identity']} {rec['launch']}", err)
        self.assertNotIn("on the task now", err)
        self.assertEqual(f.task()["agents"], [])
        out = f.ok("launch", "reconcile", rec["identity"], rec["launch"])
        self.assertEqual((out["attached"], [a["launch"] for a in f.task()["agents"]]), (True, [rec["launch"]]))
        self.assertNotIn(rec["identity"], f.journal()["claims"])
        self.assertEqual(len(f.runs()), 1)

    def test_an_unconfirmed_resume_keeps_its_launch_id(self):
        f = Fixture(self)
        f.add()
        self.assertEqual(f.start().returncode, 0)
        f.set_mode("hidden")
        refused = f.refused("resume", "1", "--folder", f.repo, "--space", "sp1")
        first, second = f.starts()
        self.assertEqual((refused["launch"]["launch"], second["state"]), (second["launch"], "submission-uncertain"))
        f.set_mode("ok")
        self.assertIn("may have started an agent", f.refused("switch", "1", "--folder", f.repo, "--space", "sp1")["error"])
        self.assertIn("held decision", f.refused("launch", "recover", second["identity"], second["launch"])["error"])
        self.assertEqual(len(f.runs()), 2)

    def test_its_assistant_changing_while_it_prepares_refuses_before_dispatch(self):
        f = Fixture(self)
        f.seed(address="t900", state="live", keep=True, template="assistant", labels={"herdr.space": "sp1", "herdr.tab": "tb1"})
        f.add()
        f.hold("get repo-1-fix-login")
        a = f.background("start", "1", "--folder", f.repo, "--space", "sp1", "--now")
        f.reached()
        self.assertEqual(f.starts()[0]["parent"], "t900")
        f.finish("t900")
        f.release()
        out, _ = a.communicate(timeout=60)
        self.assertEqual(a.returncode, 1)
        self.assertIn("Its Assistant (t900) ended or was replaced", json.loads(out)["error"])
        self.assertEqual([r["state"] for r in f.starts()], ["cancelled"])
        self.assertEqual(f.runs(), [])

    def test_settings_changed_before_recording_records_nothing(self):
        f = Fixture(self)
        f.add()
        # Preflight's last hc call is its Assistant lookup, after the revision is taken.
        f.hold("herdr.role=coordinator")
        a = f.background("start", "1", "--folder", f.repo, "--space", "sp1", "--now")
        f.reached()
        changed = json.loads(json.dumps(PERSONAL))
        changed["everywhere"]["worker"]["model"] = "second-model"
        f.write_settings(changed)
        f.release()
        out, _ = a.communicate(timeout=60)
        self.assertEqual(a.returncode, 1)
        self.assertIn("changed before it was recorded", json.loads(out)["error"])
        self.assertFalse(os.path.exists(os.path.join(f.store, ".launches.json")) and f.starts())
        self.assertEqual(f.runs(), [])

    def test_settings_changed_before_submission_cancel_the_claim(self):
        for change in ("selection", "route", "corrupt"):
            with self.subTest(change=change):
                f = Fixture(self)
                f.add()
                f.hold("get repo-1-fix-login")
                a = f.background("start", "1", "--folder", f.repo, "--space", "sp1", "--now")
                f.reached()
                d = json.loads(json.dumps(PERSONAL))
                if change == "selection":
                    d["everywhere"]["worker"]["model"] = "second-model"
                    f.write_settings(d)
                elif change == "route":
                    d["everywhere"]["provider"] = AZURE
                    f.write_settings(d)
                else:
                    with open(f.settings, "w") as fh:
                        fh.write("{ not json")
                f.release()
                out, _ = a.communicate(timeout=60)
                self.assertEqual(a.returncode, 1)
                self.assertEqual([r["state"] for r in f.starts()], ["cancelled"])
                self.assertEqual((f.runs(), f.journal()["claims"]), ([], {}))
                self.assertEqual(f.task()["state"], "todo")

    def test_unrelated_settings_edits_do_not_refuse(self):
        f = Fixture(self)
        f.add()
        f.hold("get repo-1-fix-login")
        a = f.background("start", "1", "--folder", f.repo, "--space", "sp1", "--now")
        f.reached()
        d = json.loads(json.dumps(PERSONAL))
        d["everywhere"]["tasks"] = {"archive_after": 30}
        d["everywhere"]["provider"] = {"route": "personal", "claude_resource": "half-set"}
        f.write_settings(d)
        f.release()
        out, err = a.communicate(timeout=60)
        self.assertEqual(a.returncode, 0, out + err)
        self.assertEqual([r["state"] for r in f.starts()], ["confirmed"])

    def test_a_tick_start_refused_after_its_claim_keeps_the_task_queued(self):
        """The tick saves the task after a refused start: it keeps its place in the queue, not a
        running state with no agent."""
        f = Fixture(self)
        first, second = f.add(), f.add("--after", "1")
        self.assertEqual(f.ok("start", str(second), "--folder", f.repo, "--space", "sp1")["queued"], True)
        f.ok("rm", str(first), "--folder", f.repo)
        f.hold("get repo-2-fix-login")
        a = f.background("tick", "--folder", f.repo)
        f.reached()
        # Its queued plan keeps its argv, so what changes under it here is the route.
        d = json.loads(json.dumps(PERSONAL))
        d["everywhere"]["provider"] = AZURE
        f.write_settings(d)
        f.release()
        out, err = a.communicate(timeout=60)
        self.assertEqual(a.returncode, 0, out + err)
        self.assertEqual(json.loads(out)["started"], [])
        t = f.task(second)
        self.assertEqual((t["state"], t["agents"], "queue" in t), ("queued", [], True))
        self.assertTrue(t["attention"].startswith("Couldn't start: Azure Foundry is set"), t["attention"])
        self.assertEqual(f.runs(), [])
        self.assertEqual([r["state"] for r in f.starts()], ["cancelled"])
        # Back on Personal the next tick starts it once.
        f.write_settings(PERSONAL)
        self.assertEqual([x["id"] for x in f.ok("tick", "--folder", f.repo)["started"]], [second])
        self.assertEqual(len(f.runs()), 1)


@ON_CI
class SettingsFile(unittest.TestCase):
    """A settings file that is there but can't be read refuses a start; a missing one is Personal (P17-7)."""

    def test_corrupt_or_unreadable_settings_refuse_before_any_effect(self):
        for kind in ("corrupt", "not-an-object", "unreadable"):
            with self.subTest(kind=kind):
                f = Fixture(self)
                f.add()
                if kind == "corrupt":
                    with open(f.settings, "w") as fh:
                        fh.write('{"everywhere": {"provider": ')
                elif kind == "not-an-object":
                    with open(f.settings, "w") as fh:
                        fh.write("[]")
                else:
                    os.remove(f.settings)
                    os.makedirs(f.settings)  # there, and can't be read as a file (as root can read any mode)
                before = f.task()
                err = f.refused("start", "1", "--folder", f.repo, "--space", "sp1", "--now")["error"]
                self.assertIn("are there but can't be read", err)
                self.assertNotIn('{"everywhere"', err)
                self.assertEqual((f.task(), f.runs()), (before, []))
                self.assertIn("can't be read", f.refused("provider", "plan", "--folder", f.repo, "--agent", "claude")["error"])

    def test_missing_settings_keep_personal(self):
        f = Fixture(self, settings=None)
        f.add()
        p = f.start()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual([r["state"] for r in f.starts()], ["confirmed"])
        self.assertEqual(f.ok("provider", "plan", "--folder", f.repo, "--agent", "claude")["route"], "personal")


@ON_CI
class SettingsOwner(unittest.TestCase):
    """Carried to L1 from A1: a Serve-from client's settings file is the serving machine's, written
    without pushed_from (service/sync.ts). Its herdr-core node record says so, and Azure refuses."""

    def docs(self, f, docs):
        state = os.path.join(f.tmp, "state")
        f.env["XDG_STATE_HOME"] = state
        os.makedirs(os.path.join(state, "herdr-core", "default"), exist_ok=True)
        with open(os.path.join(state, "herdr-core", "default", "docs.json"), "w") as fh:
            fh.write(docs if isinstance(docs, str) else json.dumps(docs))

    def test_a_serve_from_copy_refuses_azure_and_the_serving_machine_plans_it(self):
        node = lambda serving: {"shepherdr.node": {"value": {"id": "n1", "serving": serving}, "version": 3},
                                "shepherdr.host": {"value": {"id": "n1" if serving else "n2"}, "version": 1}}
        for docs, words in ((node(False), "kept in step with the machine that serves the web app"),
                            ("{ broken", "can't be read now"), (node(True), None)):
            with self.subTest(docs=str(docs)[:30]):
                f = Fixture(self)
                d = json.loads(json.dumps(PERSONAL))
                d["everywhere"]["provider"] = AZURE
                f.write_settings(d)
                self.docs(f, docs)
                p = f.run("provider", "plan", "--folder", f.repo, "--agent", "claude", "--json")
                if words:
                    self.assertEqual(p.returncode, 1)
                    self.assertIn(words, json.loads(p.stdout)["error"])
                    f.add()
                    self.assertIn(words, f.refused("start", "1", "--folder", f.repo, "--space", "sp1", "--now")["error"])
                    self.assertEqual(f.runs(), [])
                else:
                    self.assertEqual((p.returncode, json.loads(p.stdout)["dispatch"]), (0, "held"))

    def test_personal_never_reads_whose_file_it_is(self):
        f = Fixture(self)
        self.docs(f, "{ broken")
        f.add()
        self.assertEqual(f.start().returncode, 0)
        self.assertEqual(len(f.runs()), 1)


@ON_CI
class ClaudeFolder(unittest.TestCase):
    """Carried to L1 from C1: a task's Claude Code start passes its folder (CLAUDE_CONFIG_DIR)
    explicitly and records it; a switch carries the previous agent's own folder."""

    EXPORT = 'export CLAUDE_CONFIG_DIR="$1"; shift; "$@"; exec "$0" -i'

    def folder_word(self, run):
        """The folder the person's shell exports before it runs claude (so a claude() function still runs)."""
        i = run.index(self.EXPORT)
        self.assertEqual((run[i + 1], run[i + 3]), ("/bin/sh", "claude"))
        return run[i + 2]

    def exported(self, run):
        return self.EXPORT in run or any(a.startswith("CLAUDE_CONFIG_DIR=") for a in run)

    def test_a_start_carries_and_records_its_folder_and_a_switch_keeps_it(self):
        f = Fixture(self)
        mine, other = os.path.join(f.tmp, "profile"), os.path.join(f.tmp, "other-profile")
        f.env["CLAUDE_CONFIG_DIR"] = mine
        f.add()
        self.assertEqual(f.start().returncode, 0)
        [rec] = f.starts()
        self.assertEqual((rec["config_dir"], f.task()["agents"][0]["config_dir"], self.folder_word(f.runs()[0])), (mine, mine, mine))
        f.finish(rec["address"])
        f.env["CLAUDE_CONFIG_DIR"] = other
        self.assertEqual(f.run("switch", "1", "--folder", f.repo, "--space", "sp1", "--json").returncode, 0)
        self.assertEqual((f.starts()[1]["config_dir"], self.folder_word(f.runs()[1])), (mine, mine))

    def test_no_folder_set_adds_nothing_and_a_bad_one_refuses(self):
        f = Fixture(self)
        f.add()
        f.env["CLAUDE_CONFIG_DIR"] = "relative/profile"
        self.assertIn("isn't one absolute path", f.refused("start", "1", "--folder", f.repo, "--space", "sp1", "--now")["error"])
        self.assertEqual(f.runs(), [])
        del f.env["CLAUDE_CONFIG_DIR"]
        self.assertEqual(f.start().returncode, 0)
        [rec] = f.starts()
        self.assertIsNone(rec["config_dir"])
        self.assertFalse(self.exported(f.runs()[0]))
        self.assertNotIn("config_dir", f.task()["agents"][0])

    def test_an_agent_with_no_recorded_folder_is_never_moved_to_the_callers(self):
        """Round 3: a resume after an inherited start (no folder recorded) adds none, whatever the
        caller's own CLAUDE_CONFIG_DIR is, so the conversation stays on its profile."""
        f = Fixture(self)
        f.add()
        self.assertEqual(f.start().returncode, 0)
        f.finish(f.starts()[0]["address"])
        f.env["CLAUDE_CONFIG_DIR"] = os.path.join(f.tmp, "callers-profile")
        self.assertEqual(f.run("resume", "1", "--folder", f.repo, "--space", "sp1", "--json").returncode, 0)
        self.assertIsNone(f.starts()[1]["config_dir"])
        self.assertFalse(self.exported(f.runs()[1]))

    def test_a_queued_start_keeps_the_folder_it_was_queued_with(self):
        f = Fixture(self)
        mine = os.path.join(f.tmp, "profile")
        first, second = f.add(), f.add("--after", "1")
        f.env["CLAUDE_CONFIG_DIR"] = mine
        self.assertTrue(f.ok("start", str(second), "--folder", f.repo, "--space", "sp1")["queued"])
        del f.env["CLAUDE_CONFIG_DIR"]
        f.ok("rm", str(first), "--folder", f.repo)
        f.ok("tick", "--folder", f.repo)
        [run] = f.runs()
        self.assertEqual((self.folder_word(run), f.starts()[0]["config_dir"]), (mine, mine))


@ON_CI
class AssistantStarts(unittest.TestCase):
    """`herdr-task launch run`, the one way an Assistant's (or a tab agent's) start reaches hc."""

    WORDS = ["--bg", "--json", "--no-parent", "--keep", "--cwd", "/tmp", "--label", "herdr.role=coordinator",
             "--label", "herdr.coordinator.space=sp1", "assistant", "hello"]

    def run_start(self, f, *extra, words=None):
        return f.run("launch", "run", "--role", "coordinator", "--space", "sp1", *extra, "--json", "--", *(words or self.WORDS))

    def test_personal_starts_once_with_its_launch_label(self):
        f = Fixture(self)
        p = self.run_start(f)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout)
        [rec] = f.starts("coordinator:")
        self.assertEqual((rec["identity"], rec["state"], out["launch"], out["address"]), ("coordinator:local/sp1", "confirmed", rec["launch"], "t1"))
        [run] = f.runs()
        self.assertEqual(run[:3], ["run", "--label", f"herdr.launch={rec['launch']}"])
        self.assertEqual(run[3:], self.WORDS)  # the site's own words, as they were; --json already there

    def test_azure_or_unreadable_settings_refuse_before_hc(self):
        for kind in ("azure", "azure-remote", "corrupt"):
            with self.subTest(kind=kind):
                f = Fixture(self)
                d = json.loads(json.dumps(PERSONAL))
                if kind == "corrupt":
                    with open(f.settings, "w") as fh:
                        fh.write("{")
                else:
                    d["everywhere"]["provider"] = AZURE
                    f.write_settings(d)
                words = ["--on", "vm1", *self.WORDS] if kind == "azure-remote" else None
                p = self.run_start(f, words=words)
                self.assertEqual(p.returncode, 1, p.stdout)
                err = json.loads(p.stdout)["error"]
                self.assertIn({"azure": "can't carry a launch plan yet", "azure-remote": "would run on vm1",
                               "corrupt": "can't be read"}[kind], err)
                self.assertEqual(f.calls(), [])
                self.assertFalse(os.path.exists(os.path.join(f.store, ".launches.json")) and f.starts("coordinator:"))
                check = f.run("launch", "run", "--role", "coordinator", "--space", "sp1", "--check", "--json")
                self.assertEqual(check.returncode, 1)

    def test_a_competing_start_of_the_same_assistant_is_refused_while_one_is_in_flight(self):
        f = Fixture(self)
        f.hold("assistant hello")
        a = subprocess.Popen(f.argv("launch", "run", "--role", "coordinator", "--space", "sp1", "--json", "--", *self.WORDS),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=f.env)
        f.procs.append(a)
        f.reached()
        self.assertEqual([r["state"] for r in f.starts("coordinator:")], ["submission-uncertain"])
        p = self.run_start(f)
        self.assertEqual(p.returncode, 1)
        self.assertIn("may have started an agent", json.loads(p.stdout)["error"])
        self.assertIn("may have started", json.loads(f.run("launch", "run", "--role", "coordinator", "--space", "sp1", "--check", "--json").stdout)["error"])
        f.release()
        a.communicate(timeout=60)
        self.assertEqual(a.returncode, 0)
        self.assertEqual(len(f.runs()), 1)
        # Another space's Assistant was never held by it, and once confirmed the same space starts again.
        self.assertEqual(self.run_start(f).returncode, 0)
        self.assertEqual(f.run("launch", "run", "--role", "coordinator", "--space", "sp2", "--json", "--", *self.WORDS).returncode, 0)

    def test_an_unconfirmed_assistant_start_keeps_its_launch_id(self):
        f = Fixture(self)
        f.set_mode("hidden")
        p = self.run_start(f)
        self.assertEqual(p.returncode, 1)
        out = json.loads(p.stdout)
        [rec] = f.starts("coordinator:")
        self.assertEqual(out["launch"]["launch"], rec["launch"])
        self.assertEqual(rec["state"], "submission-uncertain")
        f.set_mode("ok")
        self.assertEqual(self.run_start(f).returncode, 1)
        self.assertEqual(len(f.runs()), 1)

    def test_its_launch_label_is_the_owners_own(self):
        f = Fixture(self)
        p = self.run_start(f, words=["--label", "herdr.launch=00000000-0000-4000-8000-000000000000", *self.WORDS])
        self.assertEqual(p.returncode, 1)
        self.assertEqual(f.calls(), [])


@ON_CI
class RestartScript(unittest.TestCase):
    """mods/coordinator/restart.sh starts through `herdr-task launch run`, checked before it
    changes anything."""

    def restart(self, f, old="t900"):
        env = dict(f.env, HERDR_RESTART_RESUME="1")
        return subprocess.run(["bash", RESTART, old, json.dumps(["claude", "--resume", "abc"])], capture_output=True, text=True,
                              env=env, timeout=120)

    def seed_assistant(self, f):
        f.seed(address="t900", state="live", keep=True, template="assistant", cwd=f.repo,
               labels={"herdr.space": "sp1", "herdr.tab": "tb1", "herdr.role": "coordinator"})

    def test_a_restart_goes_through_the_journal(self):
        f = Fixture(self)
        self.seed_assistant(f)
        p = self.restart(f)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        [rec] = f.starts("coordinator:")
        self.assertEqual((rec["identity"], rec["state"]), ("coordinator:local/sp1", "confirmed"))
        [run] = f.runs()
        self.assertEqual(run[1:3], ["--label", f"herdr.launch={rec['launch']}"])
        self.assertEqual(p.stdout.strip(), rec["address"])
        self.assertIn(["kill", "t900"], f.calls())

    def test_a_restart_carries_the_old_agents_own_folder(self):
        """restart.sh reads the old Claude Code agent's folder from its process (C1's rule) and starts
        the new one there, recorded with its start."""
        f = Fixture(self)
        profile = os.path.join(f.tmp, "profile")
        agent = subprocess.Popen(["sleep", "60"], env={"PATH": os.environ["PATH"], "CLAUDE_CONFIG_DIR": profile})
        self.addCleanup(lambda: (agent.kill(), agent.wait()))
        f.seed(address="t900", state="live", keep=True, template="assistant", cwd=f.repo, status={"app": "claude-code"},
               foreground={"pid": agent.pid}, labels={"herdr.space": "sp1", "herdr.tab": "tb1", "herdr.role": "coordinator"})
        p = self.restart(f)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        [rec] = f.starts("coordinator:")
        [run] = f.runs()
        i = run.index("CLAUDE_CONFIG_DIR=" + profile)
        self.assertEqual((run[i - 1], run[i + 1], rec["config_dir"]), ("env", "claude", profile))

    def test_a_refused_restart_changes_nothing_and_says_why(self):
        f = Fixture(self)
        d = json.loads(json.dumps(PERSONAL))
        d["everywhere"]["provider"] = AZURE
        f.write_settings(d)
        self.seed_assistant(f)
        p = self.restart(f)
        self.assertEqual(p.returncode, 1)
        self.assertIn("can't carry a launch plan yet", p.stderr)
        verbs = [c[0] for c in f.calls()]
        self.assertEqual(verbs, ["get"])  # only its own look at the old agent: no read, label, run or kill
        self.assertFalse(os.path.exists(os.path.join(f.store, ".launches.json")) and f.starts("coordinator:"))


class StartSites(unittest.TestCase):
    """The five Assistant start sites reach hc only through launch admission (source gate: what
    each site runs; the process tests above prove the owner, service/launch-sites.test.ts the
    service's two)."""

    def read(self, path):
        with open(os.path.join(ROOT, path)) as f:
            return f.read()

    def test_no_site_runs_hc_run_itself(self):
        direct = {"service/actions.ts": 'hc(["run"', "service/spaces.ts": '["hc", "run"', "mods/chat/main.js": "await hc(args)",
                  "mods/coordinator/restart.sh": "$(hc run"}
        for path, words in direct.items():
            with self.subTest(path=path):
                text = self.read(path)
                self.assertNotIn(words, text)
                self.assertIn("launch run", text)
        self.assertNotIn("hc run", self.read("service/agents.ts").replace("herdr-task", ""))
        self.assertIn('join(APP, "mods", "coordinator", "restart.sh")', self.read("service/agents.ts"))


if __name__ == "__main__":
    unittest.main()
