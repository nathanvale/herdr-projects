import { afterAll, expect, test } from "bun:test";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// A chat open on a web page keeps its question hook's flag (data/chat-asks/open/<terminal>) fresh whether or not the
// service runs the background work (service/jobs.ts). Each case is service/jobs.ts in a process of its own, as Bun finds
// a program through the PATH its process started with: that PATH holds only stand-ins for herdr-task and herdr-secret,
// which note each call, and HOME and HERDR_APP_HOME are throwaway folders. herdr-core is a stand-in hub in the child.
// No agent, model, tick, scheduler or vault is reached.

const root = mkdtempSync(join(tmpdir(), "shep-jobs-flags-"));
afterAll(() => rmSync(root, { recursive: true, force: true }));
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
// is away waits until it's back, as Hub.core() does, and is noted when it's made), the flag's age, waits that poll
// until a deadline, and the result as its last line.
const CHILD = `
import { readFileSync, statSync, utimesSync } from "node:fs";
import { dirname, join } from "node:path";
const { Jobs } = await import(process.argv[2]);
const input = JSON.parse(process.argv[3]);
const OPEN = join(process.env.HERDR_APP_HOME, "data", "chat-asks", "open");
const errors = [];
process.on("uncaughtException", (e) => errors.push(String(e)));
process.on("unhandledRejection", (e) => errors.push(String(e)));
const listeners = new Set();
let back = null;
const sent = [];
const record = (t) => [t.address, t];
const hub = {
  up: true,
  terminals: new Map(input.terminals.map(record)),
  on(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  emit(e) { for (const fn of listeners) fn(e); },
  async call(method, params) {
    sent.push({ method, on: params.on ?? null, argv: params.argv ?? null, away: !this.up });
    if (!this.up) await new Promise((r) => (back = r));
    if (input.callsFail) throw new Error("no answer");
    return { code: 0, stdout: "" };
  },
  down() { this.up = false; this.emit({ type: "reset" }); },
  again(terminals) { this.terminals = new Map(terminals.map(record)); this.up = true; this.emit({ type: "reset" }); back?.(); back = null; },
};
const wait = (ms) => new Promise((r) => setTimeout(r, Math.max(0, ms)));
// true once ok() is, polled until the deadline
const until = async (ok, ms = 12_000) => { const end = Date.now() + ms; while (Date.now() < end) { if (ok()) return true; await wait(100); } return Boolean(ok()); };
// seconds since the flag was touched, or null for no flag
const age = (a) => { try { return Math.round((Date.now() - statSync(join(OPEN, a)).mtimeMs) / 1000); } catch { return null; } };
const fresh = (a) => { const s = age(a); return s !== null && s < 15; };
// a minute old, as a page gone long since (none there: nothing to age)
const stale = (...as) => { const old = new Date(Date.now() - 60_000); for (const a of as) try { utimesSync(join(OPEN, a), old, old); } catch {} };
const sentTo = (id, from = 0) => sent.slice(from).filter((c) => c.argv?.at(-1) === id);
const called = () => { try { return readFileSync(join(dirname(process.argv[1]), "called"), "utf8").trim().split("\\n"); } catch { return []; } };
const ROUND = 5000;   // one round of the flags (every 4 s) and a second more: for what must not happen
const jobs = new Jobs(hub, null);
let following = input.follow;
jobs.watched = () => following;
const out = {};
const finish = () => { console.log(JSON.stringify({ ...out, sent, errors })); process.exit(0); };
`;

// A child that hasn't finished by then is killed, and its test fails with what it wrote.
async function child(code: string, input: unknown, env: Record<string, string>, app = folder()) {
  const { bin, called } = standIns(), home = folder();
  const script = join(bin, "child.mjs");
  writeFileSync(script, CHILD + code);
  const p = Bun.spawn([process.execPath, script, join(import.meta.dir, "jobs.ts"), JSON.stringify(input)], {
    cwd: home, env: { PATH: bin, HOME: home, HERDR_APP_HOME: app, SHEPHERDR_DATA: join(home, "data"), ...env }, stdout: "pipe", stderr: "pipe" });
  const timer = setTimeout(() => p.kill(), 50_000);
  try {
    const [text, err] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text()]);
    await p.exited;
    const last = text.trim().split("\n").pop() ?? "";
    if (!last.startsWith("{")) throw new Error(`child ended without a result (${p.signalCode ?? p.exitCode}): ${err || text}`);
    return { ...JSON.parse(last), called: called() };
  } finally {
    clearTimeout(timer);
    if (p.exitCode === null && p.signalCode === null) p.kill();
  }
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

// Each case runs from the start, side by side, so the file takes the longest case's time.
const off = child(`
jobs.start();
hub.emit({ type: "labels", terminal: "vm/t3" });
out.first = await until(() => fresh("t1") && sentTo("t2").length > 0);
stale("t1");
out.kept = await until(() => fresh("t1"));
following = [];
stale("t1");
const before = sent.length;
await wait(ROUND);
out.left = age("t1");
out.sentAfterLeaving = sent.length - before;
finish();
`, { terminals: [claude("t1"), claude("vm/t2"), { address: "vm/t3", state: "live", labels: { "herdr.secret.want": "w1", "herdr.role": "coordinator" } }], follow: ["t1", "vm/t2"] },
{ SHEPHERDR_JOBS: "off" });

const on = child(`
jobs.start();
hub.emit({ type: "labels", terminal: "vm/t3" });
out.first = await until(() => fresh("t1") && sentTo("t2").length > 0);
stale("t1");
out.kept = await until(() => fresh("t1"));
out.ticked = await until(() => called().length >= 5);
finish();
`, { terminals: [claude("t1"), claude("vm/t2"), { address: "vm/t3", state: "live", labels: { "herdr.secret.want": "w1", "herdr.role": "coordinator" } }], follow: ["t1", "vm/t2"] },
{ SHEPHERDR_JOBS: "on" });

// Away just after a touch on the other machine and for over three rounds, so its 8 s spacing can't hide one; back
// without t4 and vm/t8, gone meanwhile.
const reconnect = child(`
jobs.start();
out.first = await until(() => fresh("t1") && fresh("t4") && sentTo("t5").length > 0 && sentTo("t8").length > 0);
const awayAt = Date.now();
hub.down();
stale("t1", "t4");
out.localWhileAway = await until(() => fresh("t1") && fresh("t4"));
await wait(14_000 - (Date.now() - awayAt));
out.remoteWhileAway = sent.filter((c) => c.away).length;
const before = sent.length, backAt = Date.now();
hub.again([input.terminals[0], input.terminals[2]]);
stale("t4");
out.remoteBack = await until(() => sentTo("t5", before).length > 0);
await wait(ROUND - (Date.now() - backAt));
out.after = { t1: fresh("t1"), t4: age("t4"), t8: sentTo("t8", before).length };
finish();
`, { terminals: [claude("t1"), claude("t4"), claude("vm/t5"), claude("vm/t8")], follow: ["t1", "t4", "vm/t5", "vm/t8"] },
{ SHEPHERDR_JOBS: "off" });

// The flag folder's place taken by a file: every write fails until it's cleared.
const failing = (() => {
  const app = folder();
  mkdirSync(join(app, "data", "chat-asks"), { recursive: true });
  writeFileSync(join(app, "data", "chat-asks", "open"), "");
  return child(`
import { rmSync } from "node:fs";
jobs.start();
await until(() => sentTo("t2").length > 0);
await wait(ROUND);
out.blocked = age("t1");
rmSync(OPEN);
out.cleared = await until(() => fresh("t1"));
finish();
`, { terminals: [claude("t1"), claude("vm/t2")], follow: ["t1", "vm/t2"], callsFail: true }, { SHEPHERDR_JOBS: "off" }, app);
})();

const kinds = child(`
jobs.start();
out.flagged = await until(() => fresh("t1") && fresh("t2"));
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
  expect(r.first).toBe(true);
  expect(r.kept).toBe(true);
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
  expect(r.ticked).toBe(true);
  expect(r.called).toContain("herdr-task tick --json");
  expect(r.called).toContain("herdr-task scheduler --ensure --json");
  expect(r.called).toContain("herdr-task --on vm tick --json");
  expect(r.called).toContain("herdr-task --on vm scheduler --ensure --json");
  expect(r.called).toContain("herdr-secret serve vm/t3");
  expect(r.first).toBe(true);
  expect(r.kept).toBe(true);
  expect(flagArgv(r.sent).map((c: any) => [c.on, c.argv.at(-1)])).toContainEqual(["vm", "t2"]);
}, T);

test("herdr-core away: flags here stay fresh, none goes to another machine; back: that resumes, and nothing gone meanwhile is touched", async () => {
  const r = await reconnect;
  expect(r.errors).toEqual([]);
  expect(r.first).toBe(true);
  expect(r.localWhileAway).toBe(true);
  expect(r.remoteWhileAway).toBe(0);
  expect(r.remoteBack).toBe(true);
  expect(r.after.t1).toBe(true);
  expect(r.after.t4).toBeGreaterThanOrEqual(55);
  expect(r.after.t8).toBe(0);
  expect(r.called).toEqual([]);
}, T);

test("a flag that can't be written, here or on another machine, throws nothing, and the next round writes it", async () => {
  const r = await failing;
  expect(r.errors).toEqual([]);
  expect(r.blocked).toBeNull();
  expect(r.cleared).toBe(true);
  expect(flagArgv(r.sent).length).toBeGreaterThan(0);
  expect(r.called).toEqual([]);
}, T);

test("a window that keeps the background work: only a live Claude agent's chat is flagged, never another agent or a finished one", async () => {
  const r = await kinds;
  expect(r.errors).toEqual([]);
  expect(r.flagged).toBe(true);
  for (const a of ["t3", "t4", "t5"]) expect(r.ages[a]).toBeNull();
  expect(r.sent).toEqual([]);
  expect(r.called).toEqual([]);
}, T);
