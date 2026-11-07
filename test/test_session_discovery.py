"""session_of(), called as its callers do, against real processes in throwaway folders: an agent's
session and log are read under that agent's own Claude Code folder. Each agent here is a python
that waits: on macOS a system binary's environment reads as empty, so it wouldn't do. session_of()
runs in a process of its own, as HOME is read once at import. Linux runs these on CI; on macOS they
take the other reader, and CI never does."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "mods", "tasks", "bin")
SESSION = "aaaaaaaa-0000-4000-8000-000000000001"
OTHER = "bbbbbbbb-0000-4000-8000-000000000002"
WAIT = 'print("ready", flush=True); import time; time.sleep(120)'
# Linux: a process that isn't dumpable keeps /proc/<pid>/environ from its own user too.
SEALED = "import ctypes; ctypes.CDLL(None).prctl(4, 0, 0, 0, 0); " + WAIT
# A wrapper that has no session of its own: its child has, under the folder given, and prints its pid.
WRAPPER = """
import os, subprocess, sys, time
c = subprocess.Popen([sys.executable, "-c", sys.argv[1]], env={**os.environ, "CLAUDE_CONFIG_DIR": sys.argv[2]}, stdout=subprocess.PIPE)
c.stdout.readline()
print(c.pid, flush=True)
time.sleep(120)
"""
CALL = ("import json, sys; sys.dont_write_bytecode = True; sys.path.insert(0, sys.argv[1]);"
        "from herdr_task.sessions import session_of; print(json.dumps(session_of(int(sys.argv[2]))))")
CAN_SEAL = sys.platform.startswith("linux") and os.geteuid() != 0


class SessionOf(unittest.TestCase):
    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.fallback = os.path.join(self.home, ".claude")

    def folder(self, name="profile"):
        return os.path.join(self.home, name)

    def environment(self, env):
        return {"PATH": os.environ.get("PATH", ""), "HOME": self.home, **env}

    def agent(self, env=None, code=WAIT, args=()):
        """A real process with exactly this environment, once it has started: (pid, its first line)."""
        p = subprocess.Popen([sys.executable, "-c", code, *args], env=self.environment(env or {}), stdout=subprocess.PIPE, text=True)
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        self.addCleanup(p.stdout.close)
        return p.pid, p.stdout.readline().strip()

    def session(self, folder, pid, sid=SESSION, log=True, owner=None):
        """What Claude Code leaves for a process: its metadata, and its log unless log is False."""
        os.makedirs(os.path.join(folder, "sessions"), exist_ok=True)
        with open(os.path.join(folder, "sessions", f"{pid}.json"), "w") as f:
            json.dump({"pid": pid if owner is None else owner, "sessionId": sid, "cwd": "/work", "kind": "interactive"}, f)
        path = os.path.join(folder, "projects", "-work", sid + ".jsonl")
        if log:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("{}\n")
        return path

    def found(self, pid, env=None):
        r = subprocess.run([sys.executable, "-c", CALL, BIN, str(pid)], env=self.environment(env or {}),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return tuple(json.loads(r.stdout))

    def test_no_variable_finds_it_under_the_default_folder(self):
        pid, _ = self.agent()
        log = self.session(self.fallback, pid)
        self.assertEqual(self.found(pid), (SESSION, log))

    def test_the_variable_set_finds_it_under_exactly_that_folder(self):
        folder = self.folder()
        pid, _ = self.agent({"CLAUDE_CONFIG_DIR": folder})
        log = self.session(folder, pid)
        self.assertEqual(self.found(pid), (SESSION, log))

    def test_a_folder_with_spaces_is_read_whole(self):
        folder = self.folder(os.path.join("Application Support", "a profile"))
        pid, _ = self.agent({"CLAUDE_CONFIG_DIR": folder})
        log = self.session(folder, pid)
        self.assertEqual(self.found(pid), (SESSION, log))

    def test_two_agents_at_once_each_find_only_their_own(self):
        one, two = self.folder("one"), self.folder("two")
        a, _ = self.agent({"CLAUDE_CONFIG_DIR": one})
        b, _ = self.agent({"CLAUDE_CONFIG_DIR": two})
        log_a, log_b = self.session(one, a, SESSION), self.session(two, b, OTHER)
        # Each folder also names the other's process, as a scan across folders would trip on.
        self.session(one, b, SESSION)
        self.session(two, a, OTHER)
        self.assertEqual(self.found(a), (SESSION, log_a))
        self.assertEqual(self.found(b), (OTHER, log_b))

    def test_no_metadata_finds_nothing(self):
        folder = self.folder()
        pid, _ = self.agent({"CLAUDE_CONFIG_DIR": folder})
        self.session(folder, pid + 1)
        self.assertEqual(self.found(pid), (None, None))

    def test_metadata_for_another_pid_finds_nothing(self):
        pid, _ = self.agent()
        self.session(self.fallback, pid, owner=pid + 1)
        self.assertEqual(self.found(pid), (None, None))

    def test_metadata_with_no_pid_finds_nothing(self):
        pid, _ = self.agent()
        os.makedirs(os.path.join(self.fallback, "sessions"))
        with open(os.path.join(self.fallback, "sessions", f"{pid}.json"), "w") as f:
            json.dump({"sessionId": SESSION}, f)
        self.assertEqual(self.found(pid), (None, None))

    def test_a_session_with_no_log_yet_has_no_log_in_either_folder(self):
        folder = self.folder()
        plain, _ = self.agent()
        custom, _ = self.agent({"CLAUDE_CONFIG_DIR": folder})
        self.session(self.fallback, plain, log=False)
        self.session(folder, custom, log=False)
        self.assertEqual(self.found(plain), (SESSION, None))
        self.assertEqual(self.found(custom), (SESSION, None))

    @unittest.skipUnless(CAN_SEAL or sys.platform == "darwin", "needs a process this user can't read")
    def test_an_environment_that_cant_be_read_finds_nothing_never_the_default_folder(self):
        """Linux: a process that seals itself (root reads it anyway). macOS: a system binary, whose
        environment shows empty."""
        if CAN_SEAL:
            pid, _ = self.agent(code=SEALED)
        else:
            p = subprocess.Popen(["/bin/sleep", "120"], env=self.environment({}))
            self.addCleanup(p.wait)
            self.addCleanup(p.kill)
            pid = p.pid
        self.session(self.fallback, pid)
        self.assertEqual(self.found(pid), (None, None))

    def test_a_folder_that_holds_nothing_never_falls_back_to_the_default(self):
        pid, _ = self.agent({"CLAUDE_CONFIG_DIR": self.folder()})
        self.session(self.fallback, pid)
        self.assertEqual(self.found(pid), (None, None))

    def test_a_log_only_another_folder_holds_isnt_taken(self):
        folder = self.folder()
        pid, _ = self.agent({"CLAUDE_CONFIG_DIR": folder})
        self.session(folder, pid, log=False)
        self.session(self.fallback, pid)
        self.assertEqual(self.found(pid), (SESSION, None))

    def test_the_callers_own_variable_says_nothing_about_the_agent(self):
        folder = self.folder()
        pid, _ = self.agent()
        log = self.session(self.fallback, pid)
        self.session(folder, pid, OTHER)
        self.assertEqual(self.found(pid, {"CLAUDE_CONFIG_DIR": folder}), (SESSION, log))

    def test_each_candidate_is_read_for_itself(self):
        folder = self.folder()
        pid, line = self.agent(code=WRAPPER, args=(WAIT, folder))
        child = int(line)
        self.addCleanup(os.kill, child, 9)
        log = self.session(folder, child)
        self.assertEqual(self.found(pid), (SESSION, log))

    def test_a_value_that_isnt_an_exact_absolute_path_finds_nothing(self):
        for value in ("", "relative/folder", self.folder() + "\nmore"):
            with self.subTest(value=value):
                pid, _ = self.agent({"CLAUDE_CONFIG_DIR": value})
                self.session(self.fallback, pid)
                self.assertEqual(self.found(pid), (None, None))

    def test_only_the_variable_itself_counts(self):
        decoy = "CLAUDE_CONFIG_DIR=" + self.folder()
        pid, _ = self.agent({"NOTES": "x\n" + decoy, "ALSO": decoy}, args=(decoy,))
        log = self.session(self.fallback, pid)
        self.assertEqual(self.found(pid), (SESSION, log))


if __name__ == "__main__":
    unittest.main()
