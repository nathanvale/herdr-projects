"""Provider bindings and launch plans (herdr_task/providers.py), across herdr-task's own command
line: Personal starts as it always did; an Azure binding starts a task's agent on its plan and
records its nonsecret binding (start, queue, resume, switch, the tick's queue and an automation);
resuming a recorded conversation keeps that binding when the defaults change and refuses before any
effect when its routing changed; a task's save-only selection is revision-bound and keeps its holds;
unsupported combinations refuse before anything is started or changed; `provider plan` shows the
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
# What an Azure plan still waits for since A2 (restart and revival stay Personal only):
PENDING = ["restart and revival (L2)", "native qualification"]
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

    def give_session(self, tid, session, agent=-1):
        """Its agent's conversation, as the watcher records one it finds (sessions.refresh_sessions): the fixture's
        stand-in for a session log, written into the task list herdr-task reopens."""
        path = self.ok("where", "--folder", self.repo)["store"]
        with open(path) as fh:
            d = json.load(fh)
        t = next(x for x in d["tasks"] if x["id"] == tid)
        t["agents"][agent]["session"] = session
        with open(path, "w") as fh:
            json.dump(d, fh, indent=2)

    def agent_words(self, run):
        """(shell script, agent argv) of one hc run that started a task's agent: what in_shell() runs."""
        at = run.index("herdr-low")
        cmd = run[at + 5:]
        return cmd[4], cmd[6:]

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
        only, the person's shell, claude with its own --settings, and nothing of a provider's. All of it
        run as upstream runs every agent (SHEP-86): exactly clean_env() of those words, nothing else."""
        sys.path.insert(0, BIN)
        from herdr_task.launch import clean_env
        run = f.launches()
        self.assertEqual(len(run), 1, f.calls())
        words = run[0]
        at = words.index("herdr-low")
        cmd = words[at + 5:]  # what clean_env() wraps: its own 4 words come first
        self.assertEqual(words[at + 1:], clean_env(cmd))
        self.assertEqual(cmd[:6], ["env", "HERDR_BROWSER_TASK=" + words[words.index("--label") + 1].split("=", 1)[1],
                                   "/bin/sh", cmd[3], '"$@"; exec "$0" -i', "/bin/sh"])
        self.assertIn(cmd[3], ("-ic", "-lic"))
        agent = cmd[6:]
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
        plan = f.plan("--agent", "claude")
        self.assertRegex(plan.pop("revision"), r"^[0-9a-f]{16}$")
        self.assertEqual(plan, {
            "route": "personal", "agent": "claude", "fingerprint": "personal", "deployment": None, "auth": None, "target": None,
            "credential": None, "settings_env": {}, "args": [], "env": {}, "argv": ["claude"], "dispatch": "pass-through", "pending": []})
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


def record(auth="entra-id", kind="claude", deployment=None):
    """The nonsecret binding a start records, written out apart from the code."""
    if kind == "codex":
        return {"route": "azure-foundry", "agent": "codex", "target": "https://example.openai.azure.com/openai/v1",
                "deployment": deployment or "code-deployment", "auth": "api-key", "fingerprint": FP["codex"]}
    return {"route": "azure-foundry", "agent": "claude", "target": "example", "deployment": deployment or "claude-deployment",
            "auth": auth, "fingerprint": FP[auth]}


@ON_CI
class AzureRefusesBeforeEffects(unittest.TestCase):
    """Under an Azure binding that can't be planned, no start, queue or resume happens: each
    unsupported or incomplete combination says what is wrong before a worktree, the task list or hc
    is touched."""

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

    def test_codex_with_entra_id_is_unsupported(self):
        for auth in ("entra-id", "bearer-token"):
            with self.subTest(auth=auth):
                self.refuse_start({"route": "azure-foundry", **CODEX, "codex_auth": auth}, "API key only", agent="codex")

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

    def test_the_tick_keeps_a_queued_task_it_cant_plan_and_starts_it_once_it_can(self):
        f = Fixture(self)
        f.provider({"route": "personal"}, also=ROOM)
        first, second = f.add("--here"), f.add("--here", "--after", "1")
        self.assertEqual(f.ok("start", str(second), "--folder", f.repo, "--space", "sp1")["queued"], True)
        f.ok("rm", str(first), "--folder", f.repo)
        # Azure with no deployment: nothing to plan, so it keeps its place and says why.
        f.provider({"route": "azure-foundry", "claude_resource": "example"}, also=ROOM)
        self.assertEqual(f.ok("tick", "--folder", f.repo)["started"], [])
        task = f.task(second)
        self.assertEqual((task["state"], task["agents"], "queue" in task), ("queued", [], True))
        self.assertIn("explicit Azure deployment name for Claude Code", task["attention"])
        self.assertEqual((f.launches(), f.worktrees(), f.branches()), ([], [f"worktree {f.repo}"], ["main"]))
        # Set in full, the next tick starts it on its plan, its binding recorded.
        f.provider({"route": "azure-foundry", **CLAUDE}, also=ROOM)
        self.assertEqual([x["id"] for x in f.ok("tick", "--folder", f.repo)["started"]], [second])
        self.assertEqual(len(f.launches()), 1)
        self.assertEqual(f.task(second)["agents"][0]["provider"], record())
        f.settle(tid=second)
        f.no_secret()


@ON_CI
class AzureStartsBound(unittest.TestCase):
    """A task's agent starts on its Azure plan and records its nonsecret binding; resuming that
    conversation keeps it (A2)."""

    def start(self, f, provider, *extra, tid=None):
        f.provider(provider)
        tid = tid or f.add("--here")
        f.ok("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now", *extra)
        return tid

    def test_each_supported_sign_in_starts_on_its_plan_and_records_its_binding(self):
        for auth, credential in (("entra-id", None), ("api-key", "ANTHROPIC_FOUNDRY_API_KEY"), ("bearer-token", "ANTHROPIC_FOUNDRY_AUTH_TOKEN")):
            with self.subTest(auth=auth):
                f = Fixture(self)
                tid = self.start(f, {"route": "azure-foundry", **CLAUDE, "claude_auth": auth})
                [run] = f.launches()
                self.assertIn("herdr.provider=azure-foundry", run)
                script, agent = f.agent_words(run)
                # The deployment is the argv's one model; the plan's env joins the --settings it already has.
                self.assertEqual((agent[0], agent[agent.index("--model") + 1], agent.count("--settings"), agent.count("--model")),
                                 ("claude", "claude-deployment", 1, 1))
                settings = json.loads(agent[agent.index("--settings") + 1])
                self.assertEqual((settings["env"], settings["fastMode"]), (claude_env("claude-deployment", credential), False))
                self.assertIn("permissions", settings)  # its own herdr-task commands, as on Personal
                # The credential is only looked for, by name, in the agent's own shell before the CLI starts.
                if credential:
                    self.assertIn(f'if [ -z "${{{credential}:-}}" ]', script)
                    self.assertIn(f"Azure Foundry needs {credential}", script)
                else:
                    self.assertNotIn("if [ -z", script)
                self.assertEqual(f.task(tid)["agents"][0]["provider"], record(auth))
                f.settle(tid=tid)
                f.no_secret()

    def test_codex_starts_on_its_provider_table_with_openai_variables_blanked(self):
        f = Fixture(self)
        tid = self.start(f, {"route": "azure-foundry", **CODEX}, "--agent", "codex")
        [run] = f.launches()
        script, agent = f.agent_words(run)
        ident = "shepherdr_azure_" + FP["codex"]
        self.assertEqual((agent[0], agent[1], agent[2]), ("codex", "-c", f'model_provider="{ident}"'))
        self.assertEqual(agent[agent.index("-m") + 1], "code-deployment")
        self.assertIn("export OPENAI_BASE_URL=''; export OPENAI_API_KEY=''; ", script)
        self.assertIn('if [ -z "${AZURE_OPENAI_API_KEY:-}" ]', script)
        self.assertEqual(f.task(tid)["agents"][0]["provider"], record(kind="codex"))
        f.settle(tid=tid)
        f.no_secret()

    def test_a_workers_own_deployment_wins_over_the_clis(self):
        f = Fixture(self)
        tid = self.start(f, {"route": "azure-foundry", **CLAUDE, "worker_claude_deployment": "worker-deployment",
                             "coordinator_claude_deployment": "assistant-deployment"})
        [run] = f.launches()
        _, agent = f.agent_words(run)
        self.assertEqual(agent[agent.index("--model") + 1], "worker-deployment")
        self.assertEqual(f.task(tid)["agents"][0]["provider"]["deployment"], "worker-deployment")
        f.settle(tid=tid)

    def test_resume_keeps_the_recorded_deployment_when_the_default_changes(self):
        f = Fixture(self)
        tid = self.start(f, {"route": "azure-foundry", **CLAUDE, "claude_auth": "api-key"})
        f.settle(tid=tid)
        f.give_session(tid, "11111111-2222-4333-8444-555555555555")
        f.provider({"route": "azure-foundry", **CLAUDE, "claude_auth": "api-key", "claude_deployment": "new-default"})
        out = f.ok("resume", str(tid), "--folder", f.repo, "--space", "sp1")
        self.assertTrue(out["resumed"])
        run = f.launches()[-1]
        script, agent = f.agent_words(run)
        # Claude Code's Foundry environment is rebuilt from the record: its deployment, not the new default.
        self.assertEqual(agent[agent.index("--model") + 1], "claude-deployment")
        self.assertEqual(json.loads(agent[agent.index("--settings") + 1])["env"], claude_env("claude-deployment", "ANTHROPIC_FOUNDRY_API_KEY"))
        self.assertEqual(agent[agent.index("--resume") + 1], "11111111-2222-4333-8444-555555555555")
        self.assertIn('if [ -z "${ANTHROPIC_FOUNDRY_API_KEY:-}" ]', script)
        self.assertEqual(f.task(tid)["agents"][-1]["provider"], record("api-key"))
        f.settle(2, tid=tid)
        f.no_secret()

    def test_codex_resume_keeps_its_provider_deployment_effort_and_fast(self):
        f = Fixture(self)
        argv = ["codex", "--no-daemon", "-c", 'model_reasoning_effort="high"', "-c", 'service_tier="fast"']
        tid = self.start(f, {"route": "azure-foundry", **CODEX}, "--argv", json.dumps(argv))
        f.settle(tid=tid)
        f.give_session(tid, "22222222-3333-4444-8555-666666666666")
        f.provider({"route": "azure-foundry", **CODEX, "codex_deployment": "new-default"})
        self.assertTrue(f.ok("resume", str(tid), "--folder", f.repo, "--space", "sp1")["resumed"])
        _, agent = f.agent_words(f.launches()[-1])
        ident = "shepherdr_azure_" + FP["codex"]
        at = agent.index("resume")
        # Its provider table and its recorded deployment go before the subcommand; its effort, Fast and session after.
        self.assertEqual(agent[1:3], ["-c", f'model_provider="{ident}"'])
        self.assertEqual(agent[agent.index("-m") + 1], "code-deployment")
        self.assertLess(agent.index("-m"), at)
        self.assertEqual(agent[at:], ["resume", "--no-daemon", "-c", 'model_reasoning_effort="high"', "-c", 'service_tier="fast"',
                                      "22222222-3333-4444-8555-666666666666"])
        self.assertNotIn("new-default", json.dumps(agent))
        f.settle(2, tid=tid)
        f.no_secret()

    def test_changed_routing_refuses_before_anything_changes(self):
        for changed, words in (({"claude_resource": "other"}, "Azure Foundry other with Entra ID"),
                               ({"claude_auth": "api-key"}, "Azure Foundry example with API key"),
                               ({"route": "personal"}, "Personal (the CLI's own sign-in)")):
            with self.subTest(changed=changed):
                f = Fixture(self)
                tid = self.start(f, {"route": "azure-foundry", **CLAUDE})
                f.settle(tid=tid)
                f.give_session(tid, "33333333-4444-4555-8666-777777777777")
                f.provider({"route": "azure-foundry", **CLAUDE, **changed})
                before = f.snapshot()
                for verb in ("resume", "switch"):
                    why = f.refused(verb, str(tid), "--folder", f.repo, "--space", "sp1")
                    self.assertIn("conversation started on Azure Foundry example with Entra ID", why)
                    self.assertIn(words, why)
                    self.assertIn("--fresh", why)
                    # nothing started, and switch's old agent was not ended
                    f.nothing_started(before)
                # A new conversation with a handoff takes today's settings and records them.
                out = f.ok("resume", str(tid), "--folder", f.repo, "--space", "sp1", "--fresh")
                self.assertFalse(out["resumed"])
                rec = f.task(tid)["agents"][-1].get("provider")
                self.assertEqual(rec if rec is None else rec["route"], None if changed.get("route") == "personal" else "azure-foundry")
                f.settle(2, tid=tid)
                f.no_secret()

    def test_a_personal_conversation_is_never_moved_to_azure(self):
        f = Fixture(self)
        tid = self.start(f, {"route": "personal"})
        f.settle(tid=tid)
        f.give_session(tid, "44444444-5555-4666-8777-888888888888")
        f.provider({"route": "azure-foundry", **CLAUDE})
        before = f.snapshot()
        why = f.refused("resume", str(tid), "--folder", f.repo, "--space", "sp1")
        self.assertIn("conversation started on Personal (the CLI's own sign-in)", why)
        f.nothing_started(before)
        # Personal again, it resumes as it always did.
        f.provider({"route": "personal"})
        self.assertTrue(f.ok("resume", str(tid), "--folder", f.repo, "--space", "sp1")["resumed"])
        self.assertNotIn("provider", f.task(tid)["agents"][-1])
        f.settle(2, tid=tid)

    def test_a_model_menus_restart_stays_personal_only(self):
        f = Fixture(self)
        tid = self.start(f, {"route": "azure-foundry", **CLAUDE})
        f.settle(tid=tid)
        before = f.snapshot()
        why = f.refused("switch", str(tid), "--folder", f.repo, "--space", "sp1", "--restart")
        self.assertIn("can't carry an Azure Foundry binding yet", why)
        f.nothing_started(before)
        # A Personal agent under Azure settings: what it would start isn't Personal either.
        g = Fixture(self)
        tid = self.start(g, {"route": "personal"})
        g.settle(tid=tid)
        g.provider({"route": "azure-foundry", **CLAUDE})
        before = g.snapshot()
        self.assertIn("Provider is Azure Foundry here", g.refused("switch", str(tid), "--folder", g.repo, "--space", "sp1", "--restart"))
        g.nothing_started(before)

    def test_an_automation_starts_its_task_on_the_plan(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE}, also=ROOM)
        auto = f.ok("auto", "add", "Nightly check", "--folder", f.repo, "--space", "sp1", "--on", "merged", "--here")
        f.ok("auto", "run-now", str(auto["id"]), "--folder", f.repo)
        self.assertEqual(len(f.launches()), 1)
        self.assertEqual(f.task(1)["agents"][0]["provider"], record())
        f.settle(tid=1)
        f.no_secret()


@ON_CI
class TaskSelection(unittest.TestCase):
    """`herdr-task select`: a task's save-only new-start choice, bound to the revision it was
    shown at and to the routing it was chosen under."""

    def test_a_save_is_revision_bound_and_changes_nothing_else(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE, **CODEX}, also=ROOM)
        first, tid = f.add("--here"), f.add("--here", "--after", "1")
        self.assertEqual(f.ok("start", str(tid), "--folder", f.repo, "--space", "sp1")["queued"], True)
        shown = f.ok("select", str(tid), "--folder", f.repo, "--space", "sp1")
        self.assertEqual((shown["locked"], shown["route"], shown["selection"]), (False, "azure-foundry", {"agent": None, "deployment": None, "model": None, "effort": None}))
        self.assertEqual(shown["clis"]["codex"]["deployment"], "code-deployment")
        before = f.task(tid)
        calls = len(f.calls())
        # A stale or missing revision changes nothing.
        for rev in ("0" * 16, ""):
            self.assertIn("changed since this selector was opened",
                          f.refused("select", str(tid), "--folder", f.repo, "--space", "sp1", "--agent", "codex", "--revision", rev))
        self.assertEqual(f.task(tid), before)
        saved = f.ok("select", str(tid), "--folder", f.repo, "--space", "sp1", "--agent", "codex", "--deployment", "picked-deployment",
                     "--effort", "high", "--revision", shown["revision"])
        self.assertEqual(saved["selection"], {"agent": "codex", "deployment": "picked-deployment", "model": None, "effort": "high"})
        after = f.task(tid)
        # Its state, place in the queue, dependency and hold are as they were; nothing was started or sent.
        for k in ("state", "queued_at", "after", "held", "scheduled_for", "agents"):
            self.assertEqual(after.get(k), before.get(k), k)
        self.assertEqual(after["queue"]["argv"][0], "codex")
        self.assertEqual([c for c in f.calls()[calls:] if c and c[0] in EFFECTS], [])
        # The revision it was shown at is spent: a second save with it refuses, even to the same values.
        self.assertIn("changed since this selector was opened",
                      f.refused("select", str(tid), "--folder", f.repo, "--space", "sp1", "--agent", "codex", "--revision", shown["revision"]))
        # Its first start runs on the choice and records it; then the choice is locked.
        f.ok("rm", str(first), "--folder", f.repo)
        self.assertEqual([x["id"] for x in f.ok("tick", "--folder", f.repo)["started"]], [tid])
        _, agent = f.agent_words(f.launches()[-1])
        self.assertEqual(agent[agent.index("-m") + 1], "picked-deployment")
        self.assertIn('model_reasoning_effort="high"', agent)
        rec = f.task(tid)["agents"][0]["provider"]
        self.assertEqual({k: rec[k] for k in ("route", "agent", "deployment", "auth")}, {"route": "azure-foundry", "agent": "codex",
                                                                                         "deployment": "picked-deployment", "auth": "api-key"})
        self.assertNotEqual(rec["fingerprint"], FP["codex"])  # the deployment is part of the binding
        now = f.ok("select", str(tid), "--folder", f.repo, "--space", "sp1")
        self.assertTrue(now["locked"])
        self.assertIn("locked", f.refused("select", str(tid), "--folder", f.repo, "--space", "sp1", "--default", "--revision", now["revision"]))
        f.settle(tid=tid)
        f.no_secret()

    def test_a_choice_made_under_one_routing_refuses_under_another(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE})
        tid = f.add("--here")
        shown = f.ok("select", str(tid), "--folder", f.repo, "--space", "sp1")
        f.ok("select", str(tid), "--folder", f.repo, "--space", "sp1", "--agent", "claude", "--deployment", "chosen", "--revision", shown["revision"])
        for changed in ({"route": "personal"}, {"route": "azure-foundry", **CLAUDE, "claude_resource": "other"}):
            with self.subTest(changed=changed):
                f.provider(changed)
                before = f.snapshot()
                self.assertIn("changed since this start was chosen", f.refused("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now"))
                f.nothing_started(before)
        # Back to configured defaults, it starts on today's settings.
        shown = f.ok("select", str(tid), "--folder", f.repo, "--space", "sp1")
        f.ok("select", str(tid), "--folder", f.repo, "--space", "sp1", "--default", "--revision", shown["revision"])
        self.assertEqual(f.task(tid).get("deployment"), None)
        f.ok("start", str(tid), "--folder", f.repo, "--space", "sp1", "--now")
        _, agent = f.agent_words(f.launches()[-1])
        self.assertEqual(agent[agent.index("--model") + 1], "claude-deployment")
        f.settle(tid=tid)

    def test_a_deployment_isnt_chosen_on_personal(self):
        f = Fixture(self)
        tid = f.add("--here")
        shown = f.ok("select", str(tid), "--folder", f.repo)
        self.assertIn("on Azure Foundry only", f.refused("select", str(tid), "--folder", f.repo, "--agent", "claude", "--deployment", "x",
                                                         "--revision", shown["revision"]))
        self.assertNotIn("deployment", f.task(tid))
        # The CLI, its model and effort are the choice on Personal; its first start runs on them.
        f.ok("select", str(tid), "--folder", f.repo, "--agent", "codex", "--model", "gpt-pick", "--effort", "high", "--revision", shown["revision"])
        self.assertEqual((f.task(tid)["agent"], f.task(tid)["model"], f.task(tid)["effort"]), ("codex", "gpt-pick", "high"))
        f.ok("start", str(tid), "--folder", f.repo, "--now")
        _, agent = f.agent_words(f.launches()[-1])
        self.assertEqual(agent[agent.index("-m") + 1], "gpt-pick")
        self.assertIn('model_reasoning_effort="high"', agent)
        f.settle(tid=tid)
        # On Azure the deployment is the model: --model refuses there.
        g = Fixture(self)
        g.provider({"route": "azure-foundry", **CODEX})
        other = g.add("--here")
        shown = g.ok("select", str(other), "--folder", g.repo)
        self.assertIn("the deployment is the model", g.refused("select", str(other), "--folder", g.repo, "--agent", "codex", "--model", "gpt-pick",
                                                                "--revision", shown["revision"]))

    def test_a_deployment_that_cant_be_one_is_refused_and_never_repeated(self):
        f = Fixture(self)
        tid = f.add("--here")
        shown = f.ok("select", str(tid), "--folder", f.repo)
        why = f.refused("select", str(tid), "--folder", f.repo, "--agent", "claude", "--deployment", INLINE + " x", "--revision", shown["revision"])
        self.assertIn("explicit Azure deployment name", why)
        self.assertNotIn(INLINE, f.seen + f.store_text())


@ON_CI
class LaunchPlans(unittest.TestCase):
    """`provider plan`: each supported route's official plan, by name only, without starting or
    asking for anything."""

    def planned(self, f, *args):
        out = f.plan(*args)
        self.assertEqual(f.calls(), [])  # a plan runs no hc at all
        # The revision a selector's choice made now is bound to: a short digest of the routing, never a value.
        self.assertRegex(out.pop("revision"), r"^[0-9a-f]{16}$")
        f.no_secret()
        # An Azure plan names what can outrank it on the execution host, each with its evidence and
        # what is seen of it here (L1): it never says the plan is what will run.
        layers = out.pop("outranked_by", None)
        if out.get("route") == "azure-foundry":
            want = {"claude": ["Claude apps gateway sign-in", "Claude managed settings"], "codex": ["Codex required_model_provider()"]}
            self.assertEqual([r["layer"] for r in layers], want[out["agent"]])
            self.assertTrue(all(r["effect"] and r["evidence"] and r["observed"] for r in layers))
        else:
            self.assertIsNone(layers)
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
                    "target": "example", "credential": credential, "settings_env": env, "args": [], "env": {}, "dispatch": "planned",
                    "pending": PENDING})
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
            "target": "https://example.openai.azure.com/openai/v1", "credential": "AZURE_OPENAI_API_KEY", "settings_env": {}, "args": args,
            "env": {"OPENAI_BASE_URL": "", "OPENAI_API_KEY": ""}, "argv": ["codex", *args, "-m", "code-deployment", "--no-daemon"],
            "dispatch": "planned", "pending": PENDING})

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

    def test_words_after_a_bare_double_dash_are_operands_unless_claude_could_read_them_as_options(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE, **CODEX})
        for operands in (["--oss"], ["--local-provider=ollama"], ["-c", 'model_provider="azure"']):
            with self.subTest(codex=operands):
                out = self.planned(f, "--argv", json.dumps(["codex", "--no-daemon", "--", *operands]))
                self.assertEqual(out["argv"], ["codex", *out["args"], "-m", "code-deployment", "--no-daemon", "--", *operands])
        # Claude Code: any other word after the "--" is left as it is, and the plan's own
        # --settings goes before the "--".
        operands = ["fix the tests", "--settings-note"]
        argv = self.planned(f, "--argv", json.dumps(["claude", "--effort", "high", "--", *operands]))["argv"]
        self.assertEqual(argv[:2] + argv[3:], ["claude", "--settings", "--model", "claude-deployment", "--effort", "high", "--", *operands])
        self.assertEqual(json.loads(argv[2]), {"env": claude_env("claude-deployment")})
        # But the "--" may be another option's value, and then a --settings or --model after it
        # is a real option: it can't be told apart, so it is refused and never repeated.
        unsure = "can't be told from an option"
        for argv in (["claude", "--append-system-prompt", "--", "--settings", "/file.json"],
                     ["claude", "--append-system-prompt", "--", "--model", "other"],
                     ["claude", "--append-system-prompt", "--", "--model=other"],
                     ["claude", "--", "--settings=/file.json"],
                     ["claude", "--", "--settings", "/somewhere/settings.json"],
                     ["claude", "--settings", '{"fastMode": true}', "--", "--settings=/somewhere/settings.json", "--settings", "{}"]):
            with self.subTest(claude=argv):
                why = f.no_plan("--argv", json.dumps(argv))
                self.assertIn(unsure, why)
                self.assertTrue(why.endswith("Nothing was started."), why)
                self.assertNotIn(argv[-1], why)
        # An inline --settings there, carrying the plan's own credential variable: its value is
        # in nothing herdr-task says.
        f.provider({"route": "azure-foundry", **CLAUDE, "claude_auth": "api-key"})
        inline = json.dumps({"env": {"ANTHROPIC_FOUNDRY_API_KEY": INLINE}})
        self.assertIn(unsure, f.no_plan("--argv", json.dumps(["claude", "--append-system-prompt", "--", "--settings", inline])))
        self.assertNotIn(INLINE, f.seen + json.dumps(f.calls()))
        self.assertEqual(f.calls(), [])
        f.no_secret()

    def test_an_argv_that_routes_itself_is_refused(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE, **CODEX})
        own = "remove the argv's own provider"
        needs = "--settings needs its inline JSON value right after it. Nothing was started."
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
                            # A --settings with nothing after it, at the end or before a bare "--".
                            (["claude", "--settings"], needs),
                            (["claude", "--effort", "high", "--settings"], needs),
                            (["claude", "--settings", "--", "x"], needs),
                            # Followed by another option: its missing value, not a file path (A1's PR 17 carried to L1).
                            (["claude", "--settings", "--effort", "high"], needs),
                            (["claude", "--settings", "-p"], needs),
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
                      "Restart and revival (L2) stay Personal only", "no sign-in, credential or model request was tried"):
            self.assertIn(words, p.stdout)
        p = f.run("provider", "plan", "--help")
        self.assertEqual(p.returncode, 0, p.stderr)
        for words in ("--agent", "--argv", "--space", "--role", "--deployment", "--folder", "--json", "Reads no credential, starts nothing, signs in nowhere"):
            self.assertIn(words, " ".join(p.stdout.split()))  # argparse wraps its lines
        self.assertIn("provider", f.run("--help").stdout)
        self.assertEqual(f.calls(), [])
        f.no_secret()


@ON_CI
class SelectorView(unittest.TestCase):
    """`provider show`: what a new-start selector shows for a role, read-only."""

    def test_it_shows_each_clis_routing_deployment_and_revision_and_starts_nothing(self):
        f = Fixture(self)
        f.provider({"route": "azure-foundry", **CLAUDE, "coordinator_claude_deployment": "assistant-deployment", "claude_auth": "api-key"})
        out = f.ok("provider", "show", "--folder", f.repo, "--space", "sp1", "--role", "coordinator")
        self.assertEqual((out["route"], out["role"]), ("azure-foundry", "coordinator"))
        self.assertEqual(out["clis"]["claude"]["deployment"], "assistant-deployment")
        self.assertEqual(out["clis"]["claude"]["routing"], "Azure Foundry example with API key")
        self.assertIsNone(out["clis"]["claude"]["problem"])
        # Codex isn't set up: it says what is missing instead of refusing the view.
        self.assertIn("Codex", out["clis"]["codex"]["problem"])
        rev = out["clis"]["claude"]["revision"]
        # A deployment default is not routing: the revision stays; the sign-in method is, and it changes.
        f.provider({"route": "azure-foundry", **CLAUDE, "claude_auth": "api-key", "claude_deployment": "other"})
        self.assertEqual(f.ok("provider", "show", "--folder", f.repo, "--space", "sp1", "--role", "coordinator")["clis"]["claude"]["revision"], rev)
        f.provider({"route": "azure-foundry", **CLAUDE})
        self.assertNotEqual(f.ok("provider", "show", "--folder", f.repo, "--space", "sp1", "--role", "coordinator")["clis"]["claude"]["revision"], rev)
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

    def backup(self, provider, launch=None):
        with open(self.file, "w") as f:
            json.dump({"everywhere": {"provider": provider}}, f)
        ran, started = [], []
        store = type("S", (), {"loc": {"folder": "/f"}, "dirty": False, "key": lambda self, t: "f#1", "ref": lambda self, t: "F-1"})()
        task = {"id": 1, "space": "sp1", "agents": [{"address": "t1", "agent": "claude"}]}
        k = {"address": "t1", "labels": {"herdr.agent": "claude", "herdr.task.space": "sp1"}}
        patches = {"backup_for": lambda s, t, running: ("codex", None), "backup_argv": lambda s, t, kind: ["codex", "--no-daemon"],
                   "handover": lambda *a: "handover", "brief": lambda *a: "brief",
                   "launch": launch or (lambda s, t, argv, space, text, parent=None, admission=None: started.append(argv) or {"address": "t2"}),
                   "run": lambda args, **kw: ran.append(args)}
        for name, value in patches.items():
            p = self.mock.patch.object(self.takeover, name, value)
            p.start()
            self.addCleanup(p.stop)
        # Launch admission (L1) runs for real: its journal in a throwaway folder, and no Assistant to find.
        import herdr_task.launch as launch
        import herdr_task.launch_admission as admission
        for module, name, value in ((admission, "STORE", tempfile.mkdtemp()), (launch, "parent_for", lambda parent, space: None)):
            p = self.mock.patch.object(module, name, value)
            p.start()
            self.addCleanup(p.stop)
        row = self.takeover.takeover(store, task, k, {"reason": "Out of allowance until 5pm"}, None, {})
        return row, task, started, ran

    def test_a_backup_starts_on_personal(self):
        row, task, started, ran = self.backup({"route": "personal"})
        self.assertEqual((row, task["backup"]["state"], started, ran), (None, "started", [["codex", "--no-daemon"]], [["hc", "kill", "t1"]]))

    def test_a_backup_that_may_have_started_is_uncertain_not_failed(self):
        """A backup whose start was sent but never confirmed keeps its launch id as uncertain (L1), and the stuck agent
        isn't ended; a known failure stays failed."""
        def uncertain(*a, **k):
            e = self.p.Fail("hc didn't confirm this start")
            e.launch = {"launch": "6f1c2d3e-4a5b-4c6d-8e7f-001122334455", "identity": "task:f#1", "state": "submission-uncertain"}
            raise e
        row, task, started, ran = self.backup({"route": "personal"}, launch=uncertain)
        self.assertEqual((task["backup"]["state"], task["backup"]["launch"], ran), ("uncertain", "6f1c2d3e-4a5b-4c6d-8e7f-001122334455", []))
        self.assertEqual(row["reason"], "Out of allowance, backup uncertain")
        self.assertLessEqual(len(row["reason"]), 40)

        def broken(*a, **k):
            raise self.p.Fail("git worktree add failed")
        row, task, started, ran = self.backup({"route": "personal"}, launch=broken)
        self.assertEqual((task["backup"]["state"], "launch" in task["backup"], ran), ("failed", False, []))

    def test_a_backup_on_azure_starts_on_its_plan(self):
        """A backup is a new conversation in the other CLI: it takes today's plan for its CLI (A2), never the stuck
        agent's recorded binding."""
        admitted = []

        def launch(s, t, argv, space, text, parent=None, admission=None):
            admitted.append(admission.plan)
            return {"address": "t2"}
        row, task, started, ran = self.backup({"route": "azure-foundry", **CODEX}, launch=launch)
        self.assertEqual((row, task["backup"]["state"], ran), (None, "started", [["hc", "kill", "t1"]]))
        self.assertEqual([(p["route"], p["agent"], p["deployment"]) for p in admitted], [("azure-foundry", "codex", "code-deployment")])

    def test_a_backup_the_provider_cant_plan_isnt_spent(self):
        row, task, started, ran = self.backup({"route": "azure-foundry", **CODEX, "codex_auth": "entra-id"})
        # The refusal's own words follow "backup held", cut to the reason's one line.
        self.assertEqual(("backup" in task, started, ran), (False, [], []))
        self.assertTrue(row["reason"].startswith("Out of allowance, backup held: Codex"), row["reason"])
        self.assertLessEqual(len(row["reason"]), 40)

    def test_revival_holds_an_agent_whose_route_or_start_isnt_personal(self):
        """revive.plan (L2's site): a lost Assistant is typed back on Personal only. Under an Azure route at its space,
        or with an Azure-started label, it is held, never started on the CLI's own sign-in."""
        import herdr_task.revive as revive
        k = {"address": "t1", "pid": 7, "argv": ["/bin/zsh"], "labels": {"herdr.role": "coordinator", "herdr.coordinator.space": "sp1"}}
        rec = {"kind": "claude", "session": "s1", "log": "/nonexistent/s1.jsonl", "argv": ["claude"], "pid": 1}
        for provider, label, held in (({"route": "personal"}, None, False), ({"route": "azure-foundry", **CLAUDE}, None, True),
                                      ({"route": "personal"}, "azure-foundry", True)):
            with self.subTest(route=provider["route"], label=label):
                with open(self.file, "w") as f:
                    json.dump({"everywhere": {"provider": provider}}, f)
                labels = {**k["labels"], **({"herdr.provider": label} if label else {})}
                step = revive.plan({**k, "labels": labels}, dict(rec), set())
                self.assertEqual(step is not None and step[0] == "held", held, step)
        # Settings that can't be read can't say Personal: held too.
        with open(self.file, "w") as f:
            f.write("{")
        self.assertEqual(revive.plan(k, dict(rec), set())[0], "held")

    def test_the_credential_check_runs_the_agent_only_when_its_variable_is_set(self):
        """The guard in_shell() puts in the agent's own shell, run by a real POSIX shell: missing or empty, it names
        the variable and runs nothing; set, the agent runs. Only presence is looked at, never the value."""
        from herdr_task.launch import in_shell
        env = {k: v for k, v in os.environ.items() if k != "AZURE_OPENAI_API_KEY"}
        env["SHELL"] = "/bin/sh"
        p = self.mock.patch.dict(os.environ, {"SHELL": "/bin/sh"})
        p.start()
        self.addCleanup(p.stop)
        words = in_shell(["echo", "agent-ran"], None, {"OPENAI_BASE_URL": ""}, "AZURE_OPENAI_API_KEY")
        # in_shell keeps the person's shell after the agent: replace its last exec so the test's shell ends.
        script = words[2].replace('exec "$0" -i', "true")
        for value, ran in ((None, False), ("", False), ("marker-azure-openai-key-52de", True)):
            with self.subTest(value=value):
                e = dict(env, **({"AZURE_OPENAI_API_KEY": value} if value is not None else {}))
                r = subprocess.run(["/bin/sh", "-c", script, "sh", "echo", "agent-ran"], capture_output=True, text=True, env=e, timeout=30)
                self.assertEqual("agent-ran" in r.stdout, ran, r.stdout + r.stderr)
                self.assertEqual("Azure Foundry needs AZURE_OPENAI_API_KEY" in r.stderr, not ran)
                self.assertNotIn("marker-azure-openai-key-52de", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
