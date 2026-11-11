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
beforeEach(() => {
  sent = [];
  afterSave = () => {};
  writeFileSync(SCREEN, "› \n");
  rmSync(join(HOME_DIR, ".codex"), { recursive: true, force: true });
});

// herdr-core with this disk as the agent's machine; its terminal t9 runs Codex, idle
const hub: any = {
  terminals: new Map([["t9", { address: "t9", state: "live", status: { state: "idle" }, labels: {}, argv: ["codex"],
    foreground: { pid: 4242, name: "codex", argv: ["codex"], cwd: HOME_DIR } }]]),
  async call(method: string, p: any) {
    if (method !== "machine.exec") throw new Error(method);
    const proc = Bun.spawn(p.argv, { env: { ...process.env, HOME: HOME_DIR }, stdout: "pipe", stderr: "pipe" });
    const [o, e] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text()]);
    return { code: await proc.exited, stdout: Buffer.from(o).toString("base64"), stderr: Buffer.from(e).toString("base64") };
  },
  // Codex: /fast saves its tier (making ~/.codex/config.toml when there's none) and says so
  async send(_addr: string, text: string) {
    sent.push(text);
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
