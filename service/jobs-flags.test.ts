import { expect, test } from "bun:test";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// A chat open on a web page keeps its question hook's flag (data/chat-asks/open/<terminal>) fresh whether or not the
// service runs the background work (service/jobs.ts). Each case is service/jobs.ts in a process of its own, as Bun finds
// a program through the PATH its process started with: that PATH holds only stand-ins for herdr-task and herdr-secret,
// which note each call, and HOME and HERDR_APP_HOME are throwaway folders. herdr-core is a stand-in hub in the child.
// No agent, model, tick, scheduler or vault is reached.

const root = mkdtempSync(join(tmpdir(), "shep-jobs-flags-"));
let made = 0;
const folder = () => { const f = join(root, String(made++)); mkdirSync(f, { recursive: true }); return f; };

function standIns() {
  const bin = folder(), called = join(bin, "called");
  for (const name of ["herdr-task", "herdr-secret"]) {
    writeFileSync(join(bin, name), `#!/bin/sh\necho "${name} $*" >> "${called}"\n`);
    chmodSync(join(bin, name), 0o755);
  }
  return { bin, called: () => (existsSync(called) ? readFileSync(called, "utf8").trim().split("\n") : []) };
}

// The child's own pieces: a hub as service/hub.ts shows itself (terminals, up, on, call; a call made while herdr-core
// is away waits until it's back, as Hub.core() does), the flag's age, and the result as its last line.
const CHILD = `
import { statSync, utimesSync } from "node:fs";
import { join } from "node:path";
const { Jobs } = await import(process.argv[2]);
const input = JSON.parse(process.argv[3]);
const OPEN = join(process.env.HERDR_APP_HOME, "data", "chat-asks", "open");
const errors = [];
process.on("uncaughtException", (e) => errors.push(String(e)));
process.on("unhandledRejection", (e) => errors.push(String(e)));
const listeners = new Set();
let back = null;
const sent = [];
const hub = {
  up: true,
  terminals: new Map(input.terminals.map((t) => [t.address, t])),
  on(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  emit(e) { for (const fn of listeners) fn(e); },
  async call(method, params) {
    if (!this.up) await new Promise((r) => (back = r));
    sent.push({ method, on: params.on ?? null, argv: params.argv ?? null });
    if (input.callsFail) throw new Error("no answer");
    return { code: 0, stdout: "" };
  },
  down() { this.up = false; this.emit({ type: "reset" }); },
  again(terminals) { this.terminals = new Map(terminals.map((t) => [t.address, t])); this.up = true; this.emit({ type: "reset" }); back?.(); back = null; },
};
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
// seconds since the flag was touched, or null for no flag
const age = (a) => { try { return Math.round((Date.now() - statSync(join(OPEN, a)).mtimeMs) / 1000); } catch { return null; } };
// a minute old, as a page gone long since (none there: nothing to age)
const stale = (...as) => { const old = new Date(Date.now() - 60_000); for (const a of as) try { utimesSync(join(OPEN, a), old, old); } catch {} };
const ROUND = 4600;   // one round of the flags (every 4 s) and a little
const jobs = new Jobs(hub, null);
let following = input.follow;
jobs.watched = () => following;
const out = {};
const finish = () => { console.log(JSON.stringify({ ...out, sent, errors })); process.exit(0); };
`;

async function child(code: string, input: unknown, env: Record<string, string>, app = folder()) {
  const { bin, called } = standIns(), home = folder();
  const script = join(bin, "child.mjs");
  writeFileSync(script, CHILD + code);
  const p = Bun.spawn([process.execPath, script, join(import.meta.dir, "jobs.ts"), JSON.stringify(input)], {
    cwd: home, env: { PATH: bin, HOME: home, HERDR_APP_HOME: app, SHEPHERDR_DATA: join(home, "data"), ...env }, stdout: "pipe", stderr: "pipe" });
  const [text, err] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text()]);
  await p.exited;
  const last = text.trim().split("\n").pop() ?? "";
  if (!last.startsWith("{")) throw new Error(err || text);
  return { ...JSON.parse(last), called: called() };
}

const claude = (address: string, state = "live") => ({ address, state, foreground: { name: "claude" }, labels: {} });
const flagArgv = (sent: any[]) => sent.filter((c) => c.method === "machine.exec" && String(c.argv?.[2]).includes("data/chat-asks/open"));

// An app home with a 3.0 Shepherdr layout: its window keeps the background work (windowLeavesIt() false).
function oldLayout() {
  const app = folder();
  mkdirSync(join(app, "mods", "tabs-tasks"), { recursive: true });
  mkdirSync(join(app, "data", "shepherdr"), { recursive: true });
  writeFileSync(join(app, "data", "shepherdr", "installed.json"), "{}");
  return app;
}

// Each case runs from the start, side by side, so the file takes one case's time.
const off = child(`
jobs.start();
hub.emit({ type: "labels", terminal: "vm/t3" });
await wait(ROUND);
out.first = age("t1");
stale("t1");
await wait(ROUND);
out.kept = age("t1");
following = [];
stale("t1");
const before = sent.length;
await wait(ROUND);
out.left = age("t1");
out.sentAfterLeaving = sent.length - before;
finish();
`, { terminals: [claude("t1"), { ...claude("vm/t2") }, { address: "vm/t3", state: "live", labels: { "herdr.secret.want": "w1", "herdr.role": "coordinator" } }], follow: ["t1", "vm/t2"] },
{ SHEPHERDR_JOBS: "off" });

const on = child(`
jobs.start();
hub.emit({ type: "labels", terminal: "vm/t3" });
await wait(ROUND);
out.first = age("t1");
stale("t1");
await wait(ROUND);
out.kept = age("t1");
finish();
`, { terminals: [claude("t1"), claude("vm/t2"), { address: "vm/t3", state: "live", labels: { "herdr.secret.want": "w1", "herdr.role": "coordinator" } }], follow: ["t1", "vm/t2"] },
{ SHEPHERDR_JOBS: "on" });

const reconnect = child(`
jobs.start();
await wait(ROUND);
out.first = [age("t1"), age("t4")];
hub.down();
stale("t1", "t4");
const before = sent.length;
await wait(ROUND);
out.whileAway = [age("t1"), age("t4")];
hub.again([input.terminals[0]]);
stale("t4");
await wait(ROUND);
out.after = [age("t1"), age("t4")];
out.goneSentAfter = sent.slice(before).filter((c) => c.on === "vm").length;
finish();
`, { terminals: [claude("t1"), claude("t4"), claude("vm/t5")], follow: ["t1", "t4", "vm/t5"] },
{ SHEPHERDR_JOBS: "off" });

// The flag folder's place taken by a file: every write fails until it's cleared.
const failing = (() => {
  const app = folder();
  mkdirSync(join(app, "data", "chat-asks"), { recursive: true });
  writeFileSync(join(app, "data", "chat-asks", "open"), "");
  return child(`
import { rmSync } from "node:fs";
jobs.start();
await wait(ROUND);
out.blocked = age("t1");
rmSync(OPEN);
await wait(ROUND);
out.cleared = age("t1");
finish();
`, { terminals: [claude("t1"), claude("vm/t2")], follow: ["t1", "vm/t2"], callsFail: true }, { SHEPHERDR_JOBS: "off" }, app);
})();

const kinds = child(`
jobs.start();
await wait(ROUND);
out.ages = Object.fromEntries(input.follow.map((a) => [a, age(a)]));
finish();
`, { terminals: [
  claude("t1"),
  { address: "t2", state: "live", status: { app: "claude-code" }, labels: {} },
  { address: "t3", state: "live", foreground: { name: "codex" }, status: { app: "codex" }, labels: {} },
  claude("t4", "finished"),
  { address: "t5", state: "live", foreground: { name: "zsh" }, labels: {} },
  { address: "vm/t6", state: "live", foreground: { name: "codex" }, labels: {} },
  claude("vm/t7", "finished"),
], follow: ["t1", "t2", "t3", "t4", "t5", "vm/t6", "vm/t7"] }, {}, oldLayout());

const T = 60_000;

test("background work off: a followed Claude chat's flag is made and kept fresh, here and on its own machine", async () => {
  const r = await off;
  expect(r.errors).toEqual([]);
  expect(r.first).not.toBeNull();
  expect(r.first).toBeLessThan(15);
  expect(r.kept).toBeLessThan(15);
  expect(flagArgv(r.sent).map((c: any) => [c.on, c.argv.at(-1)])).toContainEqual(["vm", "t2"]);
}, T);

test("background work off: no tick, scheduler, automation, remote tick or secret serving, and only the flag goes to another machine", async () => {
  const r = await off;
  expect(r.called).toEqual([]);
  expect(r.sent.length).toBeGreaterThan(0);
  expect(flagArgv(r.sent)).toEqual(r.sent);
}, T);

test("a page that stops following: its flag isn't touched again and goes stale", async () => {
  const r = await off;
  expect(r.left).toBeGreaterThanOrEqual(55);
  expect(r.sentAfterLeaving).toBe(0);
}, T);

test("background work on: as before, the tick and scheduler here and on the other machine, secrets served, and the flag kept", async () => {
  const r = await on;
  expect(r.errors).toEqual([]);
  expect(r.called).toContain("herdr-task tick --json");
  expect(r.called).toContain("herdr-task scheduler --ensure --json");
  expect(r.called).toContain("herdr-task --on vm tick --json");
  expect(r.called).toContain("herdr-task --on vm scheduler --ensure --json");
  expect(r.called).toContain("herdr-secret serve vm/t3");
  expect(r.first).toBeLessThan(15);
  expect(r.kept).toBeLessThan(15);
  expect(flagArgv(r.sent).map((c: any) => [c.on, c.argv.at(-1)])).toContainEqual(["vm", "t2"]);
}, T);

test("herdr-core away and back: nothing is touched while it's away, a terminal gone since isn't touched, the rest is", async () => {
  const r = await reconnect;
  expect(r.errors).toEqual([]);
  expect(r.first[0]).toBeLessThan(15);
  expect(r.first[1]).toBeLessThan(15);
  expect(r.whileAway[0]).toBeGreaterThanOrEqual(55);
  expect(r.whileAway[1]).toBeGreaterThanOrEqual(55);
  expect(r.after[0]).toBeLessThan(15);
  expect(r.after[1]).toBeGreaterThanOrEqual(55);
  expect(r.goneSentAfter).toBe(0);
  expect(r.called).toEqual([]);
}, T);

test("a flag that can't be written, here or on another machine, throws nothing, and the next round writes it", async () => {
  const r = await failing;
  expect(r.errors).toEqual([]);
  expect(r.blocked).toBeNull();
  expect(r.cleared).toBeLessThan(15);
  expect(flagArgv(r.sent).length).toBeGreaterThan(0);
  expect(r.called).toEqual([]);
}, T);

test("a window that keeps the background work: only a live Claude agent's chat is flagged, never another agent or a finished one", async () => {
  const r = await kinds;
  expect(r.errors).toEqual([]);
  expect(r.ages.t1).toBeLessThan(15);
  expect(r.ages.t2).toBeLessThan(15);
  for (const a of ["t3", "t4", "t5"]) expect(r.ages[a]).toBeNull();
  expect(r.sent).toEqual([]);
  expect(r.called).toEqual([]);
}, T);
