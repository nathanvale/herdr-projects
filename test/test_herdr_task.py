"""herdr-task: every module compiles, the add-on switch it reads, and (on CI only, where HOME is
a throwaway) its commands start. On a person's machine herdr-task never runs with another HOME."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "mods", "tasks", "bin")
CI = os.environ.get("CI") == "true"


class HerdrTask(unittest.TestCase):
    def test_compiles(self):
        files = [os.path.join(BIN, "herdr-task")] + [os.path.join(BIN, "herdr_task", f) for f in sorted(os.listdir(os.path.join(BIN, "herdr_task"))) if f.endswith(".py")]
        files += [os.path.join(ROOT, "mods", "artifacts", "bin", "herdr-artifact"), os.path.join(ROOT, "bin", "herdr-secret"),
                  os.path.join(ROOT, "bin", "sync-shared"), os.path.join(ROOT, "bin", "shepherdr")]
        for f in files:
            with open(f, "rb") as fh:
                compile(fh.read(), f, "exec")

    def test_addon_off(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"everywhere": {"off": ["browser"]}}, f)
        code = ("import sys; sys.dont_write_bytecode = True; sys.path.insert(0, sys.argv[1]);"
                "from herdr_task.base import addon_off; print(addon_off('browser'), addon_off('voice'))")
        env = {**os.environ, "HERDR_TASK_SETTINGS": f.name}
        out = subprocess.run([sys.executable, "-c", code, BIN], capture_output=True, text=True, env=env)
        os.unlink(f.name)
        self.assertEqual(out.stdout.split(), ["True", "False"], out.stderr)

    @unittest.skipUnless(CI, "runs only on CI: herdr-task never runs with a changed HOME on a person's machine")
    def test_commands_start(self):
        home = tempfile.mkdtemp()
        env = {**os.environ, "HOME": home, "HERDR_TASK_STORE": os.path.join(home, "tasks")}
        for args in (["--help"], ["--version"], ["list", "--help"], ["machines", "sync", "--help"]):
            p = subprocess.run([sys.executable, os.path.join(BIN, "herdr-task"), *args], capture_output=True, text=True, env=env)
            self.assertEqual(p.returncode, 0, f"herdr-task {' '.join(args)}: {p.stderr}")


class Autopilot(unittest.TestCase):
    """Autopilot's Everywhere and each space's own (herdr_task/autopilot.py), in a throwaway store,
    heartbeat folder and settings file: herdr-app and hc are never run (the window's spaces are given)."""

    def setUp(self):
        import contextlib
        import io
        from unittest import mock
        sys.path.insert(0, BIN)
        import herdr_task.autopilot as ap
        self.ap, self.io, self.redirect = ap, io, contextlib.redirect_stdout
        self.tmp = tempfile.mkdtemp()
        self.folder = os.path.join(self.tmp, "tt-repo")
        os.makedirs(self.folder)
        store = os.path.join(self.tmp, "tasks")

        def never(*a, **k):
            raise AssertionError("ran a program")
        import herdr_task.settings as settings
        self.settings_file = os.path.join(self.tmp, "shepherdr.json")
        p = mock.patch.object(settings, "SETTINGS", self.settings_file)
        p.start()
        self.addCleanup(p.stop)
        for name, value in (("STORE", store), ("STATE", os.path.join(store, ".autopilot.json")),
                            ("HEARTBEATS", os.path.join(self.tmp, "beats")), ("run", never), ("hc_json", never),
                            ("space_info", lambda s: ("~", self.folder) if s == "sp1" else (None, None)),
                            ("window_spaces", lambda: None), ("ensure_scheduler", self.scheduler)):
            p = mock.patch.object(ap, name, value)
            p.start()
            self.addCleanup(p.stop)

    def scheduler(self, quiet=False):
        self.schedulers = getattr(self, "schedulers", 0) + 1
        return {}

    def cmd(self, sub, **kw):
        import argparse
        args = argparse.Namespace(autopilot=sub, json=True, space=None, everywhere=False, every=None, on=None, heartbeat=None,
                                  name=None, space_folder=None, here=False)
        for k, v in kw.items():
            setattr(args, k, v)
        out = self.io.StringIO()
        with self.redirect(out):
            self.ap.cmd_autopilot(args)
        return json.loads(out.getvalue())

    def test_the_rule_is_cores(self):
        """The cases core/autopilot.test.js checks pilotFor() on."""
        with open(os.path.join(ROOT, "core", "autopilot.cases.json")) as f:
            cases = json.load(f)["cases"]
        for c in cases:
            eff = self.ap.resolve(c["file"], c["file"]["spaces"].get(c["space"]), c["space"], c.get("settings", {}))
            got = {"on": eff["on"], "every": (eff["every"] or {}).get("text"), "events": eff["events"], "own": eff["own"]}
            self.assertEqual(got, c["expect"], c["name"])

    def test_a_spaces_old_settings_go(self):
        """Version 1's per-space schedule and events (and a switch on Everywhere) go on the next
        read; a space keeps its on/off and how its wakes went."""
        os.makedirs(self.ap.STORE)
        with open(self.ap.STATE, "w") as f:
            json.dump({"version": 1, "everywhere": {"on": True}, "spaces": {
                "on1": {"on": True, "every": self.ap.parse_every("every 30 minutes"), "events": ["ready"], "next_run": 5},
                "off1": {"on": False, "every": self.ap.parse_every("weekdays 9:00"), "events": []}}}, f)
        with self.ap.state():
            pass
        with open(self.ap.STATE) as f:
            d = json.load(f)
        self.assertEqual(d["version"], 2)
        self.assertNotIn("on", d["everywhere"])
        self.assertEqual(d["spaces"]["on1"]["on"], True)
        for a in d["spaces"].values():
            self.assertFalse({"every", "events"} & set(a))
        on1 = next(v for v in self.cmd("list")["spaces"] if v["space"] == "on1")
        self.assertEqual((on1["on"], on1["every"], on1["events"]), (True, "every 60 minutes", []))

    def test_everywhere_unless_a_space_sets_its_own(self):
        e = self.cmd("set", everywhere=True, every="every 30 minutes", on="ready")
        self.assertEqual((e["everywhere"], e["every"], e["events"]), (True, "every 30 minutes", ["ready"]))
        # kept in Shepherdr settings, with everything else there
        with open(self.settings_file) as f:
            self.assertEqual(json.load(f)["everywhere"]["autopilot"], {"every": "every 30 minutes", "events": ["ready"]})
        v = self.cmd("show", space="sp1")
        self.assertEqual((v["on"], v["every"], v["events"], v["own"]), (False, "every 30 minutes", ["ready"], []))
        # switched on in its header: Everywhere's schedule, a next wake
        v = self.cmd("on", space="sp1")
        self.assertEqual((v["on"], v["every"], v["heartbeat"]), (True, "every 30 minutes", self.ap.heartbeat_path()))
        self.assertTrue(v["next_run"])
        self.assertTrue(os.path.exists(self.ap.heartbeat_path()))
        # Everywhere's schedule changes reach it
        v0 = v["next_run"]
        self.cmd("set", everywhere=True, every="weekdays 9:00")
        v = self.cmd("show", space="sp1")
        self.assertEqual(v["every"], "weekdays 9:00")
        self.assertNotEqual(v["next_run"], v0)
        # its own schedule wins there (and gets its own next wake); its events still follow Everywhere's
        v = self.cmd("set", space="sp1", every="every 2 hours")
        self.assertEqual((v["every"], v["events"], v["own"]), ("every 2 hours", ["ready"], ["every"]))
        self.assertEqual(self.cmd("show", space="sp2")["every"], "weekdays 9:00")
        self.cmd("set", everywhere=True, every="every 60 minutes")
        self.assertEqual(self.cmd("show", space="sp1")["every"], "every 2 hours")
        # "default": back to Everywhere's
        v = self.cmd("set", space="sp1", every="default")
        self.assertEqual((v["every"], v["own"]), ("every 60 minutes", []))
        with open(self.settings_file) as f:
            self.assertNotIn("sp1", json.load(f).get("spaces", {}))
        # a schedule that isn't one is refused, and one written by hand is passed over
        with self.assertRaises(self.ap.Fail):
            self.cmd("set", space="sp1", every="whenever")
        self.assertEqual(self.ap.resolve({}, {}, "sp1", {"spaces": {"sp1": {"autopilot": {"every": "whenever"}}}})["every"]["text"], "every 60 minutes")
        # Everywhere can't switch spaces on or off
        for sub in ("on", "off", "run-now"):
            with self.assertRaises(self.ap.Fail):
                self.cmd(sub, everywhere=True)
        v = self.cmd("off", space="sp1")
        self.assertEqual((v["on"], v["next_run"]), (False, None))
        self.assertEqual([x["space"] for x in self.cmd("list")["spaces"]], ["sp1"])

    def test_heartbeats(self):
        """Everywhere's file from before, until Settings has one; a space's own wins there."""
        v = self.cmd("heartbeat")
        self.assertEqual((v["heartbeat"], v["heartbeat_from"], v["blank"]), (self.ap.heartbeat_path(), "file", False))
        with open(v["heartbeat"]) as f:
            self.assertEqual(f.read(), self.ap.STARTER)
        # the starter is a real heartbeat: a wake brings it as it is
        self.assertIn("Direction: keep this space's tasks moving", self.ap.message("sp1", {}, ["run now"]))
        with open(v["heartbeat"], "w") as f:
            f.write("Ship the docs.\n")
        self.assertIn("Ship the docs.", self.ap.message("sp1", {}, ["run now"]))
        self.cmd("set", everywhere=True, heartbeat="Keep the tests green.")
        self.cmd("set", space="sp1", heartbeat="Only the web app.")
        one, two = self.ap.message("sp1", {}, ["run now"]), self.ap.message("sp2", {}, ["run now"])
        self.assertIn("Only the web app.", one)
        self.assertIn("this space's own", one)
        self.assertIn("Keep the tests green.", two)
        self.assertNotIn("Ship the docs.", two)
        self.assertEqual(self.cmd("heartbeat", space="sp1")["heartbeat_from"], "space")
        self.assertEqual(self.cmd("show", space="sp1")["own"], ["heartbeat"])

    def test_old_starter_gets_the_new_one(self):
        """An earlier version's starter, never edited, stands for today's: the file is rewritten,
        Settings' words are read as it; an edited one is kept, an empty one stays blank."""
        path = self.ap.heartbeat_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        old = self.ap.OLD_STARTERS[0]
        with open(path, "w") as f:
            f.write(old)
        self.cmd("list")
        with open(path) as f:
            self.assertEqual(f.read(), self.ap.STARTER)
        with open(path, "w") as f:
            f.write("  " + old.strip() + "\n\n")
        self.assertIn("Direction: keep this space's tasks moving", self.ap.message("sp1", {}, ["run now"]))
        # edited, even a little: kept as the person wrote it
        edited = old.replace("Priorities:\n-", "Priorities:\n- the docs")
        with open(path, "w") as f:
            f.write(edited)
        self.cmd("heartbeat")
        self.cmd("list")
        with open(path) as f:
            self.assertEqual(f.read(), edited)
        # in Settings, Everywhere's or a space's own: read as today's
        self.cmd("set", space="sp1", heartbeat=old)
        v = self.cmd("show", space="sp1")
        self.assertEqual((v["heartbeat_text"], v["blank"]), (self.ap.STARTER, False))
        self.assertIn("Direction: keep this space's tasks moving", self.ap.message("sp1", {}, ["run now"]))
        # empty: no heartbeat, and a wake says so
        self.cmd("set", space="sp1", heartbeat="")
        self.assertTrue(self.cmd("show", space="sp1")["blank"])
        self.assertIn("not written yet", self.ap.message("sp1", {}, ["run now"]))

    def test_check_and_pushed_copies(self):
        self.assertEqual(self.cmd("check", every="Weekdays 9:00")["every"], "Weekdays 9:00")
        self.assertEqual(self.cmd("check", every="off")["every"], None)
        with self.assertRaises(self.ap.Fail):
            self.cmd("check", every="whenever")
        # a copy the window pushed here: its machine holds the truth
        with open(self.settings_file, "w") as f:
            json.dump({"pushed_from": "herdr-app", "here": "vm"}, f)
        with self.assertRaises(self.ap.Fail):
            self.cmd("set", space="sp1", every="every 2 hours")

    def test_complete_turns_it_off(self):
        import argparse
        self.cmd("on", space="sp1")
        out = self.io.StringIO()
        with self.redirect(out):
            self.ap.cmd_complete(argparse.Namespace(space="sp1", evidence="All docs merged.", json=True))
        v = json.loads(out.getvalue())
        self.assertEqual((v["on"], v["completed"]["text"]), (False, "All docs merged."))

    def test_list_names_a_space_as_the_screens_do(self):
        self.cmd("on", space="sp1")
        args = __import__("argparse").Namespace(autopilot="list", json=False)
        out = self.io.StringIO()
        with self.redirect(out):
            self.ap.cmd_autopilot(args)
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("Everywhere: Every hour"), lines)
        self.assertTrue(lines[1].startswith("tt-repo: Autopilot on"), lines)

    def test_on_starts_this_machines_scheduler(self):
        self.cmd("on", space="sp1")
        self.assertEqual(getattr(self, "schedulers", 0), 1)
        self.cmd("off", space="sp1")
        self.assertEqual(self.schedulers, 1)

    def test_a_folder_told_from_another_machines_window(self):
        # A VM has no window: the machine whose window lists the space says its name and folder.
        v = self.cmd("on", space="sp7", name="exedev", space_folder=self.folder)
        self.assertEqual((v["on"], v["name"], v["folder"]), (True, "exedev", self.folder))

    def remote(self, answers):
        """herdr-task on other machines, as cli.remote_run runs it: answers[machine](argv) -> its JSON out."""
        from unittest import mock
        import subprocess
        import herdr_task.cli as cli
        self.sent = []

        def run(machine, argv, timeout=None):
            self.sent.append((machine, argv))
            out = answers[machine](argv)
            return subprocess.CompletedProcess(argv, 0 if out is not None else 1, json.dumps(out) if out is not None else "", "" if out is not None else "hc: unreachable")
        p = mock.patch.object(cli, "remote_run", run)
        p.start()
        self.addCleanup(p.stop)

    def test_another_machines_space_is_switched_there(self):
        from unittest import mock
        win = [{"id": "sp1", "name": "~", "folder": self.folder},
               {"id": "vm/sp9", "machine": "vm", "name": "exedev", "folder": "/home/exedev"}]
        p = mock.patch.object(self.ap, "window_spaces", lambda: win)
        p.start()
        self.addCleanup(p.stop)
        self.remote({"vm": lambda argv: {"space": "sp9", "on": argv[1] == "on", "name": "exedev", "trigger": "Every hour"}})
        v = self.cmd("on", space="vm/sp9")
        self.assertEqual(self.sent, [("vm", ["autopilot", "on", "--space", "sp9", "--json", "--name", "exedev", "--space-folder", "/home/exedev"])])
        self.assertEqual((v["space"], v["machine"], v["on"]), ("vm/sp9", "vm", True))
        # Nothing here wakes it: no record of it on this machine, and this machine's scheduler isn't asked.
        self.assertFalse(os.path.exists(self.ap.STATE))
        self.assertEqual(getattr(self, "schedulers", 0), 0)
        self.cmd("run-now", space="vm/sp9")
        self.assertEqual(self.sent[-1][1][:4], ["autopilot", "run-now", "--space", "sp9"])

    def test_another_machines_refusal_is_said_here(self):
        self.remote({"vm": lambda argv: {"error": "Autopilot is off in this space: turn it on first."}})
        with self.assertRaises(self.ap.Fail) as e:
            self.cmd("run-now", space="vm/sp9")
        self.assertIn("turn it on first", str(e.exception))
        self.remote({"vm": lambda argv: None})
        with self.assertRaises(self.ap.Fail) as e:
            self.cmd("off", space="vm/sp9")
        self.assertIn("Couldn't reach vm", str(e.exception))

    def test_another_machines_space_is_set_here_by_its_full_id(self):
        self.remote({})
        v = self.cmd("set", space="vm/sp9", every="every 2 hours")
        with open(self.settings_file) as f:
            self.assertEqual(json.load(f)["spaces"]["vm/sp9"]["autopilot"], {"every": "every 2 hours"})
        self.assertEqual((v["space"], v["own"], self.sent), ("vm/sp9", ["every"], []))

    def test_list_holds_every_machines_spaces(self):
        from unittest import mock
        self.cmd("on", space="sp1")
        self.cmd("on", space="spgone")  # a space the window no longer lists
        win = [{"id": "sp1", "name": "~", "folder": self.folder}, {"id": "sp2", "name": "docs", "folder": "/tmp/docs"},
               {"id": "vm/sp9", "machine": "vm", "name": "exedev", "folder": "/home/exedev"},
               {"id": "vm/sp8", "machine": "vm", "name": "~", "folder": "/home/exedev/dev/game"},
               {"id": "mini/sp5", "machine": "mini", "name": "Home", "folder": "/Users/me"}]
        p = mock.patch.object(self.ap, "window_spaces", lambda: win)
        p.start()
        self.addCleanup(p.stop)
        self.remote({"vm": lambda argv: {"everywhere": {"trigger": "Every hour"},
                                         "spaces": [{"space": "sp9", "on": True, "trigger": "Every hour", "next_run": None, "own": []}]},
                     "mini": lambda argv: None})
        out = self.cmd("list")
        self.assertEqual(sorted(m for m, _ in self.sent), ["mini", "vm"])
        self.assertTrue(all(argv == ["autopilot", "list", "--here", "--json"] for _, argv in self.sent))
        got = {v["space"]: v for v in out["spaces"]}
        self.assertEqual(list(got), ["sp1", "sp2", "vm/sp9", "vm/sp8", "mini/sp5"])
        self.assertEqual([got[k]["on"] for k in ("sp1", "sp2", "vm/sp9", "vm/sp8")], [True, False, True, False])
        self.assertTrue(got["mini/sp5"].get("unreachable"))
        lines = [self.ap.line_of(v) for v in out["spaces"]]
        self.assertTrue(lines[2].startswith("exedev on vm: Autopilot on"), lines)
        self.assertTrue(lines[3].startswith("game on vm: Autopilot off"), lines)
        self.assertEqual(lines[4], "Home on mini: can't tell, mini didn't answer")
        # --here: this machine's only, nothing asked elsewhere
        self.sent = []
        self.assertEqual([v["space"] for v in self.cmd("list", here=True)["spaces"]], ["sp1", "sp2"])
        self.assertEqual(self.sent, [])

    def wake(self, ago, turn=3):
        """sp1 on, with a wake delivered to t9 `ago` ms back (its turn then: `turn`)."""
        self.cmd("on", space="sp1")
        with self.ap.state() as d:
            a = d["spaces"]["sp1"]
            a["inflight"] = {"at": self.ap.now() - ago, "reason": "schedule", "to": "t9", "turn": turn}
            self.ap.log_wake(a, "schedule", "Delivered", a["inflight"]["at"])

    def settled(self, k):
        """settle() with the Assistant as `k` (hc get's): the wake left, if its turn ended."""
        from unittest import mock
        k = {"state": "live", "foreground": {"name": "claude"}, **k}
        with mock.patch.object(self.ap, "hc_json", lambda *a: k), self.ap.state() as d:
            self.ap.settle(d["spaces"]["sp1"])
            return d["spaces"]["sp1"]

    def test_a_wake_ends_with_its_turn(self):
        """SHEP-34: the header leaves "Waking" once the wake's turn ends, by its count or, should
        that miss it, the Assistant idle a while; else after the timeout."""
        done = {"turn": 4, "status": {"state": "done"}}
        self.wake(5000)
        self.assertIn("inflight", self.settled({"turn": 4, "status": {"state": "working"}}))
        a = self.settled(done)
        self.assertNotIn("inflight", a)
        self.assertEqual(a["last_wake"]["outcome"], "Turn ended, no progress saved")
        self.assertEqual(self.cmd("show", space="sp1")["inflight"], None)
        # its turn not counted: idle a while after the wake ends it, not at once
        self.wake(5000)
        self.assertIn("inflight", self.settled({"turn": 3, "status": {"state": "idle"}}))
        self.wake(self.ap.IDLE_AFTER_MS + 1000)
        self.assertNotIn("inflight", self.settled({"turn": 3, "status": {"state": "idle"}}))
        # asking the person something: still its wake, until the timeout
        self.wake(self.ap.IDLE_AFTER_MS + 1000)
        self.assertIn("inflight", self.settled({"turn": 3, "status": {"state": "blocked"}}))
        self.wake(self.ap.TURN_MAX_MS + 1000)
        self.assertEqual(self.settled({"turn": 3, "status": {"state": "working"}})["last_wake"]["outcome"],
                         "No turn end seen, no progress saved")
        # its agent quit (a shell left) or its terminal gone
        self.wake(5000)
        self.assertEqual(self.settled({"foreground": {"name": "bash"}, "turn": 3})["last_wake"]["outcome"],
                         "Assistant stopped, no progress saved")

    def test_run_now_goes_after_a_wake_whose_turn_ended(self):
        """A wake the scheduler hasn't closed yet never holds Run now back."""
        from unittest import mock
        self.wake(5000)
        k = {"state": "live", "foreground": {"name": "claude"}, "turn": 4, "status": {"state": "done"}}
        sent = []
        with mock.patch.object(self.ap, "hc_json", lambda *a: k), mock.patch.object(self.ap, "coordinator_in", lambda s: "t9"), \
                mock.patch.object(self.ap, "typing", lambda *a: False), \
                mock.patch.object(self.ap, "news_send", lambda to, m, check=True: sent.append(to) or True):
            v = self.cmd("run-now", space="sp1")
        self.assertEqual(sent, ["t9"])
        self.assertEqual((v["inflight"]["reason"], v["inflight"]["turn"]), ("run now", 4))
        self.assertEqual([w["outcome"] for w in v["wakes"]], ["Turn ended, no progress saved", "Delivered"])


class RemoteInstall(unittest.TestCase):
    """herdr-task --on installs itself on the other machine first, never over a machine that holds its source."""

    def setUp(self):
        from unittest import mock
        import subprocess
        sys.path.insert(0, BIN)
        import herdr_task.cli as cli
        self.cli, self.store, self.ran, self.wrote = cli, tempfile.mkdtemp(), [], []
        self.source = False

        def run(argv, cwd=None, check=False):
            self.ran.append(argv)
            code = 0 if argv[:2] != ["hc", "exec"] or "test" not in argv else (0 if self.source else 1)
            return subprocess.CompletedProcess(argv, code, "{}" if "test" not in argv else "", "")

        def write(argv, **kw):
            self.wrote.append(argv)
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        for name, value in (("run", run), ("STORE", self.store), ("sync_held", lambda: None), ("guard", lambda a: None),
                            ("install_secret", lambda m: None)):
            p = mock.patch.object(cli, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(cli.subprocess, "run", write)
        p.start()
        self.addCleanup(p.stop)

    def test_a_machine_without_the_source_gets_this_copy(self):
        self.cli.remote_run("vm", ["autopilot", "list", "--json"])
        self.assertEqual(self.wrote[0][:5], ["hc", "file", "write", "--on", "vm"])

    def test_a_machine_holding_the_source_is_never_written_to(self):
        self.source = True
        self.cli.remote_run("mini", ["autopilot", "list", "--json"])
        self.cli.remote_run("mini", ["autopilot", "list", "--json"])
        self.assertEqual(self.wrote, [])
        self.assertEqual(sum(1 for a in self.ran if "test" in a), 1)  # asked once, then remembered
        self.assertEqual(self.ran[-1][-3:], ["autopilot", "list", "--json"])


class SchedulerRound(unittest.TestCase):
    """The scheduler's round (automations.one_pass) and the window's or service's tick share one lock,
    both every 15 s. SHEP-34: a round that found the tick holding it skipped, and in step with the
    tick it skipped every time, so no autopilot wake was ever closed (the header stuck on "Waking")."""

    def test_a_round_waits_for_the_tick_and_runs(self):
        import fcntl
        import threading
        from unittest import mock
        sys.path.insert(0, BIN)
        import herdr_task.automations as au
        import herdr_task.autopilot as ap
        import herdr_task.home as home
        store = tempfile.mkdtemp()
        ran = []
        patches = [mock.patch.object(au, "STORE", store), mock.patch.object(au, "SEEN", os.path.join(store, ".seen.json")),
                   mock.patch.object(au, "store_files", lambda *a: []), mock.patch.object(ap, "autopilot_pass", ran.append),
                   mock.patch.object(home, "home_pass", lambda r: None)]
        patches += [mock.patch.object(au, n, lambda *a, **k: None) for n in (
            "retry_pass", "archive_pass", "news_pass", "end_done_pass", "memory_guard", "backup_pass", "cli_check_pass", "machines_pass")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # a tick holds the lock as the round starts, and lets go a moment later
        tick = open(os.path.join(store, ".tick.lock"), "a")
        fcntl.flock(tick, fcntl.LOCK_EX)
        threading.Timer(0.5, lambda: (fcntl.flock(tick, fcntl.LOCK_UN), tick.close())).start()
        au.one_pass({})
        self.assertEqual(len(ran), 1, "the round gave way to the tick and skipped autopilot")
        self.assertTrue(os.path.exists(os.path.join(store, ".seen.json")))
        # a lock held past the wait: this round skips, the scheduler tries again in 15 s
        with open(os.path.join(store, ".tick.lock"), "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            with mock.patch.object(au, "LOCK_WAIT_S", 0.3):
                au.one_pass({})
        self.assertEqual(len(ran), 1)


class BackToWork(unittest.TestCase):
    """A Ready task that goes back to work is Working again (busy_again(), back_to_work()), and
    Accept retries a merge that failed once. In memory: hc, git and gh are never run."""

    def setUp(self):
        from unittest import mock
        sys.path.insert(0, BIN)
        import herdr_task.agents as agents
        import herdr_task.commands as commands
        import herdr_task.news as news
        import herdr_task.tick as tick
        self.agents, self.commands, self.news, self.tick, self.mock = agents, commands, news, tick, mock
        with open(os.path.join(ROOT, "core", "back-to-work.cases.json")) as f:
            self.cases = json.load(f)

        def never(*a, **k):
            raise AssertionError("ran a program")
        self.live = []  # the task's agents now (hc records)
        self.store = Store([])
        for mod, name, value in ((commands, "run", never), (commands, "git", never), (commands, "gh", never),
                                 (commands, "open_store", lambda args, write=True: self.store),
                                 (commands, "view", lambda s, t, live=None: dict(t)), (commands, "say", lambda *a: None),
                                 (commands, "live_agents", lambda key: self.live), (commands, "detail", lambda k: k),
                                 (commands, "refresh_sessions", lambda *a: None),
                                 (tick, "live_agents", lambda key: self.live), (tick, "detail", lambda k: k)):
            p = mock.patch.object(mod, name, value)
            p.start()
            self.addCleanup(p.stop)

    def agent(self, a):
        """A case's agent as hc gives it."""
        return {"address": a["address"], "status": {"state": a["status"]}, "turn": a["turn"], "labels": {"herdr.role": a["role"]}}

    def ready(self, **more):
        t = {"id": 7, "title": "Web client", "state": "ready", "ready_at": 1, "ready_turns": {"t1": 5}, "agents": [], **more}
        self.store.data["tasks"] = [t]
        return t

    def args(self, **kw):
        import argparse
        return argparse.Namespace(id="SHEP-7", json=True, folder=None, **kw)

    def test_the_rule_is_cores(self):
        """The cases core/tasks.test.js checks busyAgain() on."""
        with self.mock.patch.object(self.agents, "now", lambda: self.cases["now"]):
            for c in self.cases["cases"]:
                self.assertEqual(self.agents.busy_again(c["task"], [self.agent(a) for a in c["live"]]), c["expect"], c["name"])

    def test_its_status_is_working_again(self):
        t = self.ready()
        self.assertEqual(self.agents.task_status(t, [self.agent({"address": "t1", "status": "working", "turn": 5, "role": "worker"})]),
                         ("working", None, "Working again"))
        self.assertEqual(self.agents.task_status(t, [self.agent({"address": "t1", "status": "working", "turn": 4, "role": "worker"})])[0], "ready")

    def test_ready_keeps_each_agents_next_turn(self):
        turns = self.agents.ready_turns([{"address": "t1", "status": {"state": "working"}, "turn": 4},
                                         {"address": "t2", "status": "idle", "turn": 2}])
        self.assertEqual(turns, {"t1": 5, "t2": 2})

    def test_fix_takes_it_back_to_work(self):
        t = self.ready(mode="worktree", worktree="/w", branch="b", merge_requested=5)
        self.store.loc["folder"] = "/main"
        with self.mock.patch.object(self.commands, "tell", lambda s, t, msg, args: ("t1", False)):
            self.commands.cmd_fix(self.args(reason="Checks failing: test."))
        self.assertEqual(t["state"], "running")
        self.assertEqual(t["back"]["why"], "asked to fix: Checks failing: test.")
        self.assertEqual(t["progress"]["text"], "Fixing: Checks failing: test.")
        self.assertNotIn("ready_turns", t)
        self.assertNotIn("merge_requested", t)

    def test_resume_takes_it_back_to_work(self):
        t = self.ready(space="sp1")
        with self.mock.patch.object(self.commands, "start_again", lambda *a, **k: ({"address": "t2"}, True)):
            self.commands.cmd_resume(self.args(space=None, agent=None, argv=None, parent=None))
        self.assertEqual((t["state"], t["back"]["why"], t["progress"]["text"]), ("running", "resumed", "Working again"))

    def test_accept_refuses_a_task_back_at_work(self):
        t = self.ready()
        self.live = [self.agent({"address": "t1", "status": "working", "turn": 5, "role": "worker"})]
        with self.assertRaises(self.commands.Fail) as no:
            self.commands.cmd_accept(self.args())
        self.assertIn("is working again", str(no.exception))
        self.assertEqual(t["state"], "running")
        self.assertNotIn("accepted_at", t)

    def test_the_tick_takes_it_back_and_the_news_says_so(self):
        t = self.ready(space="sp1")
        report = {}
        self.tick.back_pass(self.store, t, report)
        self.assertEqual(t["state"], "ready")  # nothing at work
        self.live = [self.agent({"address": "t1", "status": "working", "turn": 5, "role": "worker"})]
        self.tick.back_pass(self.store, t, report)
        self.assertEqual((t["state"], report["working_again"]), ("running", ["SHEP-7"]))
        self.assertEqual(self.news.news_line(self.store, t, {}, "working-again"),
                         '<herdr-news task="SHEP-7" event="working-again">SHEP-7 is working again: its agent is at work again (Web client)</herdr-news>')

    # A merge that failed once (t75: "GraphQL: Something went wrong") never blocks the next Accept, and a pull
    # request merged meanwhile (by hand) makes the task done.
    def merging(self, views, merges):
        """Accept with GitHub giving these pull request views and merge results in turn."""
        views, merges = list(views), list(merges)
        done = []
        patches = [(self.commands, "pr_read", lambda t: (views.pop(0), None)), (self.commands, "pr_view", lambda t: views.pop(0)),
                   (self.commands, "gh", lambda *a, **k: merges.pop(0)),
                   (self.commands, "watch_main", lambda *a: None), (self.commands, "update_main", lambda *a: None),
                   (self.commands, "finish", lambda s, t, even_if_busy=False: (t.update(state="done"), done.append(t["id"])))]
        for mod, name, value in patches:
            p = self.mock.patch.object(mod, name, value)
            p.start()
            self.addCleanup(p.stop)
        return done

    def pr_task(self):
        return self.ready(mode="worktree", worktree="/w", branch="b", pr={"number": 593, "repo": "o/r", "checked": 5})

    def test_accept_tries_a_failed_merge_again(self):
        t = self.pr_task()
        fine = {"state": "OPEN", "mergeable": "MERGEABLE", "statusCheckRollup": [], "headRefOid": "abc"}
        self.merging([fine, fine, fine], [(False, "", "GraphQL: Something went wrong"), (True, "", "")])
        with self.assertRaises(SystemExit):
            self.commands.cmd_accept(self.args())
        self.assertEqual((t["state"], t["attention"]), ("ready", "GitHub didn't merge it: GraphQL: Something went wrong"))
        self.assertEqual(t["pr"]["checked"], 0)  # the next tick reads it at once
        self.commands.cmd_accept(self.args())
        self.assertEqual((t["state"], t.get("merged")), ("done", True))

    def test_accept_finds_it_merged_by_hand(self):
        t = self.pr_task()
        t["attention"] = "GitHub didn't merge it: GraphQL: Something went wrong"
        self.merging([{"state": "MERGED", "mergeCommit": {"oid": "f00"}}], [])
        self.commands.cmd_accept(self.args())
        self.assertEqual((t["state"], t.get("merged")), ("done", True))
        self.assertNotIn("attention", t)

    def test_a_merge_that_errs_but_went_through_is_done(self):
        t = self.pr_task()
        fine = {"state": "OPEN", "mergeable": "MERGEABLE", "statusCheckRollup": [], "headRefOid": "abc"}
        self.merging([fine, {"state": "MERGED", "mergeCommit": {"oid": "f00"}}], [(False, "", "GraphQL: Something went wrong")])
        self.commands.cmd_accept(self.args())
        self.assertEqual((t["state"], t.get("merged")), ("done", True))

    # A pull request its agent opened itself (SHEP-13: "a pull request for branch ... already exists"):
    # ready and Accept adopt it, never fail on it.
    def github_has(self, prs):
        """GitHub with these open pull requests for the branch. Opening another goes as gh's does: only
        one from this repo into the same base stands in the way."""
        import herdr_task.github as github
        calls = []

        def fake(*a, **k):
            calls.append(a[:2])
            if a[:2] == ("pr", "list"):
                return True, json.dumps(prs), ""
            if a[:2] == ("pr", "create"):
                if any(not p["isCrossRepository"] and p["baseRefName"] == "main" for p in prs):
                    return False, "", "a pull request for branch \"b\" into branch \"main\" already exists"
                return True, "https://github.com/o/r/pull/600", ""
            if a[:1] == ("api",):
                return False, "", "gh: Not Found (HTTP 404)"  # the branch isn't on GitHub yet
            return True, "", ""
        for mod, name, value in ((github, "gh", fake), (github, "git", lambda *a: (True, "abc", ""))):
            p = self.mock.patch.object(mod, name, value)
            p.start()
            self.addCleanup(p.stop)
        return github, calls

    def test_ready_adopts_the_open_pull_request(self):
        github, calls = self.github_has([{"number": 599, "url": "https://github.com/o/r/pull/599", "isCrossRepository": False, "baseRefName": "main", "headRefOid": "abc"}])
        t = self.ready(mode="worktree", worktree="/w", branch="b")
        self.assertEqual(github.pr_open(self.store, t, "o/r", "Done.")["number"], 599)
        self.assertEqual(t["pr"], {"number": 599, "url": "https://github.com/o/r/pull/599", "repo": "o/r"})
        self.assertNotIn(("pr", "create"), calls)
        self.assertIn(("pr", "comment"), calls)  # the summary still reaches it

    MINE = {"number": 599, "url": "https://github.com/o/r/pull/599", "isCrossRepository": False, "baseRefName": "main", "headRefOid": "abc"}

    def test_ready_never_adopts_a_forks(self):
        github, calls = self.github_has([{**self.MINE, "isCrossRepository": True}])
        t = self.ready(mode="worktree", worktree="/w", branch="b")
        self.assertEqual(github.pr_open(self.store, t, "o/r")["number"], 600)  # its own, as gh opens it
        self.assertIn(("pr", "create"), calls)

    def test_ready_never_adopts_one_at_another_commit(self):
        github, calls = self.github_has([{**self.MINE, "headRefOid": "f00"}])
        t = self.ready(mode="worktree", worktree="/w", branch="b")
        with self.assertRaises(self.commands.Fail):
            github.pr_open(self.store, t, "o/r")
        self.assertIn(("pr", "create"), calls)
        self.assertNotIn("pr", t)

    def test_ready_never_adopts_or_doubles_one_into_another_base(self):
        github, calls = self.github_has([{**self.MINE, "baseRefName": "dev"}])
        t = self.ready(mode="worktree", worktree="/w", branch="b")
        with self.assertRaises(self.commands.Fail) as no:
            github.pr_open(self.store, t, "o/r")
        self.assertIn("herdr-task adopt SHEP-7 --pr 599", str(no.exception))
        self.assertNotIn(("pr", "create"), calls)
        self.assertNotIn("pr", t)

    def test_ready_opens_one_when_there_is_none(self):
        github, calls = self.github_has([])
        t = self.ready(mode="worktree", worktree="/w", branch="b")
        self.assertEqual(github.pr_open(self.store, t, "o/r")["number"], 600)
        self.assertIn(("pr", "create"), calls)

    def test_accept_adopts_the_open_pull_request(self):
        self.github_has([{"number": 599, "url": "https://github.com/o/r/pull/599", "isCrossRepository": False, "baseRefName": "main", "headRefOid": "abc"}])
        t = self.ready(mode="worktree", worktree="/w", branch="b",
                       attention="Couldn't open a pull request: a pull request for branch \"b\" already exists")
        self.merging([{"state": "MERGED", "mergeCommit": {"oid": "f00"}}], [])
        with self.mock.patch.object(self.commands, "github", lambda s: "o/r"):
            self.commands.cmd_accept(self.args())
        self.assertEqual((t["state"], t["pr"]["number"]), ("done", 599))
        self.assertNotIn("attention", t)

    def test_the_tick_clears_a_failed_merge(self):
        t = self.pr_task()
        t["attention"], t["pr"]["checked"] = "GitHub didn't merge it: GraphQL: Something went wrong", 0
        fine = {"state": "OPEN", "mergeable": "MERGEABLE", "statusCheckRollup": [], "headRefOid": "abc"}
        with self.mock.patch.object(self.tick, "pr_view", lambda t: fine), self.mock.patch.object(self.tick, "pr_news", lambda *a: None):
            self.tick.facts(self.store, t, {"attention": [], "done": []})
        self.assertNotIn("attention", t)  # Ready, its Accept back


class MergedOnlyWithOwnWork(unittest.TestCase):
    """SHEP-23: a task counts as merged only when work of its own landed (its pull request merged, or
    commits made on its branch now in the base), never when its branch just caught up with main, and
    never while its agent is mid-turn. A throwaway git repo; hc and gh are never run."""

    def setUp(self):
        from unittest import mock
        import shutil
        sys.path.insert(0, BIN)
        import herdr_task.commands as commands
        import herdr_task.tick as tick
        self.commands, self.tick = commands, tick
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.main, wt = os.path.join(self.root, "repo"), os.path.join(self.root, "wt")
        self.git(self.root, "init", "-q", "-b", "main", self.main)
        for k, v in (("user.name", "T"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            self.git(self.main, "config", k, v)
        self.commit(self.main, "base")
        self.git(self.main, "worktree", "add", "-q", "-b", "task/1", wt, "HEAD")
        self.live = []  # the task's agents now (hc records)
        self.store = Store([{"id": 1, "title": "Reactions", "state": "running", "mode": "worktree", "worktree": wt,
                             "branch": "task/1", "base": "main", "start": self.git(wt, "rev-parse", "HEAD"), "agents": []}])
        self.store.loc["folder"] = self.main
        self.task = self.store.data["tasks"][0]
        done = lambda s, t, even_if_busy=False: t.update(state="done")
        for mod, name, value in ((tick, "live_agents", lambda key: self.live), (tick, "finish", done),
                                 (tick, "watch_main", lambda *a: None), (commands, "finish", done),
                                 (commands, "open_store", lambda args, write=True: self.store),
                                 (commands, "view", lambda s, t, live=None: dict(t)), (commands, "say", lambda *a: None),
                                 (commands, "live_agents", lambda key: self.live), (commands, "detail", lambda k: k)):
            p = mock.patch.object(mod, name, value)
            p.start()
            self.addCleanup(p.stop)

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, cwd, words):
        self.git(cwd, "commit", "-q", "--allow-empty", "-m", words)
        return self.git(cwd, "rev-parse", "HEAD")

    def tick_once(self):
        self.tick.facts(self.store, self.task, {"attention": [], "done": []})
        return self.task["state"], bool(self.task.get("merged"))

    def working(self):
        self.live = [{"address": "t1", "status": {"state": "working"}}]

    def test_a_fresh_branch_is_not_merged(self):
        self.assertEqual(self.tick_once(), ("running", False))

    def test_a_branch_caught_up_with_main_is_not_merged(self):
        self.commit(self.main, "another task merged")
        self.git(self.task["worktree"], "merge", "-q", "--ff-only", "main")  # SHEP-17's agent
        self.assertEqual(self.tick_once(), ("running", False))
        self.assertNotIn("own", self.task)
        # Accepted so: done, nothing to merge, never "merged".
        self.task["state"] = "ready"
        import argparse
        self.commands.cmd_accept(argparse.Namespace(id="SHEP-1", json=True, folder=None))
        self.assertEqual(self.task["state"], "done")
        self.assertFalse(self.task.get("merged"))

    def test_a_branch_caught_up_with_origin_main_is_not_merged(self):
        self.git(self.main, "update-ref", "refs/remotes/origin/main", self.commit(self.main, "on GitHub"))
        self.git(self.main, "reset", "-q", "--hard", "HEAD~1")  # local main behind its remote
        self.git(self.task["worktree"], "merge", "-q", "--ff-only", "origin/main")
        self.assertEqual(self.tick_once(), ("running", False))
        self.git(self.main, "merge", "-q", "--ff-only", "origin/main")  # main pulled
        self.assertEqual(self.tick_once(), ("running", False))

    def test_its_commits_merged_by_hand_make_it_done(self):
        own = self.commit(self.task["worktree"], "reactions on the left")
        self.assertEqual(self.tick_once(), ("running", False))
        self.assertEqual(self.task["own"], own)
        self.git(self.main, "merge", "-q", "--ff-only", "task/1")
        self.working()
        self.assertEqual(self.tick_once(), ("running", False))  # never under a working agent
        self.live = []
        self.assertEqual(self.tick_once(), ("done", True))

    def test_its_merged_pull_request_makes_it_done(self):
        self.commit(self.task["worktree"], "reactions on the left")
        self.task.update(state="ready", pr={"number": 610, "repo": "o/r", "checked": 0})
        with self.mock_pr({"state": "MERGED", "mergeCommit": {"oid": "f00"}}):
            self.working()
            self.assertEqual(self.tick_once(), ("ready", False))
            self.live, self.task["pr"]["checked"] = [], 0
            self.assertEqual(self.tick_once(), ("done", True))

    def mock_pr(self, v):
        from unittest import mock
        return mock.patch.object(self.tick, "pr_view", lambda t: v)


class TimeLeft(unittest.TestCase):
    """Every status gives the time left, a rough guess beats none (SHEP-13): the minutes show from
    the first one, one without --left asks for it, and every brief and template says so. In memory."""

    def setUp(self):
        from unittest import mock
        sys.path.insert(0, BIN)
        import herdr_task.commands as commands
        self.commands, self.said = commands, []
        self.store = Store([{"id": 7, "title": "Web client", "state": "running", "agents": []}])
        for name, value in (("open_store", lambda args, write=True: self.store), ("view", lambda s, t, live=None: {}),
                            ("live_agents", lambda key: []), ("say", lambda args, data, text: self.said.append(text))):
            p = mock.patch.object(commands, name, value)
            p.start()
            self.addCleanup(p.stop)

    def status(self, left=None, done=None):
        import argparse
        self.commands.cmd_status(argparse.Namespace(id="SHEP-7", json=False, folder=None, text="Starting", done=done, left=left))
        return self.said[-1]

    def test_the_first_status_shows_its_minutes(self):
        from herdr_task.output import report_of
        self.status("20m", 0)
        self.assertEqual(report_of(self.store.find(7), "working")["left"], 20)

    def test_a_status_without_left_asks_for_it(self):
        self.assertIn("Add --left", self.status())
        self.assertNotIn("Add --left", self.status("20m"))

    def test_every_brief_and_template_says_always(self):
        from herdr_task import templates
        launch = open(os.path.join(BIN, "herdr_task", "launch.py")).read()
        for words in (templates.WORKER_MD, open(os.path.join(ROOT, "templates", "worker.md")).read(), launch):
            self.assertNotIn("real estimate", words)
            self.assertIn("rough guess beats none", words)
        self.assertIn(templates.WORKER_MD_BEFORE_LEFT, templates.OLD_WORKERS)  # an unedited old one gets today's


class Store:
    """Enough of herdr_task.store.Store for the commands, in memory."""
    def __init__(self, tasks):
        self.data, self.loc, self.dirty, self.write = {"tasks": tasks}, {"folder": "/f", "kind": "repo", "name": "f"}, False, True
        self.prefix, self.slug = "SHEP", "f"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def find(self, ref):
        return next(t for t in self.data["tasks"] if t["id"] == int(str(ref).split("-")[-1]))

    def ref(self, t):
        return f"SHEP-{t['id']}"

    def key(self, t):
        return f"f#{t['id']}"


if __name__ == "__main__":
    unittest.main()


class Revive(unittest.TestCase):
    """SHEP-30: an Assistant or a task's agent the core gave a plain shell (a crash, a power loss, a
    reboot) gets its agent typed back into that shell, on its own session. A fake core in memory:
    hc and the agents' session files are never touched."""

    def setUp(self):
        from unittest import mock
        sys.path.insert(0, BIN)
        import herdr_task.revive as revive
        self.r, self.mock = revive, mock
        self.dir = tempfile.mkdtemp()
        self.log = os.path.join(self.dir, "S1.jsonl")
        open(self.log, "w").close()
        self.terms = {}
        self.sent, self.screens, self.sessions = [], {}, {}

        def hc(args):
            out, code = "", 0
            if args[:2] == ["hc", "label"]:
                k, v = args[3].split("=", 1)
                self.terms[args[2]].setdefault("labels", {})[k] = v
            elif args[:2] == ["hc", "send"]:
                self.sent.append((args[2], args[3]))
            elif args[:2] == ["hc", "read"]:
                out = self.screens.get(args[2], "")
            else:
                raise AssertionError(f"ran {args}")
            return subprocess.CompletedProcess(args, code, out, "")

        def hc_json(*args):
            if args == ("ls",):
                return {"terminals": [{"address": a, "state": t["state"]} for a, t in self.terms.items()]}
            if args[0] == "get":
                return json.loads(json.dumps(self.terms[args[1]]))
            raise AssertionError(f"hc {args}")
        self.tasks = {"dev#6": {"id": 6, "state": "running", "agents": []}}
        for name, value in (("run", hc), ("hc_json", hc_json), ("session_of", lambda pid: self.sessions.get(pid, (None, None))),
                            ("task_of", lambda k: self.tasks.get((k.get("labels") or {}).get("herdr.task")))):
            p = mock.patch.object(revive, name, value)
            p.start()
            self.addCleanup(p.stop)

    def assistant(self, addr="t1", pid=100, agent_pid=101, status="done"):
        self.terms[addr] = {"address": addr, "state": "live", "pid": pid, "cwd": "/home/me", "template": "assistant",
                            "argv": ["claude", "--model", "opus", "You are the coordinator..."], "status": {"state": status},
                            "foreground": {"pid": agent_pid, "name": "claude", "argv": ["/opt/claude", "--model", "opus", "You are..."], "cwd": "/home/me/app"},
                            "labels": {"herdr.role": "coordinator", "herdr.chat": "p1"}}
        self.sessions[agent_pid] = ("S1", self.log)

    def crash(self, addr, pid=200):
        """What the core does with a kept terminal whose program was lost: a shell, labels kept."""
        t = self.terms[addr]
        t.update(pid=pid, argv=["/bin/bash"], template=None, status=None, foreground={"pid": pid, "name": "bash", "argv": ["/bin/bash"], "cwd": t["cwd"]})

    def tick(self):
        report = {}
        self.r.revive_pass(report)
        return report

    def test_the_assistant_resumes_its_own_session(self):
        self.assistant()
        self.tick()
        rec = json.loads(self.terms["t1"]["labels"]["herdr.resume"])
        self.assertEqual((rec["session"], rec["argv"], rec["pid"], rec["shell"]), ("S1", ["claude", "--model", "opus"], 100, False))
        self.assertEqual(self.sent, [])
        self.crash("t1")
        report = self.tick()
        self.assertEqual(report["revived"], [{"terminal": "t1", "how": "resume", "session": "S1"}])
        self.assertEqual(self.sent, [("t1", "cd /home/me/app && command claude --model opus --resume S1")])
        # Once: the next tick types nothing again, even while the agent starts.
        self.tick()
        self.assertEqual(len(self.sent), 1)

    def test_a_working_agent_carries_on(self):
        self.assistant(status="working")
        self.tick()
        self.crash("t1")
        self.tick()
        self.assertIn("--resume S1 'Herdr restarted", self.sent[0][1])

    def test_an_agent_that_quit_at_its_shell_stays_there(self):
        """The same process (no crash): a person who quit the agent keeps their shell."""
        self.assistant()
        self.tick()
        t = self.terms["t1"]
        t["foreground"] = {"pid": 100, "name": "bash", "argv": ["/bin/bash"]}
        self.tick()
        self.assertEqual(self.sent, [])

    def test_a_gone_session_starts_a_new_assistant_that_says_so(self):
        self.assistant()
        self.tick()
        os.unlink(self.log)
        self.crash("t1")
        with self.mock.patch.object(self.r, "template_of", lambda name="assistant": ("claude", "---\ncommand: claude\n---\nYou are the Assistant.")):
            self.tick()
        line = self.sent[0][1]
        self.assertTrue(line.startswith("cd /home/me/app && command claude --model opus '<restart>Your earlier session is gone"), line)
        self.assertIn("You are the Assistant.", line)
        self.assertNotIn("--resume", line)

    def test_a_resume_the_cli_refuses_starts_anew_once(self):
        self.assistant()
        self.tick()
        self.crash("t1")
        self.tick()
        self.screens["t1"] = "$ claude --resume S1\nNo conversation found with session ID: S1\n$ "
        with self.mock.patch.object(self.r, "template_of", lambda name="assistant": ("claude", None)):
            report = self.tick()
            self.tick()
        self.assertEqual(report["revived"][0]["how"], "fresh")
        self.assertEqual(len(self.sent), 2)
        self.assertIn("<restart>", self.sent[1][1])

    def test_never_a_second_copy_of_a_running_session(self):
        self.assistant()
        self.assistant("t2", pid=300, agent_pid=301)
        self.tick()
        self.crash("t1")
        report = self.tick()
        self.assertEqual(self.sent, [])
        self.assertEqual(report["revived"][0]["how"], "running")

    def test_a_worker_resumes_with_its_task_browser(self):
        self.terms["t5"] = {"address": "t5", "state": "live", "pid": 500, "cwd": "/wt", "name": "shep-6-web",
                            "argv": ["sh", "-c", "low", "herdr-low", "env", "HERDR_BROWSER_TASK=dev#6", "/bin/bash", "-ic", "x", "/bin/bash",
                                     "claude", "--settings", '{"a":1}', "Brief..."],
                            "status": {"state": "working"}, "foreground": {"pid": 501, "name": "claude", "argv": ["claude"], "cwd": "/wt"},
                            "labels": {"herdr.task": "dev#6", "herdr.agent": "claude"}}
        self.sessions[501] = ("S1", self.log)
        self.tick()
        self.crash("t5")
        self.tick()
        self.assertTrue(self.sent[0][1].startswith("""cd /wt && HERDR_BROWSER_TASK='dev#6' claude --settings '{"a":1}' --resume S1 'Herdr restarted"""), self.sent[0][1])

    def test_an_assistant_lost_before_any_record_starts_anew(self):
        """Lost before this change (or before its first record): a new Assistant, never a bare shell."""
        self.assistant()
        self.crash("t1")
        with self.mock.patch.object(self.r, "template_of", lambda name="assistant": ("claude", "---\ncommand: claude\n---\nRole.")):
            self.tick()
            self.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0][1].startswith("cd /home/me && command claude '<restart>"), self.sent[0][1])

    def test_other_terminals_are_left_alone(self):
        self.terms["t9"] = {"address": "t9", "state": "live", "pid": 9, "argv": ["/bin/bash"], "foreground": {"pid": 9, "name": "bash"}, "labels": {}}
        self.tick()
        self.assertEqual((self.sent, self.terms["t9"]["labels"]), ([], {}))

    def test_one_typed_into_a_shell_comes_back_the_same_way(self):
        """An Assistant the person restarted by hand in its shell (claude -c): its process's flags, through the shell again."""
        self.assistant()
        t = self.terms["t1"]
        t.update(argv=["/bin/bash"], foreground={"pid": 101, "name": "claude", "argv": ["/opt/claude", "--dangerously-skip-permissions", "-c"], "cwd": "/home/me"})
        self.tick()
        self.crash("t1")
        self.tick()
        self.assertEqual(self.sent, [("t1", "cd /home/me && claude --dangerously-skip-permissions --resume S1")])

    def test_a_finished_tasks_worker_stays_a_shell(self):
        self.terms["t5"] = {"address": "t5", "state": "live", "pid": 500, "cwd": "/wt", "name": "shep-6-web", "argv": ["claude", "Brief"],
                            "foreground": {"pid": 501, "name": "claude", "argv": ["claude"], "cwd": "/wt"}, "labels": {"herdr.task": "dev#6"}}
        self.sessions[501] = ("S1", self.log)
        self.tick()
        self.tasks["dev#6"]["state"] = "done"
        self.crash("t5")
        self.tick()
        self.assertEqual(self.sent, [])

    def test_a_worker_lost_before_any_record_resumes_its_tasks_session(self):
        self.tasks["dev#6"]["agents"] = [{"address": "t5", "argv": ["claude"], "session": "S1", "log": self.log}]
        self.terms["t5"] = {"address": "t5", "state": "live", "pid": 500, "cwd": "/wt", "name": "shep-6-web", "argv": ["claude"],
                            "labels": {"herdr.task": "dev#6"}}
        self.crash("t5")
        with self.mock.patch("herdr_task.launch.own_argv", lambda argv: argv):
            self.tick()
        self.assertTrue(self.sent[0][1].startswith("cd /wt && HERDR_BROWSER_TASK='dev#6' claude --resume S1 'Herdr restarted"), self.sent)


# ---- PR adoption, base safety and cleanup, across herdr-task's own command line ---------------
# These reuse test_native_publication.py's Fixture: a throwaway repo, a bare remote reached through
# url.insteadOf, a stand-in hc first on PATH and a recording stand-in gh behind HERDR_TASK_GH. No real
# gh, merge, agent or model. Like those, they run on CI only.

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_native_publication as publication  # noqa: E402

ONLY_A_COMMIT = "only a commit, not a branch"
NOT_VERIFIED = "isn't what adoption verified"


def branch_here(f, branch="task/1"):
    return subprocess.run(["git", "-C", f.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                          capture_output=True, text=True, env=f.env).returncode == 0


def rebased(f):
    """The task's work rewritten on its start (as a rebase onto a base that hasn't moved): a new head."""
    f.git(f.wt, "commit", "-q", "--amend", "--allow-empty", "-m", "the task's work, rewritten")
    return f.git(f.wt, "rev-parse", "HEAD")


def merge_head(call):
    return call[call.index("--match-head-commit") + 1]


@publication.ON_CI
class AdoptedHead(unittest.TestCase):
    """D1: Accept merges only the head adopt verified and recorded. ready never records it; running
    adopt again re-verifies a branch that moved and records its new head."""

    def setUp(self):
        self.f = f = publication.Fixture(self)
        f.github(prs=[f.pr()])
        f.adopt()

    def test_adoption_records_the_head_it_verified(self):
        self.assertEqual(self.f.task()["pr"].get("adopted_head"), self.f.tip)

    def test_a_head_rebased_since_is_refused_naming_both(self):
        f = self.f
        h2 = rebased(f)
        f.github(prs=[f.pr(headRefOid=h2)])  # GitHub follows ready's push
        f.ready()
        self.assertEqual(f.task()["pr"].get("adopted_head"), f.tip)  # ready never records it
        error = f.refused("accept", "1", "--folder", f.repo)
        for words in (f.tip[:7], h2[:7], NOT_VERIFIED, "herdr-task adopt"):
            self.assertIn(words, error)
        self.assertEqual((f.calls("pr", "merge"), f.task()["state"]), ([], "ready"))
        self.assertNotIn("accepted_at", f.task())

    def test_an_unmoved_head_merges_what_was_adopted(self):
        f = self.f
        f.ready()
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        self.assertEqual([merge_head(c) for c in f.calls("pr", "merge")], [f.tip])
        self.assertIn("accepted_at", f.task())

    def test_adopting_again_records_the_new_head_and_accept_merges_it(self):
        f = self.f
        h2 = rebased(f)
        f.github(prs=[f.pr(headRefOid=h2)])
        self.assertTrue(f.adopt()["adopted"])
        self.assertEqual(f.task()["pr"]["adopted_head"], h2)
        f.ready()
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        self.assertEqual([merge_head(c) for c in f.calls("pr", "merge")], [h2])

    def test_an_adoption_with_no_recorded_head_is_refused_until_adopted_again(self):
        f = self.f
        f.edit(lambda d: d["tasks"][0]["pr"].pop("adopted_head", None))
        f.ready()
        error = f.refused("accept", "1", "--folder", f.repo)
        self.assertIn("herdr-task adopt", error)
        self.assertEqual(f.calls("pr", "merge"), [])
        self.assertTrue(f.adopt()["adopted"])
        self.assertEqual(f.task()["pr"]["adopted_head"], f.tip)
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")


@publication.ON_CI
class BaseIsABranch(unittest.TestCase):
    """D2: adopt and a merge refuse a base that is only a commit here; the base is fetched as a branch."""

    def test_adopt_refuses_a_base_that_is_only_a_commit(self):
        """adopt already refused this before (with other words); the merges below carry the claim."""
        f = publication.Fixture(self)
        f.github(prs=[f.pr()])
        f.seed(base=f.start)
        before = f.saved()
        self.assertIn(ONLY_A_COMMIT, f.refused("adopt", "1", "--folder", f.repo, "--pr", "7"))
        self.assertEqual(f.saved(), before)

    def test_accept_and_merge_refuse_a_base_that_is_only_a_commit(self):
        f = publication.Fixture(self, github=False)
        f.seed(base=f.start)
        f.ready()
        for verb in ("accept", "merge"):
            with self.subTest(verb=verb):
                self.assertIn(ONLY_A_COMMIT, f.refused(verb, "1", "--folder", f.repo))
                self.assertEqual((f.task()["state"], f.rev("main")), ("ready", f.start))
                self.assertFalse(branch_here(f, f.start))
                self.assertEqual(f.hc("send", "run"), [])

    def test_a_branch_base_merges_as_before(self):
        publication.Fixture(self, github=False).merges_here()

    def test_a_tag_named_like_the_base_doesnt_win_the_fetch(self):
        """The base checked out here (main), so it catches up from its remote's copy alone: a fetch that
        reads the remote's tag "main" first leaves that copy where it was, and main with it."""
        f = publication.Fixture(self)
        f.seed(state="ready", ready_at=1, base="main", pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})
        moved = f.sibling("another task merged")
        f.publish(moved, "main")
        f.git(f.repo, "update-ref", "refs/remotes/origin/main", f.start)  # this clone hasn't seen it yet
        f.git(f.bare, "tag", "main", f.first)  # the tag and the branch at different commits
        f.github(prs=[f.pr(baseRefName="main", state="MERGED", mergeCommit={"oid": moved})])
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        self.assertEqual((f.rev("refs/remotes/origin/main"), f.rev("refs/heads/main")), (moved, moved))


# A stand-in gh route that answers as the recording one does, but can't answer a pull request's view
# after the first: the tick reads it, and finishing it asks again.
ONE_VIEW_GH = '''#!/usr/bin/env python3
import os, sys
count = os.environ["FAKE_GH_STATE"] + ".views"
if sys.argv[1:3] == ["pr", "view"]:
    n = int(open(count).read()) if os.path.exists(count) else 0
    open(count, "w").write(str(n + 1))
    if n:
        print("error connecting to api.github.com", file=sys.stderr)
        sys.exit(1)
os.execv(sys.executable, [sys.executable, os.environ["REAL_GH_ROUTE"]] + sys.argv[1:])
'''

# hc with one live, idle worker for the task, which takes what's sent to it.
WORKER_HC = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_HC_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
k = {"address": "t5", "state": "live", "agent": "claude", "foreground": {"name": "claude"}, "status": {"state": "idle"},
     "labels": {"herdr.role": "worker"}}
if sys.argv[1:2] == ["ls"]:
    print(json.dumps({"terminals": [k]}))
elif sys.argv[1:2] == ["get"]:
    print(json.dumps(k))
elif sys.argv[1:2] != ["send"]:
    sys.exit(1)
'''


@publication.ON_CI
class Cleanup(unittest.TestCase):
    """D3: a finished task's branch goes only when its tip is what merged, and its worktree only when
    nothing in it is uncommitted; otherwise both stay, with a note on the done task."""

    def gone(self, f):
        self.assertEqual((os.path.isdir(f.wt), branch_here(f)), (False, False))
        self.assertNotIn("kept", f.task())

    def kept(self, f, *words):
        t = f.task()
        self.assertEqual((os.path.isdir(f.wt), branch_here(f), t["state"]), (True, True, "done"))
        self.assertNotIn("attention", t)
        for w in words:
            self.assertIn(w, t.get("kept") or "")

    def recorded(self, **pr):
        """A Ready task with the pull request ready opened for it, into target."""
        f = publication.Fixture(self)
        f.seed(state="ready", ready_at=1, base="target", pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})
        f.github(prs=[f.pr(**pr)])
        return f

    def test_a_squash_merge_at_the_branch_tip_removes_both(self):
        f = self.recorded()
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        self.assertEqual(f.task()["merged_head"], f.tip)
        self.gone(f)

    def test_a_commit_past_what_merged_keeps_both(self):
        f = self.recorded()
        extra = f.commit(f.wt, "one more, after the pull request's head")
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        self.assertEqual([merge_head(c) for c in f.calls("pr", "merge")], [f.tip])
        self.kept(f, extra[:7], f.tip[:7])

    def test_uncommitted_work_keeps_the_worktree_and_branch(self):
        for name, change in (("untracked", lambda f: open(os.path.join(f.wt, "notes.txt"), "w").close()),
                             ("tracked", lambda f: (open(os.path.join(f.wt, "a.txt"), "w").close(), f.git(f.wt, "add", "a.txt")))):
            with self.subTest(change=name):
                f = self.recorded()
                change(f)
                f.ok("accept", "1", "--folder", f.repo)
                self.kept(f, "uncommitted")

    def test_an_ignored_file_doesnt_keep_it(self):
        f = self.recorded()
        with open(os.path.join(f.repo, ".git", "info", "exclude"), "a") as x:
            x.write("build.log\n")
        open(os.path.join(f.wt, "build.log"), "w").close()
        f.ok("accept", "1", "--folder", f.repo)
        self.gone(f)

    def test_the_tick_removes_one_merged_by_hand_at_its_tip(self):
        f = self.recorded(state="MERGED", mergeCommit={"oid": "e" * 40})
        self.assertEqual(f.ok("tick", "--folder", f.repo)["done"], [1])
        self.assertEqual(f.task()["merged_head"], f.tip)
        self.gone(f)

    def test_the_tick_keeps_both_when_gh_cant_say_what_merged(self):
        f = self.recorded(state="MERGED", mergeCommit={"oid": "e" * 40})
        f.env["REAL_GH_ROUTE"] = f.gh_route
        f.env["HERDR_TASK_GH"] = f.program(os.path.join(f.tmp, "bin", "gh-one-view"), ONE_VIEW_GH)
        self.assertEqual(f.ok("tick", "--folder", f.repo)["done"], [1])
        self.kept(f, "didn't confirm")

    def test_the_tick_keeps_both_when_the_merged_head_is_unknown(self):
        f = self.recorded(state="MERGED", headRefOid=None, mergeCommit={"oid": "e" * 40})
        self.assertEqual(f.ok("tick", "--folder", f.repo)["done"], [1])
        self.kept(f, "didn't confirm")

    # No pull request: the branch tip is what merged when it is in the task's base branch.
    def nothing_of_its_own(self):
        f = publication.Fixture(self, github=False)
        f.git(f.wt, "checkout", "-q", "-B", "task/1", f.start)
        return f

    def test_accept_with_nothing_of_its_own_removes_both(self):
        f = self.nothing_of_its_own()
        f.seed(state="ready", ready_at=1)
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "done")
        self.gone(f)

    def test_ready_with_nothing_to_merge_removes_both(self):
        f = self.nothing_of_its_own()
        f.ready()
        self.assertEqual((f.task()["state"], f.task().get("nothing_to_merge")), ("done", True))
        self.gone(f)

    def test_the_tick_removes_work_merged_here(self):
        f = publication.Fixture(self, github=False)
        f.ok("tick", "--folder", f.repo)  # sees the task's own commit
        f.git(f.repo, "merge", "-q", "--ff-only", "task/1")
        self.assertEqual(f.ok("tick", "--folder", f.repo)["done"], [1])
        self.gone(f)

    def test_an_unmerged_commit_never_reaches_finishing_on_those_paths(self):
        """A guard of the calling paths: the tick and ready never finish a task holding unmerged work."""
        f = publication.Fixture(self, github=False)
        f.ok("tick", "--folder", f.repo)
        f.git(f.repo, "merge", "-q", "--ff-only", "task/1")
        f.commit(f.wt, "more work, not merged")
        self.assertEqual(f.ok("tick", "--folder", f.repo)["done"], [])
        f.ready()
        self.assertEqual(f.task()["state"], "ready")
        self.assertEqual((os.path.isdir(f.wt), branch_here(f)), (True, True))

    def test_a_tag_named_like_the_base_never_counts_as_merged(self):
        """A guard of the calling paths: the tick and ready read the base as a branch, never its tag."""
        f = publication.Fixture(self, github=False)
        f.git(f.repo, "tag", "main", f.tip)  # a tag would say the work is in "main"; the branch says it isn't
        for _ in range(2):
            self.assertEqual(f.ok("tick", "--folder", f.repo)["done"], [])
        f.ready()
        self.assertEqual(f.task()["state"], "ready")
        self.assertEqual((os.path.isdir(f.wt), branch_here(f)), (True, True))


@publication.ON_CI
class ASavedNoIsAskedAgain(unittest.TestCase):
    """D6: a local merge that rests on gh's saved no asks gh once more first."""

    def setUp(self):
        self.f = f = publication.Fixture(self, github=False)
        f.git(f.repo, "remote", "add", "origin", publication.ENTERPRISE)
        f.github(prs=[], fail=publication.NOT_GITHUB)
        f.ready()
        self.assertEqual((json.loads(f.saved())["github"]["repo"], len(f.calls("repo", "view"))), (None, 1))

    def refused(self, words):
        f = self.f
        self.assertIn(words, f.refused("accept", "1", "--folder", f.repo))
        self.assertEqual((f.task()["state"], f.rev("main")), ("ready", f.start))
        self.assertNotIn("accepted_at", f.task())

    def test_github_now_means_no_local_merge(self):
        self.f.github(prs=[])
        self.refused("no pull request recorded")
        self.assertEqual(len(self.f.calls("repo", "view")), 2)

    def test_gh_failing_now_refuses(self):
        self.f.github(prs=[], fail=publication.AUTH)
        self.refused("gh couldn't")

    def test_a_gh_that_cant_run_refuses(self):
        f = self.f
        f.env["HERDR_TASK_GH"] = f.program(os.path.join(f.tmp, "bin", "gh-broken"), "not a program\n", mode=0o644)
        self.refused("gh couldn't")


@publication.ON_CI
class AcceptedMeansAccepted(unittest.TestCase):
    """accepted_at is the person's Accept reaching an outcome, never a refusal."""

    def recorded(self, **pr):
        f = publication.Fixture(self)
        f.seed(state="ready", ready_at=1, base="target", pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})
        f.github(prs=[f.pr(**pr)])
        return f

    def test_a_checks_wait(self):
        f = self.recorded(statusCheckRollup=[{"name": "ci", "status": "IN_PROGRESS"}])
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "checks")
        self.assertIn("accepted_at", f.task())

    def test_a_merge_asked_of_its_agent(self):
        f = publication.Fixture(self, github=False)
        f.commit(f.repo, "main moved on")  # no fast-forward: the agent merges it
        f.ready()
        f.program(os.path.join(f.tmp, "bin", "hc"), WORKER_HC)
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "agent")
        self.assertTrue(f.hc("send"))
        self.assertIn("accepted_at", f.task())

    def test_a_merge_github_refused(self):
        f = self.recorded()
        f.github(prs=[f.pr()], merge="GraphQL: Something went wrong")
        f.refused("accept", "1", "--folder", f.repo)
        self.assertNotIn("accepted_at", f.task())

    def test_a_pull_request_gh_cant_reach(self):
        f = self.recorded()
        f.github(prs=[f.pr()], fail=publication.AUTH)
        f.refused("accept", "1", "--folder", f.repo)
        self.assertNotIn("accepted_at", f.task())


@publication.ON_CI
class AnImplicitBase(unittest.TestCase):
    """D4: a task with no base key is checked against main, the base it has always merged into."""

    def setUp(self):
        self.f = f = publication.Fixture(self)
        f.github(prs=[f.pr()])
        f.edit(lambda d: [d["tasks"][0].pop(k, None) for k in ("base", "base_set")])

    def test_main_held_by_the_target_is_adopted(self):
        f = self.f
        self.assertTrue(f.adopt()["adopted"])
        self.assertEqual((f.task()["base"], f.task()["adopted_from"]["base"]), ("target", "main"))

    def test_main_gone_its_own_way_is_refused(self):
        f = self.f
        f.publish(f.sibling("main went its own way"), "main")
        before = f.saved()
        self.assertIn("isn't in target", f.refused("adopt", "1", "--folder", f.repo, "--pr", "7"))
        self.assertEqual(f.saved(), before)


@publication.ON_CI
class CycleTwo(unittest.TestCase):
    """PR 19's second repair round, across the command line as above."""

    def recorded(self, **pr):
        """A Ready task with the pull request ready opened for it, into target."""
        f = publication.Fixture(self)
        f.seed(state="ready", ready_at=1, base="target", pr={"number": 7, "url": "https://github.com/o/r/pull/7", "repo": "o/r"})
        f.github(prs=[f.pr(**pr)])
        return f

    def kept(self, f, *words):
        t = f.task()
        self.assertEqual((os.path.isdir(f.wt), branch_here(f), t["state"]), (True, True, "done"))
        for w in words:
            self.assertIn(w, t.get("kept") or "")
        return t["kept"]

    def ahead(self, f, words):
        """A commit on top of the task's tip, here but on no branch: GitHub's "Update branch", say."""
        return f.git(f.repo, "commit-tree", f"{f.tip}^{{tree}}", "-p", f.tip, "-m", words)

    # 1: a branch behind what merged holds nothing unmerged; both stay, and the note doesn't say it does.
    def test_a_branch_behind_what_merged_keeps_both_and_says_so_plainly(self):
        f = self.recorded()
        updated = self.ahead(f, "Update branch")
        f.github(prs=[f.pr(headRefOid=updated)])
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        note = self.kept(f, f"task/1 is at {f.tip[:7]} here and what merged was {updated[:7]}", "nothing was removed")
        self.assertNotIn("didn't merge", note)

    # 3: a merge that erred and went through records the head gh says merged, not the one asked for.
    def test_a_merge_that_erred_but_went_through_records_its_head(self):
        f = self.recorded()
        updated = self.ahead(f, "a suggestion committed on GitHub")
        f.github(prs=[f.pr()], merge="GraphQL: Something went wrong",
                 merge_moves={"state": "MERGED", "headRefOid": updated, "mergeCommit": {"oid": "e" * 40}})
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        self.assertEqual(f.task()["merged_head"], updated)
        self.kept(f, updated[:7])

    # 5: the no-PR keep path: a task with nothing of its own whose start isn't in its base any more.
    def test_a_tip_that_isnt_in_the_base_keeps_both(self):
        for verb in ("accept", "ready"):
            with self.subTest(verb=verb):
                f = publication.Fixture(self, github=False)
                f.git(f.wt, "checkout", "-q", "-B", "task/1", f.start)  # nothing of its own
                rewritten = f.git(f.repo, "commit-tree", "HEAD^{tree}", "-p", f.first, "-m", "main rewritten without the start")
                f.git(f.repo, "checkout", "-q", "-B", "main", rewritten)
                if verb == "accept":
                    f.seed(state="ready", ready_at=1)
                    self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "done")
                else:
                    f.ready()
                self.kept(f, f"task/1 at {f.start[:7]} isn't in main")

    # 6: the saved no is asked again through merge and ready's auto-merge too.
    def saved_no(self):
        f = publication.Fixture(self, github=False)
        f.git(f.repo, "remote", "add", "origin", publication.ENTERPRISE)
        f.github(prs=[], fail=publication.NOT_GITHUB)
        f.ready()
        f.github(prs=[])  # gh now places it on GitHub
        return f

    def saved_no_on_a_reachable_remote(self):
        """saved_no(), with the remote reaching the bare repo (url.insteadOf), so publishing pushes nowhere real."""
        f = publication.Fixture(self)
        f.git(f.repo, "remote", "set-url", "origin", publication.ENTERPRISE)
        f.git(f.repo, "config", "--add", f"url.{f.bare}.insteadOf", publication.ENTERPRISE)
        f.github(prs=[], fail=publication.NOT_GITHUB)
        f.ready()
        self.assertEqual((f.task()["state"], json.loads(f.saved())["github"]["repo"]), ("ready", None))
        f.seed(state="running")
        f.github(prs=[])  # gh now places it on GitHub
        return f

    # CodeRabbit 9Z8c: Ready asks a saved no again too, and publishes: a refusal saves nothing, so
    # trusting the saved no would leave the task with no pull request for up to an hour.
    def test_ready_asks_a_saved_no_again_and_opens_the_pull_request(self):
        f = self.saved_no_on_a_reachable_remote()
        f.ready()
        t = f.task()
        self.assertEqual((t["state"], (t.get("pr") or {}).get("number")), ("ready", 9))
        self.assertEqual((len(f.calls("pr", "create")), len(f.calls("repo", "view"))), (1, 2))
        self.assertEqual((f.remote_tip("task/1"), f.rev("main"), f.hc("send", "run")), (f.tip, f.start, []))
        self.assertEqual(json.loads(f.saved())["github"]["repo"], "o/r")

    def test_merge_asks_a_saved_no_again(self):
        f = self.saved_no()
        self.assertIn("no pull request recorded", f.refused("merge", "1", "--folder", f.repo))
        self.assertEqual((len(f.calls("repo", "view")), f.hc("send", "run"), f.rev("main")), (2, [], f.start))
        self.assertNotIn("merge_requested", f.task())

    def test_readys_auto_merge_asks_a_saved_no_again(self):
        """Ready asks again before it publishes (9Z8c), so under auto it opens the pull request and merges
        through it, never here and never through its agent."""
        f = self.saved_no_on_a_reachable_remote()
        f.seed(set={"merge": "auto"})
        f.ready()
        t = f.task()
        self.assertEqual(((t.get("pr") or {}).get("number"), len(f.calls("repo", "view"))), (9, 2))
        self.assertEqual((f.hc("send", "run"), f.rev("main")), ([], f.start))
        self.assertNotIn("merge_requested", t)

    # 2: no base recorded, adopted into main: its base is written as at eaa90190, with no adopted_from.
    def test_adopted_into_main_with_no_base_recorded_writes_it(self):
        f = publication.Fixture(self)
        f.github(prs=[f.pr(baseRefName="main")])
        f.edit(lambda d: [d["tasks"][0].pop(k, None) for k in ("base", "base_set")])
        p = f.run("adopt", "1", "--folder", f.repo, "--pr", "7")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("its base stays main", p.stdout)
        t = f.task()
        self.assertEqual((t["base"], t["base_set"], t["base_by"]), ("main", True, "pull-request"))
        self.assertNotIn("adopted_from", t)

    # 9: what was kept is said in Accept's, merge's and show's own words, not only in --json.
    def test_what_was_kept_is_said(self):
        for verb in ("accept", "merge"):
            with self.subTest(verb=verb):
                f = self.recorded()
                f.commit(f.wt, "one more, after the pull request's head")
                p = f.run(verb, "1", "--folder", f.repo)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertIn("Kept task/1 and its worktree", p.stdout)
                self.assertIn("kept: Kept task/1 and its worktree", f.run("show", "1", "--folder", f.repo).stdout)

    # 10: one side moved is said as one side.
    def test_only_the_branch_here_moving_is_said_so(self):
        f = publication.Fixture(self)
        f.github(prs=[f.pr()])
        f.adopt()
        f.ready()
        moved = f.commit(f.wt, "one more fix")
        error = f.refused("accept", "1", "--folder", f.repo)
        for words in (NOT_VERIFIED, f"#7 is still at {f.tip[:7]}, but task/1 is at {moved[:7]} here", "herdr-task adopt"):
            self.assertIn(words, error)
        self.assertNotIn("Bring both back", error)

    # 12: a branch that's gone: the worktree alone is kept, and said so.
    def test_a_branch_thats_gone_keeps_the_worktree_and_says_that(self):
        f = self.recorded()
        f.git(f.repo, "update-ref", "-d", "refs/heads/task/1")
        self.assertEqual(f.ok("accept", "1", "--folder", f.repo)["accepted"], "github")
        t = f.task()
        self.assertEqual((t["state"], os.path.isdir(f.wt)), ("done", True))
        self.assertTrue(t["kept"].startswith(f"Kept the worktree {f.wt}: its branch task/1 isn't here"), t["kept"])
