// The service's new-start selectors (service/selections.ts, A2) against a stand-in herdr-task that records its words and
// answers from a reply file (SHEPHERDR_HERDR_TASK, as service/launch-sites.test.ts): no task list, settings file, agent
// or Azure is touched. They prove what the service asks herdr-task for, that a save carries the revision it was shown
// at, and what each CLI's list offers; herdr-task's own revision and save-only rules are proved across its command line
// in test/test_providers.py.
import { expect, test, beforeAll, afterAll, beforeEach } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { assistantChoices, menusFor, pickRevision, STALE_LIST, STALE_PICK, taskSelection, withoutUsedPick, withPick } from "./selections.ts";

const DIR = mkdtempSync(join(tmpdir(), "shep-selections-"));
const CALLS = join(DIR, "calls"), REPLY = join(DIR, "reply"), BIN = join(DIR, "herdr-task");
writeFileSync(BIN, `#!/bin/sh\nprintf '%s\\n' "$*" >> "${CALLS}"\ncat "${REPLY}"\nexit "$(cat "${REPLY}.code" 2>/dev/null || echo 0)"\n`, { mode: 0o755 });
const was = process.env.SHEPHERDR_HERDR_TASK;
beforeAll(() => { process.env.SHEPHERDR_HERDR_TASK = BIN; });
afterAll(() => { if (was === undefined) delete process.env.SHEPHERDR_HERDR_TASK; else process.env.SHEPHERDR_HERDR_TASK = was; rmSync(DIR, { recursive: true, force: true }); });
beforeEach(() => { for (const p of [CALLS, `${REPLY}.code`]) if (existsSync(p)) rmSync(p); });
const calls = () => (existsSync(CALLS) ? readFileSync(CALLS, "utf8").trim().split("\n") : []);

// What Settings' Refresh found, by level and CLI (Settings.discovery's shape): an Opus deployment and one unknown model.
const FOUND: Record<string, any> = {
  "all\0claude": { options: [{ value: "opus-deployment", label: "opus-deployment · claude-opus-5-5 (1)", model: "claude-opus-5-5" },
    { value: "custom-deployment", label: "custom-deployment · house-model (2)", model: "house-model" }], revision: "1" },
};
// Settings.discoveryFor's shape: the space's own list, or Everywhere's when read under the space's configuration (that
// judgement is proved against real Settings in service/settings.test.ts)
const settings: any = { discoveryFor: (space: string | null, kind: string) => FOUND[`${space ?? "all"}\0${kind}`] ?? FOUND[`all\0${kind}`] ?? { options: [], revision: "" } };
const SHOWN = { ok: true, id: 3, locked: false, route: "azure-foundry", revision: "abcd1234abcd1234",
  selection: { agent: "claude", deployment: "saved-deployment", effort: null },
  clis: { claude: { routing: "Azure Foundry example with Entra ID", deployment: "claude-default", revision: "r1", problem: null },
    codex: { routing: "Azure Foundry", deployment: "", revision: "r2", problem: "Set the Codex Azure endpoint" } } };

test("showing a task's choice only asks herdr-task select; each CLI's list has what Refresh found and the saved ones", async () => {
  writeFileSync(REPLY, JSON.stringify(SHOWN));
  const v: any = await taskSelection(settings, { ref: "HAT-3", folder: "/repo", machine: null, space: null }, null, {});
  expect(calls()).toEqual(["select HAT-3 --folder /repo --json"]);
  const claude = v.menus.claude.models;
  expect(claude.map((m: any) => m.id)).toEqual(["saved-deployment", "claude-default", "opus-deployment", "custom-deployment"]);
  // Effort levels only where the deployment's model is one Claude Code's catalogue knows; Fast never offered.
  expect(claude.find((m: any) => m.id === "opus-deployment").efforts).toEqual(["low", "medium", "high", "xhigh", "max"]);
  expect(claude.find((m: any) => m.id === "custom-deployment").efforts).toEqual([]);
  expect(claude.find((m: any) => m.id === "saved-deployment").efforts).toEqual([]);
  expect(claude.every((m: any) => m.fast === false && m.deployment === true)).toBe(true);
});

test("a save carries the revision it was shown at, and a refusal comes back as herdr-task said it", async () => {
  writeFileSync(REPLY, JSON.stringify(SHOWN));
  await taskSelection(settings, { ref: "HAT-3", folder: "/repo", machine: null }, { agent: "codex", deployment: "picked", effort: "high", revision: "abcd1234abcd1234" }, {});
  expect(calls()).toEqual(["select HAT-3 --folder /repo --agent codex --deployment picked --effort high --revision abcd1234abcd1234 --json"]);
  writeFileSync(REPLY, JSON.stringify({ error: "HAT-3's choice or its provider settings changed since this selector was opened" }));
  writeFileSync(`${REPLY}.code`, "1");
  await expect(taskSelection(settings, { ref: "HAT-3", folder: "/repo", machine: "vm1" }, { default: true, revision: "old" }, {}))
    .rejects.toThrow("changed since this selector was opened");
  expect(calls()[1]).toBe("--on vm1 select HAT-3 --folder /repo --default --revision old --json");
});

test("another machine's task offers only its saved deployments: Refresh reads this computer's Azure CLI", async () => {
  writeFileSync(REPLY, JSON.stringify(SHOWN));
  const v: any = await taskSelection(settings, { ref: "HAT-3", folder: "/repo", machine: "vm1" }, null, {});
  expect(v.menus.claude.models.map((m: any) => m.id)).toEqual(["saved-deployment", "claude-default"]);
});

test("Personal offers no deployment list, and an Assistant's choices come from provider show for its role", async () => {
  writeFileSync(REPLY, JSON.stringify({ ...SHOWN, route: "personal" }));
  expect(((await taskSelection(settings, { ref: "HAT-3", folder: "/repo", machine: null }, null, {})) as any).menus).toBeNull();
  writeFileSync(REPLY, JSON.stringify({ route: "azure-foundry", role: "coordinator", clis: SHOWN.clis }));
  const v: any = await assistantChoices(settings, { id: "sp1", folder: "/repo" }, {});
  expect(calls()[1]).toBe("provider show --role coordinator --space sp1 --folder /repo --json");
  expect(v.menus.claude.models[0].id).toBe("claude-default");
});

test("a space's list is the one Settings gives for it", () => {
  const menus: any = menusFor(settings, "sp1", { claude: [], codex: [] }, {});
  expect(menus.claude.models.map((m: any) => m.id)).toEqual(["opus-deployment", "custom-deployment"]);
  expect(menus.codex.models).toEqual([]);
});

test("a task whose space is known is asked for in that space, so its choice reads the settings its start reads", async () => {
  writeFileSync(REPLY, JSON.stringify(SHOWN));
  await taskSelection(settings, { ref: "HAT-3", folder: "/repo", machine: null, space: "vm1/sp4" }, null, {});
  expect(calls()).toEqual(["select HAT-3 --folder /repo --space sp4 --json"]);
});

// A web Assistant pick: only its space changes, inside the store's update, and only from the pick the menu showed.
test("two spaces' picks saved from the same snapshot both stay; an older menu can't overwrite or clear a newer pick", () => {
  const empty = pickRevision(undefined);
  // two menus opened on an empty store: each save runs on the current document (as Store.update's retry gives it)
  let doc: Record<string, unknown> = {};
  doc = withPick(doc, "sp1", { agent: "claude", model: "a" }, empty);
  doc = withPick(doc, "sp2", { agent: "codex", model: "b" }, empty);
  expect(Object.keys(doc).sort()).toEqual(["sp1", "sp2"]);
  // a menu opened before sp1's pick was saved quotes the old revision: refused, for a save and for a reset
  expect(() => withPick(doc, "sp1", { agent: "claude", model: "c" }, empty)).toThrow(STALE_PICK);
  expect(() => withPick(doc, "sp1", null, empty)).toThrow(STALE_PICK);
  // the current one is accepted, and a reset clears only that space
  expect(withPick(doc, "sp1", null, pickRevision(doc.sp1))).toEqual({ sp2: { agent: "codex", model: "b" } });
});

test("a start drops only the pick it used: a newer pick for its space, and other spaces' picks, stay", () => {
  const used = { agent: "claude", model: "a" };
  expect(withoutUsedPick({ sp1: used, sp2: { agent: "codex" } }, "sp1", { ...used })).toEqual({ sp2: { agent: "codex" } });
  const newer = { agent: "claude", model: "z" };
  expect(withoutUsedPick({ sp1: newer }, "sp1", used)).toEqual({ sp1: newer });
});

test("a task deployment picked from Refresh's list must come from the list in force; one typed by hand needs none", async () => {
  writeFileSync(REPLY, JSON.stringify(SHOWN));
  const t = { ref: "HAT-3", folder: "/repo", machine: null, space: null };
  await expect(taskSelection(settings, t, { agent: "claude", deployment: "opus-deployment", inventory: "0", revision: "r" }, {})).rejects.toThrow(STALE_LIST);
  expect(calls()).toEqual([]);
  await taskSelection(settings, t, { agent: "claude", deployment: "opus-deployment", inventory: "1", revision: "r" }, {});
  await taskSelection(settings, t, { agent: "claude", deployment: "typed-one", revision: "r" }, {});
  expect(calls().length).toBe(2);
  // what it shows carries each CLI's list revision and what that list holds
  const shown: any = await taskSelection(settings, t, null, {});
  expect(shown.inventory.claude).toBe("1");
  expect(shown.listed.claude).toEqual(["opus-deployment", "custom-deployment"]);
});
