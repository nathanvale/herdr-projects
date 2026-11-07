import { afterAll, afterEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { FIND } from "./chat-log.js";

// FIND as its callers run it (sh, on the agent's machine) against real processes in throwaway folders. Each agent
// here is a python3 that waits: on macOS a system binary's environment reads as empty, so it wouldn't do. Linux runs
// these on CI; on macOS they take FIND's other reader, and CI never does.
const SESSION = "aaaaaaaa-0000-4000-8000-000000000001";
const OTHER = "bbbbbbbb-0000-4000-8000-000000000002";
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

test("only the variable itself counts: not another's value, and not an argument", async () => {
  const decoy = `CLAUDE_CONFIG_DIR=${folder()}`;
  const { pid } = await agent({ NOTES: `x\n${decoy}`, ALSO: decoy }, WAIT, [decoy]);
  const log = session(fallback, pid);
  expect(await find(pid)).toBe(log);
});
