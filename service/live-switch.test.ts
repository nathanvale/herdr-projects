import { expect, test, beforeAll, afterAll, beforeEach } from "bun:test";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, appendFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// The model menu's switch in place (service/agents.ts change(), core/live-switch.js; PR 60 review #1 and #2) across the
// service's own home-file io: its reads and writes run as `sh` on the agent's machine, here this disk with a throwaway
// HOME (as herdr-core's machine.exec would there). The agent is a Codex stand-in: typing /fast into it saves its tier
// in ~/.codex/config.toml, as Codex does, and its screen is what the stand-in hc reads back. No agent, terminal or
// settings file of the person's is touched; the real CLIs' own saving is not proved here.
const APP = mkdtempSync(join(tmpdir(), "shep-live-switch-"));
const HOME_DIR = join(APP, "home"), BIN = join(APP, "bin"), SCREEN = join(APP, "screen");
const CONFIG = join(HOME_DIR, ".codex", "config.toml");
mkdirSync(HOME_DIR);
mkdirSync(BIN);
// hc: `read` gives the agent's screen; anything else (keys) does nothing
writeFileSync(join(BIN, "hc"), `#!/bin/sh\n[ "$1" = read ] && cat "${SCREEN}"\nexit 0\n`, { mode: 0o755 });

let Agents: typeof import("./agents.ts").Agents;
const was = process.env.SHEPHERDR_HC;
beforeAll(async () => {
  process.env.SHEPHERDR_HC = join(BIN, "hc");
  ({ Agents } = await import("./agents.ts"));
});
afterAll(() => {
  if (was === undefined) delete process.env.SHEPHERDR_HC; else process.env.SHEPHERDR_HC = was;
  rmSync(APP, { recursive: true, force: true });
});

let sent: string[] = [];
let afterSave: () => void = () => {};
// what the Claude Code agent's own process says of its config folder (core/chat-log.js FOLDER's words: "default" is
// ~/.claude, "other" another, nothing when it can't be read), and each machine.exec the service ran, by its first word
let folder = "default\n";
let ran: string[] = [];
beforeEach(() => {
  sent = [];
  afterSave = () => {};
  folder = "default\n";
  ran = [];
  writeFileSync(SCREEN, "› \n");
  rmSync(join(HOME_DIR, ".codex"), { recursive: true, force: true });
});

// herdr-core with this disk as the agent's machine; its terminal t9 runs Codex, t7 Claude Code, both idle. The folder
// question (its process and children's open files) is answered as the agent's machine would; the rest runs here.
const hub: any = {
  terminals: new Map([["t9", { address: "t9", state: "live", status: { state: "idle" }, labels: {}, argv: ["codex"],
    foreground: { pid: 4242, name: "codex", argv: ["codex"], cwd: HOME_DIR } }],
  ["t7", { address: "t7", state: "live", status: { state: "idle" }, labels: {}, argv: ["claude"],
    foreground: { pid: 4343, name: "claude", argv: ["claude"], cwd: HOME_DIR } }]]),
  async call(method: string, p: any) {
    if (method !== "machine.exec") throw new Error(method);
    ran.push(p.argv[3]);
    if (p.argv[3] === "folder") return { code: 0, stdout: Buffer.from(p.argv[4] === "4343" ? folder : "").toString("base64"), stderr: "" };
    const proc = Bun.spawn(p.argv, { env: { ...process.env, HOME: HOME_DIR }, stdout: "pipe", stderr: "pipe" });
    const [o, e] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text()]);
    return { code: await proc.exited, stdout: Buffer.from(o).toString("base64"), stderr: Buffer.from(e).toString("base64") };
  },
  // Codex: /fast saves its tier (making ~/.codex/config.toml when there's none) and says so. Claude Code: each command
  // is echoed and answered as taken (its default isn't saved here: nothing to put back)
  async send(addr: string, text: string) {
    sent.push(text);
    if (addr === "t7") {
      const said = text.startsWith("/model ") ? `Set model to ${text.slice(7)}` : text.startsWith("/effort ") ? `Set effort level to ${text.slice(8)}`
        : text === "/fast on" ? "Fast mode ON" : text === "/fast off" ? "Fast mode OFF" : "";
      appendFileSync(SCREEN, `› ${text}\n  ⎿ ${said}\n`);
      return { code: 0, stdout: "", stderr: "" };
    }
    if (text === "/fast") {
      mkdirSync(join(HOME_DIR, ".codex"), { recursive: true });
      const kept = (existsSync(CONFIG) ? readFileSync(CONFIG, "utf8") : "").split("\n").filter((l) => l && !/^service_tier\s*=/.test(l));
      writeFileSync(CONFIG, [...kept, 'service_tier = "fast"', ""].join("\n"));
      afterSave();
      appendFileSync(SCREEN, "• Service tier set to fast\n");
    }
    return { code: 0, stdout: "", stderr: "" };
  },
};
const fast = () => new Agents(hub).change("t9", null, { kind: "codex", speed: "fast" });

test("no config.toml before: the one Codex made loses the tier it saved, and the switch is made", async () => {
  expect(await fast()).toEqual({ live: true });
  expect(sent).toEqual(["/fast"]);
  expect(readFileSync(CONFIG, "utf8")).not.toContain("service_tier");
});

test("a config.toml there before gets its own tier back", async () => {
  mkdirSync(join(HOME_DIR, ".codex"));
  writeFileSync(CONFIG, 'approval_policy = "never"\nservice_tier = "flex"\n');
  expect(await fast()).toEqual({ live: true });
  expect(readFileSync(CONFIG, "utf8")).toBe('approval_policy = "never"\nservice_tier = "flex"\n');
});

test("a config.toml that can't be read: nothing is typed, and the switch says why", async () => {
  mkdirSync(CONFIG, { recursive: true }); // there, but cat can't read it, as root too
  await expect(fast()).rejects.toThrow("~/.codex/config.toml couldn't be read");
  expect(sent).toEqual([]);
});

// a file its owner can't write: root writes it anyway, so this needs the CI runner's ordinary user
test.skipIf(process.getuid?.() === 0)("a tier that couldn't be put back is no success: it says it switched and the default stayed", async () => {
  mkdirSync(join(HOME_DIR, ".codex"));
  writeFileSync(CONFIG, 'service_tier = "flex"\n');
  afterSave = () => chmodSync(CONFIG, 0o444);
  try {
    await expect(fast()).rejects.toThrow("It switched, but ~/.codex/config.toml couldn't be put back, so new sessions may start on this choice.");
    expect(sent).toEqual(["/fast"]);
    expect(readFileSync(CONFIG, "utf8")).toBe('service_tier = "fast"\n');
  } finally {
    if (existsSync(CONFIG)) chmodSync(CONFIG, 0o644);
  }
});

// PR 60 review #2: the switch asks the Claude Code agent's own process which config folder it runs on (folderRefusal),
// as restart() does. Another folder, or one that can't be read, can't be put back in place: it refuses before anything
// is typed or any settings file is read, and says why. Only its folder was asked.
const claudeFast = (a = new Agents(hub)) => a.change("t7", null, { kind: "claude", speed: "fast" });

test("a Claude Code agent on another config folder: nothing is typed or read, and the switch says why", async () => {
  folder = "other\n";
  await expect(claudeFast()).rejects.toThrow("It runs under its own Claude Code folder, which a restart can't carry yet.");
  expect(sent).toEqual([]);
  expect(ran.every((w) => w === "folder")).toBe(true);
  expect(ran.length).toBeGreaterThan(0);
});

test("a Claude Code agent whose config folder can't be read: nothing is typed or read, and the switch says why", async () => {
  folder = "";
  await expect(claudeFast()).rejects.toThrow("Its Claude Code folder can't be read, so a restart might start it on another.");
  expect(sent).toEqual([]);
  expect(ran.every((w) => w === "folder")).toBe(true);
  expect(ran.length).toBeGreaterThan(0);
});

test("a Claude Code agent on ~/.claude switches in place", async () => {
  await expect(claudeFast()).resolves.toEqual({ live: true });
  expect(ran[0]).toBe("folder");
  expect(sent).toContain("/fast on");
});

// PR 60 review #8: a switch that happened changes what the menu's defaults are; the same Agents' cached() reads them
// again, even when the default it saved couldn't be put back
test.skipIf(process.getuid?.() === 0)("after a switch whose default couldn't be put back, the defaults are read again", async () => {
  mkdirSync(join(HOME_DIR, ".codex"));
  writeFileSync(CONFIG, 'service_tier = "flex"\n');
  const a = new Agents(hub);
  const settled = async () => {
    for (let i = 0; i < 200; i++) {
      const v = a.cached("codex", null);
      if (v) return v;
      await Bun.sleep(10);
    }
    return null;
  };
  expect((await settled())?.fast).toBe(false);
  afterSave = () => chmodSync(CONFIG, 0o444);
  try {
    await expect(a.change("t9", null, { kind: "codex", speed: "fast" })).rejects.toThrow("It switched, but ~/.codex/config.toml couldn't be put back");
    expect(a.cached("codex", null)).toBeNull();
    expect((await settled())?.fast).toBe(true);
  } finally {
    if (existsSync(CONFIG)) chmodSync(CONFIG, 0o644);
  }
});
