"""Provider bindings and launch plans (herdr_task/providers.py), across herdr-task's own command
line: Personal starts as it always did, an Azure binding is refused before anything is started or
changed (by start, resume, switch, the tick's queue and an automation), `provider plan` shows the
official plan for each supported sign-in, and no credential's value is ever read or written.

The command-line tests run on CI only, as herdr-task's others: HOME stays the account's own, the
task lists, settings and templates are throwaway ones (herdr-task's own overrides), and `hc` is a
recording stand-in first on PATH, so no agent, terminal or model request exists. They prove what
herdr-task does with a binding; they don't prove Azure sign-in, inference or a real launch."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "mods", "tasks", "bin")
CI = os.environ.get("CI") == "true"
ON_CI = unittest.skipUnless(CI, "runs only on CI: herdr-task's commands never run from a test on a person's machine")

# Stand-ins for the host's credentials: present in every command's environment, expected nowhere.
SECRETS = {"ANTHROPIC_FOUNDRY_API_KEY": "marker-foundry-key-7f3a", "ANTHROPIC_FOUNDRY_AUTH_TOKEN": "marker-foundry-token-91bc",
           "AZURE_OPENAI_API_KEY": "marker-azure-openai-key-52de", "ANTHROPIC_API_KEY": "marker-anthropic-key-0c4e",
           "OPENAI_API_KEY": "marker-openai-key-aa17"}
# hc's verbs that start, stop or change something: a refused launch runs none of them.
EFFECTS = {"run", "exec", "send", "kill", "rm", "label", "put", "keys", "interrupt", "file", "machine", "restart"}

FAKE_HC = '''#!/usr/bin/env python3
import json, os, sys
log = os.environ["FAKE_HC_LOG"]
try:
    with open(log) as f:
        n = sum(1 for _ in f)
except OSError:
    n = 0
with open(log, "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
verb = sys.argv[1] if len(sys.argv) > 1 else ""
if verb == "run":
    print(json.dumps({"address": "t%d" % (n + 1)}))
elif verb == "ls":
    print(json.dumps({"terminals": []}))
else:
    sys.exit(1)
'''

CLAUDE = {"claude_resource": "example", "claude_deployment": "claude-deployment"}
CODEX = {"codex_endpoint": "https://example.openai.azure.com/openai/v1", "codex_deployment": "code-deployment"}
# sha256 of the 2.x planner's JSON.stringify([kind, endpoint, deployment, method words]), computed apart from this code.
FP = {"entra-id": "b4ff5e524c831cf3eb23385562a1e07606b2f98a18ab17b71030acd4286ad75e",
      "api-key": "d7393ef87da0113071eb5338ece39195610cf841cd6b6351151e0366c881b49a",
      "bearer-token": "ac9a02f2e525b63cb6119359c4c065981f15a9b17383a990cfecfb3d5c80493e",
      "codex": "44e019ec9ff5b99ccb91a33d83e95ec6c5d75bfd66c5d3b91e6bd7bb6fe9169b",
      "space": "05c67c012ea6fc16ea0739ba8dbffac40c853fd73df3a2ac9acfc646e756536c"}
PENDING = ["launch admission", "bound resume", "settings and selectors", "native qualification"]
# Settings' start limits off: the runner's own load, memory or disk never decides what a tick starts.
ROOM = {"machine": {"start_load": None, "start_memory": None, "start_disk": None}}
INLINE = "marker-inline-credential-3b9d"
# A key pasted into settings as a field's name, not its value.
PASTED = "sk-marker-pasted-as-a-field-name-4e7a"
UNKNOWN = "a field it doesn't know"


def claude_env(deployment, inherited=None):
    """Claude Code's --settings env on Foundry, written out: the route's own values, "" for every
    competing route and inactive credential, and the active credential's variable left out."""
    env = {"CLAUDE_CODE_USE_FOUNDRY": "1", "CLAUDE_CODE_USE_BEDROCK": "", "CLAUDE_CODE_USE_VERTEX": "", "CLAUDE_CODE_USE_MANTLE": "",
           "CLAUDE_CODE_USE_ANTHROPIC_AWS": "", "CLAUDE_CODE_SKIP_FOUNDRY_AUTH": "", "ANTHROPIC_BASE_URL": "", "ANTHROPIC_API_KEY": "",
           "ANTHROPIC_AUTH_TOKEN": "", "ANTHROPIC_FOUNDRY_API_KEY": "", "ANTHROPIC_FOUNDRY_AUTH_TOKEN": "",
           "ANTHROPIC_FOUNDRY_RESOURCE": "example", "ANTHROPIC_FOUNDRY_BASE_URL": "", "ANTHROPIC_DEFAULT_OPUS_MODEL": deployment,
           "ANTHROPIC_DEFAULT_SONNET_MODEL": deployment, "ANTHROPIC_DEFAULT_HAIKU_MODEL": deployment, "ANTHROPIC_MODEL": "",
           "ANTHROPIC_SMALL_FAST_MODEL": ""}
    if inherited:
        del env[inherited]
    return env


class Fixture:
    """A throwaway git repo, task store, settings file and templates folder, and a recording hc."""

    def __init__(self, test):
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
        self.log = os.path.join(self.tmp, "hc.log")
        self.settings = os.path.join(self.tmp, "shepherdr.json")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_", "ANTHROPIC_", "CLAUDE_", "AZURE_", "OPENAI_"))}
        self.env.update(SECRETS, PATH=fake + os.pathsep + os.environ.get("PATH", ""), SHELL="/bin/sh", FAKE_HC_LOG=self.log,
                        HERDR_TASK_STORE=os.path.join(self.tmp, "tasks"), HERDR_TASK_SETTINGS=self.settings,
                        HERDR_TASK_TEMPLATES=os.path.join(self.tmp, "templates"))
        self.seen = ""

    def run(self, *args):
        p = subprocess.run([sys.executable, os.path.join(BIN, "herdr-task"), *args], capture_output=True, text=True, env=self.env, timeout=120)
        self.seen += p.stdout + p.stderr
        return p

    def ok(self, *args):
        p = self.run(*args, "--json")
        self.test.assertEqual(p.returncode, 0, f"herdr-task {' '.join(args)}: {p.stdout}{p.stderr}")
        return json.loads(p.stdout)

    def refused(self, *args):
        """A refusal as --json gives it: exit 1, the reason on stdout, nothing on stderr."""
        p = self.run(*args, "--json")
        self.test.assertEqual((p.returncode, p.stderr), (1, ""), p.stdout)
        return json.loads(p.stdout)["error"]

    def provider(self, everywhere=None, space=None, also=None, **top):
        """Writes the settings file: Everywhere's and the space's "provider" sections, `also` beside
        Everywhere's (its other settings), `top` at the file's top."""
        d = {"version": 1, **top}
        if everywhere is not None:
            d["everywhere"] = {"provider": everywhere, **(also or {})}
        if space is not None:
            d["spaces"] = {"sp1": {"folder": self.repo, "provider": space}}
        with open(self.settings, "w") as f:
            json.dump(d, f)

    def plan(self, *args):
        return self.ok("provider", "plan", "--folder", self.repo, "--space", "sp1", *args)

    def no_plan(self, *args):
        return self.refused("provider", "plan", "--folder", self.repo, "--space", "sp1", *args)

    def add(self, *extra):
        return self.ok("add", "Fix login", "--folder", self.repo, "--space", "sp1", *extra)["id"]

    def calls(self):
        try:
            with open(self.log) as f:
                return [json.loads(line) for line in f]
        except OSError:
            return []

    def launches(self):
        """The agents hc was asked to start (the scheduler's own terminal isn't one)."""
        return [c for c in self.calls() if c[:1] == ["run"] and any(a.startswith("herdr.task=") for a in c)]

    def store_text(self):
        with open(self.ok("where", "--folder", self.repo)["store"]) as f:
            return f.read()

    def task(self, tid=1):
        return next(t for t in json.loads(self.store_text())["tasks"] if t["id"] == tid)

    def worktrees(self):
        out = subprocess.run(["git", "-C", self.repo, "worktree", "list", "--porcelain"], check=True, capture_output=True, text=True).stdout
        return [line for line in out.splitlines() if line.startswith("worktree ")]

    def branches(self):
        return subprocess.run(["git", "-C", self.repo, "branch", "--format=%(refname:short)"], check=True, capture_output=True, text=True).stdout.split()

    def settle(self, agents=1, tid=1):
        """Waits for the background watcher of each started agent to finish its one write."""
        for _ in range(200):
            if sum(1 for a in self.task(tid)["agents"] if a.get("ended")) >= agents:
                return
            time.sleep(0.1)
        self.test.fail("the agent watcher didn't finish")

    def snapshot(self):
        """The task list's words and how many hc calls there were, before a command that must refuse."""
        return self.store_text(), len(self.calls())

    def nothing_started(self, before):
        """After a refusal: the task list is as it was, no worktree or branch was made, and since
        the snapshot hc was asked for nothing that starts, stops or changes anything."""
        text, calls = before
        self.test.assertEqual(self.store_text(), text)
        self.test.assertEqual(self.worktrees(), [f"worktree {self.repo}"])
        self.test.assertEqual(self.branches(), ["main"])
        self.test.assertEqual([c for c in self.calls()[calls:] if c and c[0] in EFFECTS], [])

    def no_secret(self):
        """No credential's value in anything herdr-task said, kept or handed to hc."""
        texts = [self.seen, json.dumps(self.calls())]
        if os.path.exists(self.settings):
            with open(self.settings) as f:
                texts.append(f.read())
        store = self.env["HERDR_TASK_STORE"]
        for d, _, files in os.walk(store) if os.path.isdir(store) else []:
            for name in files:
                with open(os.path.join(d, name), errors="replace") as f:
                    texts.append(f.read())
        for name, value in SECRETS.items():
            for text in texts:
                self.test.assertNotIn(value, text, name)


@ON_CI
class PersonalPassThrough(unittest.TestCase):
    """Personal is the default and changes nothing about a launch."""

    def started_plainly(self, f):
        """The one agent hc was asked for is the CLI as Settings starts it: the task's browser variable
        only, the person's shell, claude with its own --settings, and nothing of a provider's."""
        run = f.launches()
        self.assertEqual(len(run), 1, f.calls())
        words = run[0]
        at = words.index("herdr-low")
        self.assertEqual(words[at + 1:at + 7], ["env", "HERDR_BROWSER_TASK=" + words[words.index("--label") + 1].split("=", 1)[1],
                                               "/bin/sh", words[at + 4], '"$@"; exec "$0" -i', "/bin/sh"])
        self.assertIn(words[at + 4], ("-ic", "-lic"))
        agent = words[at + 7:]
        self.assertEqual(agent[:2], ["claude", "--settings"])
        settings = json.loads(agent[2])
        self.assertEqual((settings["fastMode"], sorted(settings)), (False, ["fastMode", "permissions"]))
        self.assertEqual(len(agent), 4)  # and its brief
        for word in ("--model", "-c"):
            self.assertNotIn(word, agent[:3])
        for mark in ("FOUNDRY", "model_provider", "openai.azure.com", "claude-deployment", "OPENAI_"):
            self.assertNotIn(mark, json.dumps(words))

    def test_no_provider_setting_starts_the_cli_as_before(self):
        f = Fixture(self)
        tid = f.add("--here")
        out = f.ok("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now")
        self.assertEqual(out["state"], "running")
        self.assertRegex(out["terminal"], r"^t\d+$")
        self.started_plainly(f)
        self.assertEqual([a["argv"] for a in f.task()["agents"]], [["claude", "--settings", '{"fastMode": false}']])
        f.settle()
        self.assertEqual(f.plan("--agent", "claude"), {
            "route": "personal", "agent": "claude", "fingerprint": "personal", "deployment": None, "auth": None, "credential": None,
            "settings_env": {}, "args": [], "env": {}, "argv": ["claude"], "dispatch": "pass-through", "pending": []})
        f.no_secret()

    def test_personal_with_a_half_filled_azure_setup_is_still_untouched(self):
        f = Fixture(self)
        f.provider({"route": "personal", **CLAUDE, "claude_auth": "api-key", "codex_endpoint": "not yet", "azure_subscription": ""})
        tid = f.add("--here")
        f.ok("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now")
        self.started_plainly(f)
        f.settle()
        self.assertEqual(f.plan("--agent", "codex")["argv"], ["codex", "--no-daemon"])
        f.no_secret()

    def test_a_space_set_to_personal_wins_over_everywheres_azure(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE}, space={"route": "personal"})
        self.assertEqual(f.plan("--agent", "claude")["route"], "personal")
        tid = f.add("--here")
        f.ok("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now")
        self.started_plainly(f)
        f.settle()

    def test_a_provider_section_that_cannot_be_read_refuses_on_personal_too(self):
        # The section's shape is checked on every route: settings are copied between machines, so a
        # key put there is said and never started past. Its value is never repeated.
        for section, words in (({"route": "personal", "api_key": "marker-pasted-key-6d21"}, UNKNOWN),
                               ({"claude_deployment": 7}, "provider claude_deployment isn't text")):
            with self.subTest(section=sorted(section)):
                f = Fixture(self)
                tid = f.add()
                f.provider(section)
                before = f.snapshot()
                self.assertIn(words, f.refused("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now"))
                f.nothing_started(before)
                self.assertNotIn("marker-pasted-key-6d21", f.seen + json.dumps(f.calls()) + f.store_text())
                # Without the section Personal starts again.
                f.provider({"route": "personal"})
                f.ok("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now", "--here")
                f.settle(tid=tid)


@ON_CI
class AzureRefusesBeforeEffects(unittest.TestCase):
    """Under an Azure binding no start, queue or resume happens: unsupported combinations say what
    is wrong, and a valid one is held, each before a worktree, the task list or hc is touched."""

    def refuse_start(self, provider, words, agent=None, **top):
        f = Fixture(self)
        tid = f.add()  # a worktree task: starting it would make a worktree and a branch
        self.assertEqual(f.task(tid)["mode"], "worktree")
        f.provider(provider, **top)
        before = f.snapshot()
        why = f.refused("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now", *(["--agent", agent] if agent else []))
        self.assertIn(words, why)
        f.nothing_started(before)
        self.assertEqual(f.task(tid)["state"], "todo")
        f.no_secret()
        return f, why

    def test_each_supported_sign_in_is_planned_and_held(self):
        for auth in ("entra-id", "api-key", "bearer-token"):
            with self.subTest(auth=auth):
                _, why = self.refuse_start({"route": "azure-foundry", **CLAUDE, "claude_auth": auth}, "this version only plans it")
                self.assertIn("Nothing was started or changed", why)
        self.refuse_start({"route": "azure-foundry", **CODEX, "codex_auth": "api-key"}, "this version only plans it", agent="codex")

    def test_codex_with_entra_id_is_unsupported(self):
        for auth in ("entra-id", "bearer-token"):
            with self.subTest(auth=auth):
                _, why = self.refuse_start({"route": "azure-foundry", **CODEX, "codex_auth": auth}, "API key only", agent="codex")
                self.assertNotIn("only plans it", why)

    def test_an_incomplete_or_unknown_binding_is_refused(self):
        self.refuse_start({"route": "azure-foundry", "claude_resource": "example"}, "explicit Azure deployment name for Claude Code")
        self.refuse_start({"route": "azure-foundry", "claude_deployment": "claude-deployment"}, "Claude Azure resource name")
        self.refuse_start({"route": "azure-foundry", **CLAUDE, "claude_resource": "https://example.services.ai.azure.com/anthropic"}, "not a URL")
        self.refuse_start({"route": "azure-foundry", **CLAUDE, "claude_auth": "managed-identity"}, "Entra ID, an API key or a bearer token")
        self.refuse_start({"route": "azure-foundry", **CODEX, "codex_endpoint": "https://example.openai.azure.us/openai/v1"},
                          "https://RESOURCE.openai.azure.com/openai/v1", agent="codex")
        self.refuse_start({"route": "bedrock"}, "Personal or Azure Foundry")
        self.refuse_start({"route": "azure-foundry", **CLAUDE}, "Claude Code and Codex only", agent="pi")

    def test_a_credential_put_in_settings_is_refused_and_never_repeated(self):
        f, why = self.refuse_start({"route": "azure-foundry", **CLAUDE, "api_key": "marker-pasted-key-6d21"}, UNKNOWN)
        self.assertIn("Keys and tokens never go in settings", why)
        self.assertNotIn("marker-pasted-key-6d21", f.seen + json.dumps(f.calls()) + f.store_text())

    def test_a_secret_pasted_as_a_field_name_is_never_repeated_or_kept(self):
        f = Fixture(self)
        f.provider({"route": "personal"}, also=ROOM)
        first, second = f.add("--here"), f.add("--here", "--after", "1")
        self.assertEqual(f.ok("start", str(second), "--folder", f.repo, "--space", "sp1")["queued"], True)
        f.ok("rm", str(first), "--folder", f.repo)
        auto = f.ok("auto", "add", "Nightly check", "--folder", f.repo, "--space", "sp1", "--on", "merged", "--here")
        f.provider({"route": "azure-foundry", **CLAUDE, PASTED: "1"}, also=ROOM)
        # A start says so, as JSON and as words.
        self.assertIn(UNKNOWN, f.refused("start", str(second), "--folder", f.repo, "--space", "sp1", "--now"))
        p = f.run("start", str(second), "--folder", f.repo, "--space", "sp1", "--now")
        self.assertEqual((p.returncode, p.stdout), (1, ""))
        self.assertIn(UNKNOWN, p.stderr)
        # The tick keeps its reason on the queued task.
        self.assertEqual(f.ok("tick", "--folder", f.repo)["started"], [])
        self.assertIn(UNKNOWN, f.task(second)["attention"])
        # An automation's run keeps it on the automation and on its task.
        out = f.ok("auto", "run-now", str(auto["id"]), "--folder", f.repo)
        self.assertIn(UNKNOWN, out["last_error"]["message"])
        self.assertIn(UNKNOWN, out["runs"][-1]["error"])
        self.assertIn(UNKNOWN, f.task(second + 1)["attention"])
        self.assertEqual(f.launches(), [])
        # Nothing said, kept or handed to hc repeats the field's name.
        for text in (f.seen, json.dumps(f.calls()), f.store_text()):
            self.assertNotIn(PASTED, text)
            self.assertNotIn(PASTED[:16], text)  # nor a shortened one
        f.no_secret()

    def test_a_copy_of_the_settings_on_another_machine_never_starts_azure(self):
        self.refuse_start({"route": "azure-foundry", **CLAUDE}, "this machine's are a copy", pushed_from="herdr-app", here="vm")

    def test_a_task_that_would_queue_is_not_queued(self):
        f = Fixture(self)
        first, second = f.add(), f.add("--after", "1")
        # Personal: it waits its turn behind the first.
        self.assertEqual(f.ok("start", str(second), "--folder", f.repo, "--space", "sp1")["queued"], True)
        f.ok("reopen", str(second), "--folder", f.repo)
        f.provider({"route": "azure-foundry", **CLAUDE})
        before = f.snapshot()
        self.assertIn("only plans it", f.refused("start", str(second), "--folder", f.repo, "--space", "sp1"))
        f.nothing_started(before)
        self.assertEqual((f.task(first)["state"], f.task(second)["state"]), ("todo", "todo"))

    def test_resume_is_refused_and_personal_resumes_again_after(self):
        f = Fixture(self)
        tid = f.add("--here")
        f.ok("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now")
        f.settle()
        f.provider({"route": "azure-foundry", **CLAUDE})
        before, started = f.snapshot(), len(f.launches())
        for verb in ("resume", "switch"):
            with self.subTest(verb=verb):
                self.assertIn("only plans it", f.refused(verb, str(tid), "--folder", f.repo, "--space", "sp1"))
                self.assertEqual((f.store_text(), len(f.launches())), (before[0], started))
                # no terminal was asked for, and the old one wasn't ended
                self.assertEqual([c for c in f.calls()[before[1]:] if c and c[0] in EFFECTS], [])
        # Back on Personal the same conversation's task starts again: the refusal left it whole.
        f.provider({"route": "personal"})
        self.assertRegex(f.ok("resume", str(tid), "--folder", f.repo, "--space", "sp1")["terminal"], r"^t\d+$")
        self.assertEqual(len(f.launches()), started + 1)
        f.settle(2)
        f.no_secret()

    def test_the_tick_does_not_start_a_queued_task_and_personal_starts_it_after(self):
        f = Fixture(self)
        f.provider({"route": "personal"}, also=ROOM)
        first, second = f.add("--here"), f.add("--here", "--after", "1")
        # Personal: it waits its turn behind the first, then nothing holds it.
        self.assertEqual(f.ok("start", str(second), "--folder", f.repo, "--space", "sp1")["queued"], True)
        f.ok("rm", str(first), "--folder", f.repo)
        f.provider({"route": "azure-foundry", **CLAUDE}, also=ROOM)
        report = f.ok("tick", "--folder", f.repo)
        self.assertEqual(report["started"], [])
        task = f.task(second)
        self.assertEqual((task["state"], task["agents"], "queue" in task), ("queued", [], True))
        self.assertTrue(task["attention"].startswith("Couldn't start: Azure Foundry is set for Claude Code"), task["attention"])
        self.assertIn("only plans it", task["attention"])
        self.assertEqual((f.launches(), f.worktrees(), f.branches()), ([], [f"worktree {f.repo}"], ["main"]))
        # Back on Personal the next tick starts it: the refusal left its place in the queue whole.
        f.provider({"route": "personal"}, also=ROOM)
        report = f.ok("tick", "--folder", f.repo)
        self.assertEqual([x["id"] for x in report["started"]], [second])
        self.assertEqual(len(f.launches()), 1)
        task = f.task(second)
        self.assertEqual((task["state"], "attention" in task, "queue" in task), ("running", False, False))
        f.settle(tid=second)
        f.no_secret()

    def test_an_automation_neither_queues_nor_starts_its_task(self):
        f = Fixture(self)
        room = {**ROOM, "tasks": {"max_running": 1}}
        f.provider({"route": "personal"}, also=room)
        busy = f.add("--here")
        f.ok("start", str(busy), "--folder", f.repo, "--space", "sp1", "--now")
        auto = f.ok("auto", "add", "Nightly check", "--folder", f.repo, "--space", "sp1", "--on", "merged", "--here")
        # Personal: with one task at work its task waits its turn, as a start would.
        out = f.ok("auto", "run-now", str(auto["id"]), "--folder", f.repo)
        self.assertEqual(out["runs"][-1].get("queued"), "1 task is running here")
        self.assertEqual(f.task(busy + 1)["state"], "queued")
        f.provider({"route": "azure-foundry", **CLAUDE}, also=room)
        launched = len(f.launches())
        out = f.ok("auto", "run-now", str(auto["id"]), "--folder", f.repo)
        self.assertIn("only plans it", out["last_error"]["message"])
        self.assertEqual((out["last_error"]["kind"], "queued" in out["runs"][-1]), ("start", False))
        self.assertIn("only plans it", out["runs"][-1]["error"])
        # Its task is there for the person, saying why: not queued, not started, no worktree.
        task = f.task(busy + 2)
        self.assertEqual((task["state"], task["agents"], "queue" in task, "queued_at" in task), ("todo", [], False, False))
        self.assertTrue(task["attention"].startswith("Couldn't start: Azure Foundry is set for Claude Code"), task["attention"])
        self.assertEqual((len(f.launches()), f.worktrees(), f.branches()), (launched, [f"worktree {f.repo}"], ["main"]))
        f.settle(tid=busy)
        f.no_secret()


@ON_CI
class LaunchPlans(unittest.TestCase):
    """`provider plan`: each supported route's official plan, by name only, without starting or
    asking for anything."""

    def planned(self, f, *args):
        out = f.plan(*args)
        self.assertEqual(f.calls(), [])  # a plan runs no hc at all
        f.no_secret()
        return out

    def test_claude_on_foundry_by_each_sign_in(self):
        for auth, credential in (("entra-id", None), ("api-key", "ANTHROPIC_FOUNDRY_API_KEY"), ("bearer-token", "ANTHROPIC_FOUNDRY_AUTH_TOKEN")):
            with self.subTest(auth=auth):
                f = Fixture(self)
                f.provider({"route": "azure-foundry", **CLAUDE, "claude_auth": auth, "azure_subscription": "11111111-2222-3333-4444-555555555555"})
                env = claude_env("claude-deployment", credential)
                out = self.planned(f, "--agent", "claude")
                argv = out.pop("argv")
                self.assertEqual(out, {
                    "route": "azure-foundry", "agent": "claude", "fingerprint": FP[auth], "deployment": "claude-deployment", "auth": auth,
                    "credential": credential, "settings_env": env, "args": [], "env": {}, "dispatch": "held", "pending": PENDING})
                self.assertEqual(argv[:2] + argv[3:], ["claude", "--settings", "--model", "claude-deployment"])
                self.assertEqual(json.loads(argv[2]), {"env": env})
                if credential:
                    self.assertNotIn(credential, env)  # inherited from the host, never set or blanked here

    def test_entra_id_is_the_default_sign_in_for_claude(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE})
        out = self.planned(f, "--agent", "claude")
        self.assertEqual((out["auth"], out["credential"], out["fingerprint"]), ("entra-id", None, FP["entra-id"]))

    def test_codex_on_azure_by_api_key(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CODEX})
        ident = "shepherdr_azure_" + FP["codex"]
        args = ["-c", f'model_provider="{ident}"', "-c",
                f'model_providers.{ident}={{name="Azure Foundry",base_url="https://example.openai.azure.com/openai/v1",'
                'env_key="AZURE_OPENAI_API_KEY",wire_api="responses",requires_openai_auth=false}']
        self.assertEqual(self.planned(f, "--agent", "codex"), {
            "route": "azure-foundry", "agent": "codex", "fingerprint": FP["codex"], "deployment": "code-deployment", "auth": "api-key",
            "credential": "AZURE_OPENAI_API_KEY", "settings_env": {}, "args": args, "env": {"OPENAI_BASE_URL": "", "OPENAI_API_KEY": ""},
            "argv": ["codex", *args, "-m", "code-deployment", "--no-daemon"], "dispatch": "held", "pending": PENDING})

    def test_the_agents_own_effort_fast_and_permissions_are_kept(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE, **CODEX})
        ident = "shepherdr_azure_" + FP["codex"]
        base = ["codex", "--no-daemon", "-m", "gpt-5", "-c", 'model_reasoning_effort="high"', "-c", 'service_tier="fast"',
                "--dangerously-bypass-approvals-and-sandbox"]
        out = self.planned(f, "--argv", json.dumps(base))
        self.assertEqual(out["argv"][:2] + out["argv"][5:], ["codex", "-c", "--no-daemon", "-m", "code-deployment", "-c", 'model_reasoning_effort="high"',
                                                             "-c", 'service_tier="fast"', "--dangerously-bypass-approvals-and-sandbox"])
        self.assertEqual(out["argv"][2], f'model_provider="{ident}"')
        base = ["claude", "--model", "opus", "--effort", "high", "--settings", '{"fastMode": true, "env": {"MY_FLAG": "1"}}', "--permission-mode", "plan"]
        out = self.planned(f, "--argv", json.dumps(base))
        self.assertEqual(out["argv"][:6] + out["argv"][7:], ["claude", "--model", "claude-deployment", "--effort", "high", "--settings", "--permission-mode", "plan"])
        self.assertEqual(json.loads(out["argv"][6]), {"fastMode": True, "env": {"MY_FLAG": "1", **claude_env("claude-deployment")}})

    def test_the_argv_selects_the_plans_deployment_and_no_other_model(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE, **CODEX})
        one = ["-m", "code-deployment"]
        # Each argv carries Codex's --no-daemon itself, before any "--": one without it is given it
        # at its end (settings.agent_argv), which these cases don't judge.
        for words, kept in (
                # Codex takes a one-letter flag's value attached, with or without "=".
                (["-mgpt-5", "--no-daemon"], [*one, "--no-daemon"]),
                (["--no-daemon", "-m=gpt-5"], ["--no-daemon", *one]),
                (["--model=gpt-5", "--no-daemon"], ["--model=code-deployment", "--no-daemon"]),
                # A second selection would compete with the plan's: only the first place is kept.
                (["--no-daemon", "-m", "gpt-5", "-m", "o3"], ["--no-daemon", *one]),
                (["--model=gpt-5", "--no-daemon", "--model", "o3"], ["--model=code-deployment", "--no-daemon"]),
                (["--model", "gpt-5", "--no-daemon", "--model=o3", "-mo4", "-m=o5", "-m", "o6"], ["--model", "code-deployment", "--no-daemon"]),
                # Not a selection: a long word or another one-letter flag that only looks like one,
                # and the operands after "--".
                (["--no-daemon", "--max", "-pmine"], [*one, "--no-daemon", "--max", "-pmine"]),
                (["--no-daemon", "--", "-m", "gpt-5"], [*one, "--no-daemon", "--", "-m", "gpt-5"]),
                (["-m", "gpt-5", "--no-daemon", "--", "--model=o3", "-mo4"], [*one, "--no-daemon", "--", "--model=o3", "-mo4"]),
                # A flag with no value of its own (the next word is another option, the "--", or
                # isn't there) takes the deployment, and the next word stays.
                (["-m", "--no-daemon"], [*one, "--no-daemon"]),
                (["--no-daemon", "-m"], ["--no-daemon", *one]),
                (["--no-daemon", "-m", "--", "gpt-5"], ["--no-daemon", *one, "--", "gpt-5"]),
                (["-m", "gpt-5", "-m", "--no-daemon"], [*one, "--no-daemon"]),
                (["-m", "gpt-5", "--no-daemon", "--model"], [*one, "--no-daemon"])):
            with self.subTest(codex=words):
                out = self.planned(f, "--argv", json.dumps(["codex", *words]))
                self.assertEqual(out["argv"], ["codex", *out["args"], *kept])
                self.assertEqual(len(out["args"]), 4)
        for words, kept in (
                (["--model", "opus", "--model", "sonnet"], ["--model", "claude-deployment"]),
                (["--model=opus", "--effort", "high", "--model", "sonnet"], ["--model=claude-deployment", "--effort", "high"]),
                (["--effort", "high", "--model", "opus", "--model=sonnet", "--model=haiku"], ["--effort", "high", "--model", "claude-deployment"]),
                (["--model", "--effort", "high"], ["--model", "claude-deployment", "--effort", "high"]),
                (["--effort", "high", "--model"], ["--effort", "high", "--model", "claude-deployment"])):
            with self.subTest(claude=words):
                argv = self.planned(f, "--argv", json.dumps(["claude", *words]))["argv"]
                self.assertEqual(argv[:2] + argv[3:], ["claude", "--settings", *kept])

    def test_operands_after_a_bare_double_dash_are_planned_and_not_read(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE, **CODEX})
        for operands in (["--oss"], ["--local-provider=ollama"], ["-c", 'model_provider="azure"']):
            with self.subTest(codex=operands):
                out = self.planned(f, "--argv", json.dumps(["codex", "--no-daemon", "--", *operands]))
                self.assertEqual(out["argv"], ["codex", *out["args"], "-m", "code-deployment", "--no-daemon", "--", *operands])
        # Claude Code: a --settings among the operands is not opened, parsed or counted, and the
        # plan's own --settings goes before the "--".
        operands = ["--settings", "/somewhere/settings.json"]
        argv = self.planned(f, "--argv", json.dumps(["claude", "--", *operands]))["argv"]
        self.assertEqual(argv[:2] + argv[3:], ["claude", "--settings", "--model", "claude-deployment", "--", *operands])
        self.assertEqual(json.loads(argv[2]), {"env": claude_env("claude-deployment")})
        operands = ["--settings=/somewhere/settings.json", "--settings", "{}"]
        argv = self.planned(f, "--argv", json.dumps(["claude", "--settings", '{"fastMode": true}', "--", *operands]))["argv"]
        self.assertEqual(argv[:4] + argv[5:], ["claude", "--model", "claude-deployment", "--settings", "--", *operands])
        self.assertEqual(json.loads(argv[4]), {"fastMode": True, "env": claude_env("claude-deployment")})

    def test_an_argv_that_routes_itself_is_refused(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE, **CODEX})
        own = "remove the argv's own provider"
        for argv, words in ((["codex", "-c", 'model_provider="azure"'], own),
                            # Codex trims an override's key, and takes it attached to -c or --config too.
                            (["codex", "-c", ' model_provider = "azure"'], own),
                            (["codex", '-cmodel_provider="azure"'], own),
                            (["codex", '-c=model_provider="azure"'], own),
                            (["codex", '--config=model_provider="azure"'], own),
                            (["codex", "--config", ' model_providers.azure.base_url = "https://other.example/v1"'], own),
                            (["codex", "-c", 'model_providers={azure={name="other"}}'], own),
                            (["codex", "--oss"], own),
                            # Before a bare "--" these are still options.
                            (["codex", "--oss", "--no-daemon", "--", "x"], own),
                            (["codex", "--no-daemon", "-c", 'model_provider="azure"', "--", "x"], own),
                            (["claude", "--settings", "/somewhere/settings.json", "--", "x"], "must be inline JSON, not a file"),
                            (["claude", "--settings=/somewhere/settings.json", "--", "x"], "as a separate JSON word"),
                            (["claude", "--settings", "/somewhere/settings.json"], "must be inline JSON, not a file"),
                            (["claude", "--settings=/somewhere/settings.json"], "as a separate JSON word")):
            with self.subTest(argv=argv):
                self.assertIn(words, f.no_plan("--argv", json.dumps(argv)))
        self.assertEqual(f.calls(), [])

    def test_a_credential_written_into_the_argv_is_refused_by_name(self):
        f = Fixture(self)
        inline = lambda variable: ["claude", "--settings", json.dumps({"env": {variable: INLINE}})]
        for auth, variable in (("api-key", "ANTHROPIC_FOUNDRY_API_KEY"), ("bearer-token", "ANTHROPIC_FOUNDRY_AUTH_TOKEN")):
            with self.subTest(auth=auth):
                f.provider({"route": "azure-foundry", **CLAUDE, "claude_auth": auth})
                self.assertIn(f"{variable} comes from the execution host's environment", f.no_plan("--argv", json.dumps(inline(variable))))
        # The same through a start: refused before the task, a worktree or hc is touched.
        tid = f.add()
        before = f.snapshot()
        why = f.refused("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now", "--argv", json.dumps(inline("ANTHROPIC_FOUNDRY_AUTH_TOKEN")))
        self.assertIn("ANTHROPIC_FOUNDRY_AUTH_TOKEN comes from the execution host's environment", why)
        f.nothing_started(before)
        # A second --settings word could carry one past the first: one word only.
        twice = ["claude", "--settings", "{}", *inline("ANTHROPIC_FOUNDRY_AUTH_TOKEN")[1:]]
        self.assertIn("one --settings word", f.no_plan("--argv", json.dumps(twice)))
        # A credential the plan doesn't use is blanked in the argv, as the inherited one is.
        f.provider({"route": "azure-foundry", **CLAUDE})
        argv = f.plan("--argv", json.dumps(inline("ANTHROPIC_FOUNDRY_API_KEY")))["argv"]
        self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), {"env": claude_env("claude-deployment")})
        self.assertNotIn(INLINE, f.seen + json.dumps(f.calls()) + f.store_text())
        f.no_secret()

    def test_the_most_specific_layer_wins_field_by_field(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE}, space={"claude_deployment": "space-deployment", "claude_auth": "api-key", "claude_resource": None})
        out = self.planned(f, "--agent", "claude")
        self.assertEqual((out["deployment"], out["auth"], out["credential"], out["fingerprint"], out["settings_env"]["ANTHROPIC_FOUNDRY_RESOURCE"]),
                         ("space-deployment", "api-key", "ANTHROPIC_FOUNDRY_API_KEY", FP["space"], "example"))
        # An empty value a space sets is its own value, not Everywhere's again.
        f.provider({"route": "azure-foundry", **CLAUDE}, space={"claude_deployment": ""})
        self.assertIn("explicit Azure deployment name for Claude Code", f.no_plan("--agent", "claude"))

    def test_unsupported_plans_say_why_as_json_and_as_words(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CODEX, "codex_auth": "entra-id"})
        self.assertIn("Microsoft's Codex guide says Entra ID isn't available", f.no_plan("--agent", "codex"))
        p = f.run("provider", "plan", "--folder", f.repo, "--agent", "codex")
        self.assertEqual((p.returncode, p.stdout), (1, ""))
        self.assertTrue(p.stderr.startswith("herdr-task: Codex on Azure signs in with an API key only"), p.stderr)
        self.assertIn("Which CLI?", f.no_plan())
        self.assertEqual(f.calls(), [])
        f.no_secret()

    def test_the_plan_in_words_and_its_help(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE, "claude_auth": "api-key"})
        p = f.run("provider", "plan", "--folder", f.repo, "--agent", "claude")
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        for words in ("claude: Azure Foundry, deployment claude-deployment, API key.", "the ANTHROPIC_FOUNDRY_API_KEY variable on the execution host",
                      "Dispatch is held in this version", "no sign-in, credential or model request was tried"):
            self.assertIn(words, p.stdout)
        p = f.run("provider", "plan", "--help")
        self.assertEqual(p.returncode, 0, p.stderr)
        for words in ("--agent", "--argv", "--space", "--folder", "--json", "Reads no credential, starts nothing, signs in nowhere"):
            self.assertIn(words, " ".join(p.stdout.split()))  # argparse wraps its lines
        self.assertIn("provider", f.run("--help").stdout)
        self.assertEqual(f.calls(), [])
        f.no_secret()


class Binding(unittest.TestCase):
    """The binding's own rules, in the module: the fields both herdr-task and the service's
    discovery judge (test/azure-binding.cases.json), and a backup the provider setting holds.
    The backup tests call takeover() itself, with its launch and hc replaced: reaching it through
    `herdr-task tick` needs a live agent, its session log and a provider cut that the recording
    hc doesn't model, so the tick's own gate is proved above and the backup's stays in-module."""

    def setUp(self):
        from unittest import mock
        sys.path.insert(0, BIN)
        import herdr_task.providers as providers
        import herdr_task.settings as settings
        import herdr_task.takeover as takeover
        self.p, self.takeover, self.mock = providers, takeover, mock
        self.file = os.path.join(tempfile.mkdtemp(), "shepherdr.json")
        p = mock.patch.object(settings, "SETTINGS", self.file)
        p.start()
        self.addCleanup(p.stop)

    def test_the_fields_as_both_sides_judge_them(self):
        with open(os.path.join(ROOT, "test", "azure-binding.cases.json")) as f:
            cases = json.load(f)["cases"]
        self.assertEqual((len(cases), sum(1 for c in cases if c["ok"])), (33, 8))
        for c in cases:
            with self.subTest(field=c["field"], value=c["value"]):
                if c["ok"]:
                    self.assertEqual(self.p.clean(c["field"], c["value"]), c["kept"])
                else:
                    with self.assertRaises(self.p.Fail) as e:
                        self.p.clean(c["field"], c["value"])
                    self.assertNotIn(c["value"].strip(), str(e.exception))

    def backup(self, provider):
        with open(self.file, "w") as f:
            json.dump({"everywhere": {"provider": provider}}, f)
        ran, started = [], []
        store = type("S", (), {"loc": {"folder": "/f"}, "dirty": False})()
        task = {"id": 1, "space": "sp1", "agents": [{"address": "t1", "agent": "claude"}]}
        k = {"address": "t1", "labels": {"herdr.agent": "claude", "herdr.task.space": "sp1"}}
        patches = {"backup_for": lambda s, t, running: ("codex", None), "backup_argv": lambda s, t, kind: ["codex", "--no-daemon"],
                   "parent_for": lambda parent, space: None, "handover": lambda *a: "handover", "brief": lambda *a: "brief",
                   "launch": lambda s, t, argv, space, text, parent=None: started.append(argv) or {"address": "t2"},
                   "run": lambda args, **kw: ran.append(args)}
        for name, value in patches.items():
            p = self.mock.patch.object(self.takeover, name, value)
            p.start()
            self.addCleanup(p.stop)
        row = self.takeover.takeover(store, task, k, {"reason": "Out of allowance until 5pm"}, None, {})
        return row, task, started, ran

    def test_a_backup_starts_on_personal(self):
        row, task, started, ran = self.backup({"route": "personal"})
        self.assertEqual((row, task["backup"]["state"], started, ran), (None, "started", [["codex", "--no-daemon"]], [["hc", "kill", "t1"]]))

    def test_a_backup_the_provider_holds_isnt_spent(self):
        row, task, started, ran = self.backup({"route": "azure-foundry", **CODEX})
        # The refusal's own words follow "backup held", cut to the reason's one line.
        self.assertEqual((row["reason"], "backup" in task, started, ran), ("Out of allowance, backup held: Azure…", False, [], []))


if __name__ == "__main__":
    unittest.main()
