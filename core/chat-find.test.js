import { afterAll, afterEach, expect, test } from "bun:test";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import * as AG from "./agents.js";
import { argvFor, inOtherFolder, OTHER_FOLDER, sessionOf } from "./agents.js";
import * as LOG from "./chat-log.js";
import { FIND } from "./chat-log.js";

// FIND as its callers run it (sh, on the agent's machine) against real processes in throwaway folders. Each agent
// here is a python3 that waits: on macOS a system binary's environment reads as empty, so it wouldn't do. Linux runs
// these on CI; on macOS they take FIND's other reader, and CI never does.
const SESSION = "aaaaaaaa-0000-4000-8000-000000000001";
const OTHER = "bbbbbbbb-0000-4000-8000-000000000002";
// Everything a shell or printf could take for something else, in one folder's name.
const ODD = `odd \\n $(x) * "quoted" 'single'`;
const WAIT = `print("ready", flush=True); import time; time.sleep(120)`;
// Linux: a process that isn't dumpable keeps /proc/<pid>/environ from its own user too.
const SEALED = `import ctypes; ctypes.CDLL(None).prctl(4, 0, 0, 0, 0); ${WAIT}`;
// A wrapper that has no session of its own: its child has, under the folder given, and prints its pid.
const WRAPPER = `
import os, subprocess, sys, time
c = subprocess.Popen([sys.executable, "-c", sys.argv[1]], env={**os.environ, "CLAUDE_CONFIG_DIR": sys.argv[2]}, stdout=subprocess.PIPE)
c.stdout.readline()
print(c.pid, flush=True)
time.sleep(120)
`;

const home = realpathSync(mkdtempSync(join(tmpdir(), "chat-find-")));
const fallback = join(home, ".claude");
let running = [];
let folders = 0;

afterEach(() => {
  for (const kill of running) kill();
  running = [];
  rmSync(fallback, { recursive: true, force: true });
});
afterAll(() => rmSync(home, { recursive: true, force: true }));

const folder = (name = `profile-${folders++}`) => join(home, name);
const environment = (env) => ({ PATH: process.env.PATH, HOME: home, ...env });

async function firstLine(p) {
  const reader = p.stdout.getReader();
  const { value } = await reader.read();
  reader.releaseLock();
  return new TextDecoder().decode(value).trim();
}

// A real process with exactly this environment, waiting until it has started.
async function agent(env = {}, code = WAIT, args = []) {
  const p = Bun.spawn(["python3", "-c", code, ...args], { env: environment(env), stdout: "pipe", stderr: "ignore" });
  running.push(() => p.kill(9));
  return { pid: p.pid, line: await firstLine(p) };
}

// What Claude Code leaves for a process: its metadata, and its log unless `log` is false. Returns the log's path.
function session(dir, pid, id = SESSION, { log = true, owner = pid } = {}) {
  mkdirSync(join(dir, "sessions"), { recursive: true });
  writeFileSync(join(dir, "sessions", `${pid}.json`), JSON.stringify({ pid: owner, sessionId: id, cwd: "/work", kind: "interactive" }));
  const path = join(dir, "projects", "-work", `${id}.jsonl`);
  if (log) {
    mkdirSync(join(dir, "projects", "-work"), { recursive: true });
    writeFileSync(path, "{}\n");
  }
  return path;
}

// What a caller reads back: the last line of FIND's output (core/chat-reader.js).
async function find(pid, env = {}) {
  const p = Bun.spawn(["sh", "-c", FIND, "chat", "claude", String(pid)], { env: environment(env), stdout: "pipe", stderr: "ignore" });
  const out = await new Response(p.stdout).text();
  await p.exited;
  return out.trim().split("\n").pop();
}

test("no CLAUDE_CONFIG_DIR: the session under ~/.claude", async () => {
  const { pid } = await agent();
  const log = session(fallback, pid);
  expect(await find(pid)).toBe(log);
});

test("CLAUDE_CONFIG_DIR set: the session under exactly that folder", async () => {
  const dir = folder();
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  const log = session(dir, pid);
  expect(await find(pid)).toBe(log);
});

test("a folder with spaces in its name is read whole", async () => {
  const dir = join(home, "Application Support", "a profile");
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  const log = session(dir, pid);
  expect(await find(pid)).toBe(log);
});

test("two agents at once, each with its own folder and session, each finds only its own", async () => {
  const [one, two] = [folder(), folder()];
  const a = await agent({ CLAUDE_CONFIG_DIR: one });
  const b = await agent({ CLAUDE_CONFIG_DIR: two });
  const logA = session(one, a.pid, SESSION);
  const logB = session(two, b.pid, OTHER);
  // Each folder also names the other's process, as a scan across folders would trip on.
  session(one, b.pid, SESSION);
  session(two, a.pid, OTHER);
  expect(await find(a.pid)).toBe(logA);
  expect(await find(b.pid)).toBe(logB);
});

test("no metadata: nothing", async () => {
  const dir = folder();
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  session(dir, pid + 1);
  expect(await find(pid)).toBe("");
});

test("metadata whose pid isn't this process's: nothing", async () => {
  const { pid } = await agent();
  session(fallback, pid, SESSION, { owner: pid + 1 });
  expect(await find(pid)).toBe("");
});

test("metadata with no pid: nothing", async () => {
  const { pid } = await agent();
  mkdirSync(join(fallback, "sessions"), { recursive: true });
  writeFileSync(join(fallback, "sessions", `${pid}.json`), JSON.stringify({ sessionId: SESSION }));
  expect(await find(pid)).toBe("");
});

test("a session with no log yet is pending under ~/.claude, and nothing under another folder", async () => {
  const dir = folder();
  const plain = await agent();
  const custom = await agent({ CLAUDE_CONFIG_DIR: dir });
  session(fallback, plain.pid, SESSION, { log: false });
  session(dir, custom.pid, SESSION, { log: false });
  expect(await find(plain.pid)).toBe("pending");
  expect(await find(custom.pid)).toBe("");
});

test("under another folder the next look finds the log once it's there", async () => {
  const dir = folder();
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  session(dir, pid, SESSION, { log: false });
  expect(await find(pid)).toBe("");
  const log = session(dir, pid);
  expect(await find(pid)).toBe(log);
});

test("~/.claude named outright is pending as ~/.claude is", async () => {
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: fallback });
  session(fallback, pid, SESSION, { log: false });
  expect(await find(pid)).toBe("pending");
});

test("a process with its own session and no log stops FIND: a child's log is another conversation", async () => {
  const dir = folder();
  const parent = folder();
  const { pid, line } = await agent({ CLAUDE_CONFIG_DIR: parent }, WRAPPER, [WAIT, dir]);
  const child = Number(line);
  running.push(() => process.kill(child, 9));
  session(parent, pid, SESSION, { log: false });
  session(dir, child, OTHER);
  expect(await find(pid)).toBe("");
});

// Unreadable: Linux, a process that seals itself (root reads it anyway, so not as root); macOS, a system binary,
// whose environment shows empty. Either way ~/.claude holds a session for it that must not be taken.
const canSeal = process.platform === "linux" && process.getuid?.() !== 0;
test.skipIf(!canSeal && process.platform !== "darwin")("an environment that can't be read finds nothing, never ~/.claude", async () => {
  let pid;
  if (canSeal) ({ pid } = await agent({}, SEALED));
  else {
    const p = Bun.spawn(["/bin/sleep", "120"], { env: environment({}) });
    running.push(() => p.kill(9));
    pid = p.pid;
  }
  session(fallback, pid);
  expect(await find(pid)).toBe("");
});

test("a folder that holds nothing for it never falls back to ~/.claude", async () => {
  const dir = folder();
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  session(fallback, pid);
  expect(await find(pid)).toBe("");
});

test("a log only another folder holds isn't taken", async () => {
  const dir = folder();
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  session(dir, pid, SESSION, { log: false });
  session(fallback, pid, SESSION);
  expect(await find(pid)).toBe("");
});

test("the caller's own CLAUDE_CONFIG_DIR says nothing about the agent", async () => {
  const dir = folder();
  const { pid } = await agent();
  const log = session(fallback, pid);
  session(dir, pid, OTHER);
  expect(await find(pid, { CLAUDE_CONFIG_DIR: dir })).toBe(log);
});

test("each candidate is read for itself: a child's folder finds the child's session", async () => {
  const dir = folder();
  const { pid, line } = await agent({}, WRAPPER, [WAIT, dir]);
  const child = Number(line);
  running.push(() => process.kill(child, 9));
  const log = session(dir, child);
  expect(await find(pid)).toBe(log);
});

test("a value that isn't an exact absolute path finds nothing, never ~/.claude", async () => {
  for (const value of ["", "relative/folder", `${folder()}\nmore`]) {
    const { pid } = await agent({ CLAUDE_CONFIG_DIR: value });
    session(fallback, pid);
    expect(await find(pid)).toBe("");
  }
});

// Chat reads a session under another folder; nothing continues it, as a restart or fork carries no CLAUDE_CONFIG_DIR.
const restart = (path) => argvFor({ agent: "claude" }, { agent: "claude", argv: [], session: sessionOf("claude", path) });

test("a session under ~/.claude can be continued", async () => {
  const { pid } = await agent();
  session(fallback, pid);
  const path = await find(pid);
  expect(sessionOf("claude", path)).toBe(SESSION);
  expect(restart(path).resume).toBe(true);
  expect(inOtherFolder("claude", path)).toBe(false);
});

test("a session under another folder is found and never continued", async () => {
  const dir = folder();
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  const log = session(dir, pid);
  const path = await find(pid);
  expect(path).toBe(log);
  expect(sessionOf("claude", path)).toBe(null);
  expect(restart(path).resume).toBe(false);
  expect(inOtherFolder("claude", path)).toBe(true);
});

test("Codex and a chat with no log are as before", () => {
  const rollout = "/x/rollout-2026-01-01-aaaaaaaa-0000-4000-8000-000000000001.jsonl";
  expect(sessionOf("codex", rollout)).toBe(SESSION);
  expect(inOtherFolder("codex", rollout)).toBe(false);
  expect(sessionOf("claude", null)).toBe(null);
  expect(inOtherFolder("claude", null)).toBe(false);
});

test("the window's picker refuses before it restarts or switches anything", () => {
  const main = readFileSync(join(import.meta.dir, "..", "mods", "chat", "main.js"), "utf8");
  const pick = main.slice(main.indexOf("  applyPick(pick, cx) {"));
  expect(pick.indexOf("agent.inOtherFolder(this.kind, this.path)")).toBeGreaterThan(-1);
  expect(pick.indexOf("agent.inOtherFolder(this.kind, this.path)")).toBeLessThan(pick.indexOf("this.switchTask(pick, cx)"));
  expect(pick.indexOf("agent.inOtherFolder(this.kind, this.path)")).toBeLessThan(pick.indexOf("agent.restart(t, built, mine)"));
});

// What FOLDER prints for a process: its folder as what would start that agent again needs it.
async function folderOf(pid) {
  const p = Bun.spawn(["sh", "-c", LOG.FOLDER, "folder", String(pid)], { env: environment({}), stdout: "pipe", stderr: "ignore" });
  const out = await new Response(p.stdout).text();
  await p.exited;
  return out.trim().split("\n").pop();
}

// A process whose environment can't be read (the test above's two ways), or null where there's no way here.
async function sealed() {
  if (canSeal) return (await agent({}, SEALED)).pid;
  if (process.platform !== "darwin") return null;
  const p = Bun.spawn(["/bin/sleep", "120"], { env: environment({}) });
  running.push(() => p.kill(9));
  return p.pid;
}

test("FOLDER answers from the process, with no session or log: ~/.claude, another folder, or nothing", async () => {
  const dir = folder();
  expect(await folderOf((await agent()).pid)).toBe("default");
  expect(await folderOf((await agent({ CLAUDE_CONFIG_DIR: fallback })).pid)).toBe("default");
  expect(await folderOf((await agent({ CLAUDE_CONFIG_DIR: dir })).pid)).toBe("other");
  expect(await folderOf((await agent({ CLAUDE_CONFIG_DIR: join(home, "elsewhere", ".claude") })).pid)).toBe("");
  expect(await folderOf((await agent({ CLAUDE_CONFIG_DIR: "relative/folder" })).pid)).toBe("");
  const pid = await sealed();
  if (pid) expect(await folderOf(pid)).toBe("");
});

test("FOLDER follows the agent: a child with its own session under another folder, or one with none yet", async () => {
  const dir = folder();
  const { pid, line } = await agent({}, WRAPPER, [WAIT, dir]);
  const child = Number(line);
  running.push(() => process.kill(child, 9));
  expect(await folderOf(pid)).toBe("other");
  session(dir, child, SESSION, { log: false });
  expect(await folderOf(pid)).toBe("other");
});

test("FOLDER stops at the process with its own session: a child under another folder is another agent", async () => {
  const dir = folder();
  const { pid, line } = await agent({}, WRAPPER, [WAIT, dir]);
  const child = Number(line);
  running.push(() => process.kill(child, 9));
  session(fallback, pid);
  session(dir, child, OTHER);
  expect(await folderOf(pid)).toBe("default");
});

test("FIND's arguments and output are as they were beside FOLDER", async () => {
  const dir = folder();
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  session(dir, pid, SESSION, { log: false });
  expect(await find(pid)).toBe("");
  expect(await folderOf(pid)).toBe("other");
});

// What the service would run, as stand-ins, each saying it was called: its restart's herdr-task and herdr-app, hc for
// another machine's record, and the bash that would run restart.sh. A child's PATH is this folder alone.
// herdr-task's `provider show` answers with `route` (A2: lost-session recovery asks it first; Personal by default).
function standIns(record = null, route = "personal") {
  const bin = folder(), called = join(bin, "called");
  mkdirSync(bin);
  const tool = (name, out) => {
    writeFileSync(join(bin, name), `#!/bin/sh\necho "${name} $1" >> "${called}"\necho '${out}'\n`);
    chmodSync(join(bin, name), 0o755);
  };
  tool("herdr-task", JSON.stringify({ terminal: "t9", route }));
  tool("herdr-app", '{"terminal":"t9"}');
  tool("hc", JSON.stringify(record));
  tool("bash", "t9");
  return { bin, called: () => (existsSync(called) ? readFileSync(called, "utf8").trim().split("\n") : []) };
}

// A HERDR_APP_HOME with a restart.sh, which only the stand-in bash ever gets.
function appWithRestart() {
  const app = folder(), script = join(app, "mods", "coordinator", "restart.sh");
  mkdirSync(join(app, "mods", "coordinator"), { recursive: true });
  writeFileSync(script, "exit 1\n");
  return app;
}

// A service module in a process of its own, as Bun finds a program through the PATH its process started with. Nothing
// real is in reach, were a guard to go: only the stand-ins on PATH, this test's own HOME and HERDR_APP_HOME, and an
// address no terminal has. The core's machine.exec is a stand-in too: it runs what it's given on this machine, with
// this test's HOME, and only the scripts under test get real tools (sh, tr, awk), for reading a process of this test's.
const SERVICE = `
const [tools, shell] = JSON.parse(process.argv[3]);
const input = JSON.parse(process.argv[4]);
const asked = [];
const call = async (method, { argv, on }) => {
  if (method !== "machine.exec") throw new Error(method);
  asked.push(on ?? null);
  const p = Bun.spawn([shell, ...argv.slice(1)], { env: { PATH: tools, HOME: process.env.HOME }, stdout: "pipe", stderr: "ignore" });
  const out = await new Response(p.stdout).text();
  return { code: await p.exited, stdout: Buffer.from(out).toString("base64"), stderr: "" };
};
const finish = async (out) => { await Bun.write(Bun.stdout, JSON.stringify({ ...out, asked }) + "\\n"); process.exit(0); };
`;
let scripts = 0;
async function service(bin, code, target, input, app = join(home, "no-app")) {
  const script = join(bin, `child-${scripts++}.mjs`);
  writeFileSync(script, SERVICE + code);
  const p = Bun.spawn([process.execPath, script, join(import.meta.dir, "..", "service", target), JSON.stringify([process.env.PATH, Bun.which("sh")]), JSON.stringify(input)], {
    cwd: home, env: { PATH: bin, HOME: home, HERDR_APP_HOME: app, SHEPHERDR_DATA: join(home, "no-data") }, stdout: "pipe", stderr: "pipe" });
  const [out, err] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text()]);
  await p.exited;
  if (!out.trim()) throw new Error(err);
  return JSON.parse(out);
}

const RESTART = `
const { Agents } = await import(process.argv[2]);
const terminals = new Map([[input.addr, input.record]]);
await finish(await new Agents({ terminals, call }).restart(input.addr, input.path ? { path: input.path } : null, { kind: "claude" })
  .then((terminal) => ({ terminal }), (e) => ({ error: e.message })));
`;
const ADDR = "no-such-terminal";
const shellRecord = (labels) => ({ state: "live", argv: ["claude"], cwd: "/work", foreground: { argv: ["claude"], cwd: "/work" }, labels });
const agentRecord = (pid, labels = {}, name = "claude") => ({ state: "live", argv: [name], cwd: "/work", foreground: { name, pid, argv: [name], cwd: "/work" }, labels });
const webRestart = (bin, record, path = null, addr = ADDR) => service(bin, RESTART, "agents.ts", { addr, record, path });

test("the web's restart refuses an agent under another folder, and nothing runs", async () => {
  const { bin, called } = standIns(), log = join(folder(), "projects", "-work", `${SESSION}.jsonl`);
  for (const labels of [{ "herdr.task": "list#1" }, {}]) {
    expect((await webRestart(bin, shellRecord(labels), log)).error).toBe(OTHER_FOLDER);
    expect(called()).toEqual([]);
  }
}, 20000);

test("the web's restart still restarts an agent under ~/.claude", async () => {
  const { bin, called } = standIns(), log = join(fallback, "projects", "-work", `${SESSION}.jsonl`);
  expect((await webRestart(bin, shellRecord({ "herdr.task": "list#1" }), log)).terminal).toBe("t9");
  expect(called()).toEqual(["herdr-task switch", "herdr-app do"]);
}, 20000);

test("no reader: the agent's own process refuses a custom folder, with or without a log, and nothing runs", async () => {
  const { bin, called } = standIns(), dir = folder();
  const fresh = await agent({ CLAUDE_CONFIG_DIR: dir }), logged = await agent({ CLAUDE_CONFIG_DIR: dir });
  session(dir, logged.pid);
  for (const pid of [fresh.pid, logged.pid]) for (const labels of [{ "herdr.task": "list#1" }, {}]) {
    expect((await webRestart(bin, agentRecord(pid, labels))).error).toBe(OTHER_FOLDER);
    expect(called()).toEqual([]);
  }
}, 30000);

test("no reader: a default agent still restarts", async () => {
  const { bin, called } = standIns();
  const { pid } = await agent();
  expect((await webRestart(bin, agentRecord(pid, { "herdr.task": "list#1" }))).terminal).toBe("t9");
  expect(called()).toEqual(["herdr-task switch", "herdr-app do"]);
}, 20000);

test.skipIf(!canSeal && process.platform !== "darwin")("an agent whose folder can't be read is refused, never taken for ~/.claude", async () => {
  const { bin, called } = standIns();
  const pid = await sealed();
  session(fallback, pid);
  const { error } = await webRestart(bin, agentRecord(pid, { "herdr.task": "list#1" }));
  expect(error).toBe(AG.UNREAD_FOLDER);
  expect(error).toBeTruthy();
  expect(called()).toEqual([]);
}, 20000);

test("a reader with no path yet decides nothing: the process does", async () => {
  const { bin, called } = standIns();
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: folder() });
  const out = await service(bin, RESTART.replace("input.path ? { path: input.path } : null", "{ path: null }"), "agents.ts", { addr: ADDR, record: agentRecord(pid) });
  expect(out.error).toBe(OTHER_FOLDER);
  expect(called()).toEqual([]);
}, 20000);

test("on another machine: asked there, through the record the list lacks, for custom and default alike", async () => {
  const addr = `elsewhere/${ADDR}`;
  const custom = await agent({ CLAUDE_CONFIG_DIR: folder() }), plain = await agent();
  const listed = { state: "live", status: { app: "claude-code" }, argv: ["claude"], cwd: "/work", labels: { "herdr.task": "list#1" } };
  const refused = standIns({ foreground: { name: "claude", pid: custom.pid } });
  const no = await webRestart(refused.bin, listed, null, addr);
  expect(no.error).toBe(OTHER_FOLDER);
  expect(no.asked).toEqual(["elsewhere"]);
  expect(refused.called()).toEqual(["hc get"]);
  const allowed = standIns({ foreground: { name: "claude", pid: plain.pid } });
  const yes = await webRestart(allowed.bin, listed, null, addr);
  expect(yes.terminal).toBe("t9");
  expect(yes.asked).toEqual(["elsewhere"]);
  expect(allowed.called()).toEqual(["hc get", "herdr-task switch", "herdr-app do"]);
}, 30000);

test("Codex asks nothing and restarts as before", async () => {
  const { bin, called } = standIns();
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: folder() });
  const out = await webRestart(bin, agentRecord(pid, { "herdr.task": "list#1" }, "codex"));
  expect(out.terminal).toBe("t9");
  expect(out.asked).toEqual([]);
  expect(called()).toEqual(["herdr-task switch", "herdr-app do"]);
}, 20000);

// Lost-session recovery as the service runs it. There is no agent to ask: it has gone. What remains is what started it
// (its argv, which freshArgv drops any assignment from) and, when the terminal lives, the shell the new agent inherits.
const LOST = `
const { AgentWatch } = await import(process.argv[2]);
const sent = [];
const hub = { terminals: new Map([[input.addr, input.record]]), call, send: async (a, line) => { sent.push(line); return { code: 0 }; } };
const hc = async (args) => ({ code: 0, stdout: args[0] === "get" ? JSON.stringify(input.record) : "No conversation found with session ID: x" });
const watch = new AgentWatch(hub, hc, { watched: () => [], windowCards: () => ({}), windowLost: () => ({}), changed() {} });
await watch.checkLost({ addr: input.addr });
await finish({ sent, note: watch.notes.get(input.addr)?.text ?? null });
`;
const resumed = ["claude", "--resume", SESSION];
const atShell = (pid, argv = resumed) => ({ address: ADDR, state: "live", argv, cwd: "/work", foreground: { name: "zsh", pid, argv: ["zsh"], cwd: "/work" }, labels: {} });
const ended = (argv = resumed) => ({ address: ADDR, state: "finished", exit_code: 1, argv, cwd: "/work", labels: { "herdr.chat": "p1" } });
const webLost = (bin, record, app) => service(bin, LOST, "watch.ts", { addr: ADDR, record }, app);
const named = () => ["/usr/bin/env", `CLAUDE_CONFIG_DIR=${folder()}`, ...resumed];

// Each case waits the service's 20 s for the window, so they run side by side.
test("lost-session recovery refuses a custom folder: nothing typed, nothing started", async () => {
  const app = appWithRestart(), [a, b, c] = [standIns(), standIns(), standIns()];
  const plain = await agent(), custom = await agent({ CLAUDE_CONFIG_DIR: folder() });
  const [launched, inherited, gone] = await Promise.all([webLost(a.bin, atShell(plain.pid, named()), app), webLost(b.bin, atShell(custom.pid), app), webLost(c.bin, ended(named()), app)]);
  for (const out of [launched, inherited, gone]) {
    expect(out.sent).toEqual([]);
    expect(out.note).toContain(OTHER_FOLDER);
  }
  for (const s of [a, b, c]) expect(s.called()).toEqual([]);
}, 60000);

// L2: the service types nothing itself. At its shell herdr-task's launch owner brings it back (`launch revive TERMINAL
// --lost`, the tick's revival's own owner, so it comes back once), and an ended one goes to restart.sh, whose start the
// same owner plans; neither asks the route first, as the owner plans the binding and refuses what it can't carry.
function owner(bin, out, code = 0) {
  const called = join(bin, "called");
  writeFileSync(join(bin, "herdr-task"), `#!/bin/sh\necho "herdr-task $*" >> "${called}"\necho '${out}'\nexit ${code}\n`);
  chmodSync(join(bin, "herdr-task"), 0o755);
}

test("lost-session recovery goes through herdr-task's launch owner, never typed by the service", async () => {
  const app = appWithRestart(), [a, b] = [standIns(), standIns()];
  owner(a.bin, JSON.stringify({ how: "fresh", missing_history: true }));
  const plain = await agent();
  const [shell, gone] = await Promise.all([webLost(a.bin, atShell(plain.pid), app), webLost(b.bin, ended(), app)]);
  for (const out of [shell, gone]) expect(out.sent).toEqual([]);
  expect(a.called()).toEqual([`herdr-task launch revive ${ADDR} --lost --json`]);
  expect(b.called()).toEqual(["bash " + join(app, "mods", "coordinator", "restart.sh")]);
  for (const out of [shell, gone]) expect(out.note).not.toContain("didn't start");
}, 60000);

test("lost-session recovery says the owner's refusal, and one already brought back, with nothing typed", async () => {
  const app = appWithRestart(), [a, b] = [standIns(), standIns()];
  owner(a.bin, JSON.stringify({ error: "Its recorded provider binding can't be found." }), 1);
  owner(b.bin, JSON.stringify({ how: "none" }));
  const plain = await agent();
  const [refused, handled] = await Promise.all([webLost(a.bin, atShell(plain.pid), app), webLost(b.bin, atShell(plain.pid), app)]);
  for (const out of [refused, handled]) expect(out.sent).toEqual([]);
  expect(refused.note).toContain("Its recorded provider binding can't be found.");
  expect(handled.note).toContain("brought back already");
}, 60000);

// macOS shows no environment for its own /bin/zsh, so refusing here would end recovery for default agents there. No
// folder can be lost: what's typed inherits this very shell, as the agent that left did.
test.skipIf(!canSeal && process.platform !== "darwin")("a shell that can't be read keeps recovering: the new agent inherits it", async () => {
  const app = appWithRestart(), { bin, called } = standIns();
  const out = await webLost(bin, atShell(await sealed()), app);
  expect(out.sent).toEqual([]);
  expect(called()).toEqual(["herdr-task launch"]);
}, 60000);

test("the rule itself: Codex is never asked, and an assignment counts wherever it stands before the agent", async () => {
  const never = () => { throw new Error("asked"); };
  expect(await AG.restartRefusal("codex", 1, never)).toBe(null);
  expect(await AG.lostRefusal("codex", { state: "live", argv: named(), foreground: { pid: 1 } }, never)).toBe(null);
  expect(await AG.lostRefusal("claude", { state: "finished", argv: ["env", "CLAUDE_CONFIG_DIR=/p/claude", "claude", "-c"] }, never)).toBe(OTHER_FOLDER);
  expect(await AG.lostRefusal("claude", { state: "finished", argv: resumed }, never)).toBe(null);
  expect(await AG.lostRefusal("claude", { state: "finished", argv: resumed }, never, join(folder(), "projects", "-w", `${SESSION}.jsonl`))).toBe(OTHER_FOLDER);
  expect(await AG.restartRefusal("claude", null, never)).toBe(AG.UNREAD_FOLDER);
  expect(await AG.restartRefusal("claude", 1, async () => "\n")).toBe(AG.UNREAD_FOLDER);
  expect(await AG.restartRefusal("claude", 1, async () => "default\n")).toBe(null);
});

const FORK = `
const { act } = await import(process.argv[2]);
const hub = { terminals: new Map([[input.addr, input.record]]), call };
await finish(await act(hub, { type: "fork", chat: "chat" }, { addrOf: () => input.addr, reader: () => ({ path: input.path }) })
  .then((result) => ({ result }), (e) => ({ error: e.message })));
`;
const webFork = (bin, path) => service(bin, FORK, "actions.ts", { addr: ADDR, record: agentRecord(1), path });

test("the web's fork says why: another folder, or no session; a default session still forks", async () => {
  const { bin, called } = standIns();
  expect((await webFork(bin, join(folder(), "projects", "-work", `${SESSION}.jsonl`))).error).toBe(OTHER_FOLDER);
  expect((await webFork(bin, null)).error).toBe("This conversation has no saved session to fork.");
  expect(called()).toEqual([]);
  expect((await webFork(bin, join(fallback, "projects", "-work", `${SESSION}.jsonl`))).result).toEqual({ ok: true });
  // herdr-task's launch owner admits it first (L2), then the window makes the tab
  expect(called()).toEqual(["herdr-task launch", "herdr-app do"]);
}, 30000);

test("the web's fork asks the launch owner with its own argv, and its refusal makes no tab (L2)", async () => {
  const { bin, called } = standIns();
  owner(bin, JSON.stringify({ admitted: true, route: "personal" }));
  expect((await webFork(bin, join(fallback, "projects", "-work", `${SESSION}.jsonl`))).result).toEqual({ ok: true });
  expect(called()[0]).toBe(`herdr-task launch run --role agent --space unplaced --slot fork --replaces ${ADDR} --argv ["claude","--resume","${SESSION}","--fork-session"] --check --json`);
  const refused = standIns();
  owner(refused.bin, JSON.stringify({ error: "Its conversation is recorded on Azure Foundry." }), 1);
  expect((await webFork(refused.bin, join(fallback, "projects", "-work", `${SESSION}.jsonl`))).error).toBe("Its conversation is recorded on Azure Foundry.");
  expect(refused.called()).toEqual([`herdr-task launch run --role agent --space unplaced --slot fork --replaces ${ADDR} --argv ["claude","--resume","${SESSION}","--fork-session"] --check --json`]);
}, 30000);

// main.js runs only inside the window, so these read its order, as the picker's check above does. The rule they call is
// the one the service's tests above run.
const windowSource = () => readFileSync(join(import.meta.dir, "..", "mods", "chat", "main.js"), "utf8");
const method = (main, head) => main.slice(main.indexOf(head), main.indexOf("\n  }\n", main.indexOf(head)));

test("the window asks the process before it restarts or switches anything", () => {
  const main = windowSource();
  const pick = method(main, "  applyPick(pick, cx) {"), task = method(main, "  switchTask(pick, cx) {");
  expect(pick.indexOf("agent.restartRefusal(")).toBeGreaterThan(-1);
  expect(pick.indexOf("agent.restartRefusal(")).toBeLessThan(pick.indexOf("agent.restart(t, built, mine)"));
  expect(task.indexOf("agent.restartRefusal(")).toBeGreaterThan(-1);
  expect(task.indexOf("agent.restartRefusal(")).toBeLessThan(task.indexOf("mods/tasks/bin/herdr-task"));
});

test("the window's recovery asks before it types into a shell or restarts", () => {
  const lost = method(windowSource(), "  async lostSession(t, kind, fresh, cx) {");
  expect(lost.indexOf("agent.lostRefusal(")).toBeGreaterThan(-1);
  // At its shell the launch owner types it (L2), never the window itself.
  expect(lost.indexOf('hc(["send"')).toBe(-1);
  expect(lost.indexOf('"launch", "revive", term, "--lost"')).toBeGreaterThan(-1);
  expect(lost.indexOf("agent.lostRefusal(")).toBeLessThan(lost.indexOf('"launch", "revive", term, "--lost"'));
  expect(lost.indexOf("agent.lostRefusal(")).toBeLessThan(lost.indexOf("agent.restart(t,"));
});

test("the window's fork says another folder is why, where it is", () => {
  const fork = method(windowSource(), "  fork(cx) {");
  expect(fork.indexOf("agent.OTHER_FOLDER")).toBeGreaterThan(-1);
  expect(fork.indexOf("agent.inOtherFolder(this.kind, this.path)")).toBeLessThan(fork.indexOf("agent.OTHER_FOLDER"));
  expect(fork.indexOf("This conversation has no saved session.")).toBeGreaterThan(-1);
});

test("another folder called .claude finds nothing, as it would pass for ~/.claude", async () => {
  const dir = join(home, "elsewhere", ".claude");
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  session(dir, pid);
  expect(await find(pid)).toBe("");
});

test("~/.claude named outright is ~/.claude, with or without its last slash", async () => {
  for (const value of [fallback, `${fallback}/`]) {
    const { pid } = await agent({ CLAUDE_CONFIG_DIR: value });
    const log = session(fallback, pid);
    expect(await find(pid)).toBe(log);
    expect(sessionOf("claude", log)).toBe(SESSION);
  }
});

test("only the variable itself counts: not another's value", async () => {
  const decoy = `CLAUDE_CONFIG_DIR=${folder()}`;
  const { pid } = await agent({ NOTES: `x\n${decoy}`, ALSO: decoy });
  const log = session(fallback, pid);
  expect(await find(pid)).toBe(log);
});

// Linux reads the environment apart from argv. macOS can't tell an argument from a moved environment, so it refuses.
test("an argument shaped like the variable: not read on Linux, refused on macOS, never another folder", async () => {
  const dir = folder();
  const { pid } = await agent({}, WAIT, [`CLAUDE_CONFIG_DIR=${dir}`]);
  session(dir, pid, OTHER);
  const log = session(fallback, pid);
  expect(await find(pid)).toBe(process.platform === "darwin" ? "" : log);
});

test("a folder's name is taken literally, whatever a shell or printf would make of it", async () => {
  const dir = join(home, ODD);
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  const log = session(dir, pid);
  expect(await find(pid)).toBe(log);
});

test("a process that has gone finds nothing", async () => {
  const p = Bun.spawn(["python3", "-c", WAIT], { env: environment({}), stdout: "pipe", stderr: "ignore" });
  await firstLine(p);
  p.kill(9);
  await p.exited;
  session(fallback, p.pid);
  expect(await find(p.pid)).toBe("");
});

// Node's process.title rewrites argv in place, which is what macOS reads the environment past. A short one zero-fills
// the rest, and the environment is still found. One that fills it leaves the count landing beyond the variable when it
// comes first, which refuses: set must never read as unset.
const TITLED = `process.title = process.argv[1] === "fill" ? "z".repeat(4000) : "t"; console.log("ready"); setTimeout(() => {}, 120000);`;
test.skipIf(!Bun.which("node"))("a process that set its title never reads as unset", async () => {
  for (const title of ["short", "fill"]) {
    const dir = folder();
    const p = Bun.spawn(["node", "-e", TITLED, title], { env: { CLAUDE_CONFIG_DIR: dir, ...environment({}) }, stdout: "pipe", stderr: "ignore" });
    running.push(() => p.kill(9));
    await firstLine(p);
    const log = session(dir, p.pid);
    session(fallback, p.pid, OTHER);
    expect(await find(p.pid)).toBe(process.platform === "darwin" && title === "fill" ? "" : log);
  }
});

test.skipIf(!Bun.which("node"))("a process that set a short title and has no variable is under ~/.claude", async () => {
  const p = Bun.spawn(["node", "-e", TITLED, "short"], { env: environment({}), stdout: "pipe", stderr: "ignore" });
  running.push(() => p.kill(9));
  await firstLine(p);
  const log = session(fallback, p.pid);
  expect(await find(p.pid)).toBe(log);
});
