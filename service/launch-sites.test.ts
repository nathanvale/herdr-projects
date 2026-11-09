import { expect, test, beforeAll, afterAll, beforeEach } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// The service's two Assistant start sites (L1): a web-only New space (spaces.ts newSpace) and a space's first message
// with no Assistant yet (actions.ts send to "p:<space>") start it through launch admission, `herdr-task launch run`,
// never with an hc run of their own, and a refusal's words reach the page. herdr-task and hc are stand-ins that record
// their words, given as SHEPHERDR_HERDR_TASK and SHEPHERDR_HC (Bun.spawn finds a bare name on the PATH the test
// process started with, so a PATH set here wouldn't reach it): no agent, terminal or settings file of the person's is
// touched. The owner itself
// (claims, revalidation, uncertainty) is proved across its own command line in test/test_launch_admission.py.
const APP = mkdtempSync(join(tmpdir(), "shep-launch-sites-"));
const BIN = join(APP, "bin"), TASK_CALLS = join(APP, "herdr-task.calls"), HC_CALLS = join(APP, "hc.calls"), REPLY = join(APP, "reply");
const HOME_DIR = join(APP, "home"), FOLDER = join(APP, "repo");
mkdirSync(BIN);
mkdirSync(join(HOME_DIR, ".config", "herdr-core", "templates"), { recursive: true });
mkdirSync(FOLDER);
// the assistant template, as the machine's sync puts it there
writeFileSync(join(HOME_DIR, ".config", "herdr-core", "templates", "assistant.md"), "---\nname: assistant\ncommand: claude\n---\nYou are the Assistant.\n");
// herdr-task: one JSON line of its words; its reply is REPLY's, its exit code REPLY.code's
writeFileSync(join(BIN, "herdr-task"), `#!/bin/sh\nprintf '%s\\n' "$*" >> "${TASK_CALLS}"\ncat "${REPLY}"\nexit "$(cat "${REPLY}.code" 2>/dev/null || echo 0)"\n`, { mode: 0o755 });
writeFileSync(join(BIN, "hc"), `#!/bin/sh\nprintf '%s\\n' "$*" >> "${HC_CALLS}"\nexit 1\n`, { mode: 0o755 });

let SP: typeof import("./spaces.ts");
let A: typeof import("./actions.ts");
const was = { app: process.env.HERDR_APP_HOME, task: process.env.SHEPHERDR_HERDR_TASK, hc: process.env.SHEPHERDR_HC };
beforeAll(async () => {
  process.env.HERDR_APP_HOME = APP; // no mods/spaces-chat: the service's own spaces, no window
  process.env.SHEPHERDR_HERDR_TASK = join(BIN, "herdr-task");
  process.env.SHEPHERDR_HC = join(BIN, "hc");
  SP = await import("./spaces.ts");
  A = await import("./actions.ts");
});
afterAll(() => {
  for (const [k, v] of [["HERDR_APP_HOME", was.app], ["SHEPHERDR_HERDR_TASK", was.task], ["SHEPHERDR_HC", was.hc]] as const) {
    if (v === undefined) delete process.env[k]; else process.env[k] = v;
  }
  rmSync(APP, { recursive: true, force: true });
});
beforeEach(() => {
  for (const p of [TASK_CALLS, HC_CALLS, `${REPLY}.code`]) if (existsSync(p)) rmSync(p);
  writeFileSync(REPLY, JSON.stringify({ address: "t7", launch: "6f1c2d3e-4a5b-4c6d-8e7f-001122334455", state: "confirmed" }));
});

// herdr-core with this disk as the machine: machine.exec runs the command here, with the throwaway HOME
const hub: any = {
  terminals: new Map(),
  async call(method: string, p: any) {
    if (method !== "machine.exec") throw new Error(method);
    const proc = Bun.spawn(p.argv, { env: { ...process.env, HOME: HOME_DIR }, stdout: "pipe", stderr: "pipe" });
    const [o, e] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text()]);
    return { code: await proc.exited, stdout: Buffer.from(o).toString("base64"), stderr: Buffer.from(e).toString("base64") };
  },
};
const store = () => { const d: Record<string, any> = {}; return { d, value: (k: string) => d[k], set: async (k: string, v: unknown) => { d[k] = v; } }; };
const read = (p: string) => (existsSync(p) ? readFileSync(p, "utf8").trim().split("\n").filter(Boolean) : []);
const compat = (folder: string): any => ({
  addrOf: () => null,
  spaceOf: (id: string) => (id === "sp1" ? { id: "sp1", name: "repo", folder, machine: null } : null),
  shared: { value: () => ({}) },
});

test("a web-only new space starts its Assistant through launch admission", async () => {
  const s = store();
  const place = await SP.newSpace(hub, { machine: null, path: FOLDER, store: s });
  const id = s.d.spaces[0].id;
  expect(place).toBe(id);
  const [call] = read(TASK_CALLS);
  expect(call.startsWith(`launch run --role coordinator --space ${id} --json -- --bg --keep --no-parent --cwd `)).toBe(true);
  expect(call).toContain(`--label herdr.role=coordinator --label herdr.coordinator.space=${id} --label herdr.space=${id} herdr-assistant-`);
  expect(read(HC_CALLS)).toEqual([]);
});

test("a space's first message starts its Assistant through launch admission", async () => {
  const r: any = await A.act(hub, { type: "send", chat: "p:sp1", text: "Plan the week" }, compat(FOLDER));
  expect(r).toMatchObject({ ok: true, started: true });
  const [call] = read(TASK_CALLS);
  expect(call.startsWith(`launch run --role coordinator --space sp1 --json -- --bg --json --no-parent --keep --cwd ${FOLDER} `)).toBe(true);
  expect(call).toContain("--label herdr.role=coordinator --label herdr.coordinator.space=sp1 --label herdr.space=sp1 herdr-assistant-");
  expect(call.endsWith(" Plan the week")).toBe(true);
  expect(read(HC_CALLS)).toEqual([]);
});

test("a refused first-message start says the owner's words and starts nothing", async () => {
  const why = "Provider is Azure Foundry here, but an Assistant's start can't carry a launch plan yet (pending: settings and selectors): it would start on the CLI's own sign-in. Nothing was started.";
  writeFileSync(REPLY, JSON.stringify({ error: why }));
  writeFileSync(`${REPLY}.code`, "1");
  await expect(A.act(hub, { type: "send", chat: "p:sp1", text: "Plan the week" }, compat(FOLDER))).rejects.toThrow(why);
  expect(read(TASK_CALLS)).toHaveLength(1);
  expect(read(HC_CALLS)).toEqual([]);
});
