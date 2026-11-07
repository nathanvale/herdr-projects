import { afterAll, afterEach, expect, test } from "bun:test";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Agents } from "../service/agents.ts";
import { argvFor, inOtherFolder, OTHER_FOLDER, sessionOf } from "./agents.js";
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

test("a session with no log yet is pending, in either folder", async () => {
  const dir = folder();
  const plain = await agent();
  const custom = await agent({ CLAUDE_CONFIG_DIR: dir });
  session(fallback, plain.pid, SESSION, { log: false });
  session(dir, custom.pid, SESSION, { log: false });
  expect(await find(plain.pid)).toBe("pending");
  expect(await find(custom.pid)).toBe("pending");
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

test("a log only another folder holds isn't taken: its own session is pending", async () => {
  const dir = folder();
  const { pid } = await agent({ CLAUDE_CONFIG_DIR: dir });
  session(dir, pid, SESSION, { log: false });
  session(fallback, pid, SESSION);
  expect(await find(pid)).toBe("pending");
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

// What the service's restart() would run, as stand-ins first on PATH, each saying it was called.
function standIns() {
  const bin = folder(), called = join(bin, "called"), path = process.env.PATH;
  mkdirSync(bin);
  for (const name of ["herdr-task", "herdr-app"]) {
    writeFileSync(join(bin, name), `#!/bin/sh\necho "${name} $1" >> "${called}"\necho '{"terminal":"t9"}'\n`);
    chmodSync(join(bin, name), 0o755);
  }
  process.env.PATH = `${bin}:${path}`;
  running.push(() => { process.env.PATH = path; });
  return () => (existsSync(called) ? readFileSync(called, "utf8").trim().split("\n") : []);
}
const webRestart = (labels, path) => new Agents({ terminals: new Map([["t1", { state: "live", argv: ["claude"], cwd: "/work",
  foreground: { argv: ["claude"], cwd: "/work" }, labels }]]) }).restart("t1", { path }, { kind: "claude" });

test("the web's restart refuses an agent under another folder, and nothing runs", async () => {
  const called = standIns(), log = join(folder(), "projects", "-work", `${SESSION}.jsonl`);
  for (const labels of [{ "herdr.task": "list#1" }, {}]) {
    await expect(webRestart(labels, log)).rejects.toThrow(OTHER_FOLDER);
    expect(called()).toEqual([]);
  }
});

test("the web's restart still restarts an agent under ~/.claude", async () => {
  const called = standIns(), log = join(fallback, "projects", "-work", `${SESSION}.jsonl`);
  expect(await webRestart({ "herdr.task": "list#1" }, log)).toBe("t9");
  expect(called()).toEqual(["herdr-task switch", "herdr-app do"]);
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

// Node's process.title rewrites argv in place, which is what macOS reads the environment past: a title that fills it
// leaves the count landing beyond the variable when it comes first. Set must never read as unset.
const TITLED = `process.title = process.argv[1] === "fill" ? "z".repeat(4000) : "t"; console.log("ready"); setTimeout(() => {}, 120000);`;
test.skipIf(!Bun.which("node"))("a process that set its title never reads as unset", async () => {
  for (const title of ["short", "fill"]) {
    const dir = folder();
    const p = Bun.spawn(["node", "-e", TITLED, title], { env: { CLAUDE_CONFIG_DIR: dir, ...environment({}) }, stdout: "pipe", stderr: "ignore" });
    running.push(() => p.kill(9));
    await firstLine(p);
    const log = session(dir, p.pid);
    session(fallback, p.pid, OTHER);
    expect(await find(p.pid)).toBe(process.platform === "darwin" ? "" : log);
  }
});
