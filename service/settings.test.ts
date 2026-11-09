import * as APc from "../core/autopilot.js";
import { expect, test } from "bun:test";
import { existsSync, mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// a throwaway settings file, never ~/.herdr/shepherdr.json
const file = join(mkdtempSync(join(tmpdir(), "shep-settings-")), "shepherdr.json");
writeFileSync(file, JSON.stringify({ everywhere: { machine: { start_load: 2 } }, spaces: { sp1: { folder: "/x" } } }));
process.env.HERDR_TASK_SETTINGS = file;
const { Settings } = await import("./settings.ts");
const CORE: any = await import("../core/settings.js");

test("the Tasks rows say the window's words, and a change keeps the rest of the file", () => {
  const s = new Settings();
  s.start();
  const tasks = s.sections("https://box/shepherdr/").find((x) => x.name === "Tasks" && x.level === "all")!;
  expect(tasks.rows.find((r) => r.key === "tasks.merge")).toMatchObject({ value: "On Accept", options: ["On Accept", "After checks pass", "Right away"] });
  s.set("tasks.merge", "After checks pass");
  s.set("tasks.max_running", "40");
  s.set("tasks.proof", "Off");
  const f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.everywhere.tasks).toEqual({ merge: "checks", max_running: 10, proof: false });
  expect(f.everywhere.machine).toEqual({ start_load: 2 });
  expect(f.spaces.sp1.folder).toBe("/x");
  expect(() => s.set("tasks.merge", "Whenever")).toThrow();
  expect(() => s.set("secrets.vault", "x")).toThrow();
});

test("a space's own values go in its layer with its folder, and Reset drops them", () => {
  const s = new Settings();
  s.start();
  const scope = { id: "sp2", name: "web", machine: null, folder: "/repo" };
  s.set("tasks.merge", "Right away", "sp2", scope);
  s.set("role.worker", JSON.stringify({ agent: "codex", model: "gpt-5", effort: "high" }), "sp2", scope);
  let f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.spaces.sp2).toEqual({ folder: "/repo", name: "web", tasks: { merge: "auto" }, worker: { agent: "codex", model: "gpt-5", effort: "high", fast: false, perm: null } });
  const tasks = s.sections(null, [scope]).find((x) => x.name === "Tasks" && x.level === "sp2")!;
  // as the window's: "Set for this space · Reset", Reset back to Everywhere's; Base branch only in a space's own
  expect(tasks.rows.find((r) => r.key === "tasks.merge")).toMatchObject({ value: "Right away", inherits: { from: "Everywhere" } });
  expect(tasks.rows.find((r) => r.key === "tasks.base")).toMatchObject({ label: "Base branch", text: true, placeholder: "Its current branch" });
  s.set("tasks.merge", null, "sp2", scope);
  f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.spaces.sp2.tasks).toBeUndefined();
  expect(() => s.set("tasks.merge", "Right away", "sp3", null)).toThrow();
});

test("Branch names (#570): Everywhere's or a space's own pattern, checked before it's kept", () => {
  const s = new Settings();
  s.start();
  const scope = { id: "sp6", name: "api", machine: null, folder: "/api" };
  const row = (level: string) => s.sections(null, [scope]).find((x) => x.name === "Tasks" && x.level === level)!.rows.find((r) => r.key === "tasks.branch")!;
  expect(row("all")).toMatchObject({ label: "Branch names", text: true, value: "", placeholder: "task/{n}-{slug}" });
  s.set("tasks.branch", "feat/{key}-{slug}", "all");
  s.set("tasks.branch", " {key} ", "sp6", scope);
  const f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.everywhere.tasks.branch).toBe("feat/{key}-{slug}");
  expect(f.spaces.sp6.tasks.branch).toBe("{key}");
  expect(row("sp6")).toMatchObject({ value: "{key}", inherits: { value: "feat/{key}-{slug}", from: "Everywhere" } });
  expect(() => s.set("tasks.branch", "feat/{slug}", "all")).toThrow("Put {n} or {key} in it");
  expect(() => s.set("tasks.branch", "a b/{n}", "all")).toThrow("isn't a name git allows");
  s.set("tasks.branch", "", "sp6", scope);
  expect(JSON.parse(readFileSync(file, "utf8")).spaces.sp6.tasks).toBeUndefined();
});

test("Autopilot: Everywhere's unless a space sets its own, kept with the rest and sent to its machine", async () => {
  const { pushBody } = await import("./settings.ts");
  const s = new Settings();
  s.start();
  const web = { id: "sp4", name: "web", machine: null, folder: "/web" }, api = { id: "pi/sp5", name: "api", machine: "pi", folder: "/api" };
  const pilot = { everywhere: { every: "every 60 minutes", events: ["ready"], words: "Keep it green." } };
  s.set("autopilot.every", "weekdays 9:00", "pi/sp5", api);
  s.set("autopilot.heartbeat", "Only the API.", "pi/sp5", api);
  s.set("autopilot.events", "merged,ready", "all");
  let f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.spaces["pi/sp5"].autopilot).toEqual({ every: "weekdays 9:00", heartbeat: "Only the API." });
  expect(f.everywhere.autopilot).toEqual({ events: ["ready", "merged"] });
  expect(JSON.parse(pushBody(f, "pi")).spaces.sp5.autopilot.every).toBe("weekdays 9:00");
  const page = (level: string) => s.sections(null, [web, api], ["pi"], "box", pilot).find((x) => x.name === "Autopilot" && x.level === level)!;
  const row = (level: string, key: string) => page(level).rows.find((r) => r.key === key)!;
  expect(row("pi/sp5", "autopilot.every")).toMatchObject({ value: "weekdays 9:00", inherits: { value: "Every hour", from: "Everywhere" } });
  expect(row("pi/sp5", "autopilot.events")).toMatchObject({ value: "ready,merged", from: "Everywhere" });
  expect(row("sp4", "autopilot.every")).toMatchObject({ value: "every 60 minutes", from: "Everywhere" });
  expect(row("sp4", "autopilot.heartbeat")).toMatchObject({ value: "Keep it green." });
  expect(row("all", "autopilot.every").others).toEqual([{ id: "pi/sp5", name: "api" }]);
  expect(() => s.set("autopilot.events", "lunch", "all")).toThrow();
  // a space's Direction: one line; empty, none (Everywhere's page has no Direction row)
  s.set("autopilot.direction", "  Launch the\n  shop ", "sp4", web);
  expect(JSON.parse(readFileSync(file, "utf8")).spaces.sp4.autopilot).toEqual({ direction: "Launch the shop" });
  expect(row("sp4", "autopilot.direction")).toMatchObject({ value: "Launch the shop", text: true });
  expect(row("all", "autopilot.direction")).toBeUndefined();
  s.set("autopilot.direction", "", "sp4", web);
  expect(JSON.parse(readFileSync(file, "utf8")).spaces.sp4.autopilot).toBeUndefined();
  // an earlier version's starter in Settings shows as today's
  s.set("autopilot.heartbeat", APc.OLD_STARTERS[0], "sp4", web);
  expect(row("sp4", "autopilot.heartbeat").value).toBe(APc.STARTER);
  s.set("autopilot.heartbeat", null, "sp4", web);
  expect(page("all").about).toContain("push the project forward");
  expect(page("all").about).toContain("never asking you");
  // Reset: back to Everywhere's
  s.set("autopilot.every", null, "pi/sp5", api);
  s.set("autopilot.heartbeat", null, "pi/sp5", api);
  f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.spaces["pi/sp5"].autopilot).toBeUndefined();
  // without its add-on, no page
  expect(s.sections(null, [web], [], "box", null).some((x) => x.name === "Autopilot")).toBe(false);
});

test("machine limits: percents on the page, the file's own units, and this computer as local", () => {
  const s = new Settings();
  s.start();
  s.sections(null, [], [], "box");
  s.set("machine.start_load", "150", "all");
  s.set("machine.start_memory", "off", "m:box");
  s.set("machine.worker_memory", "4 GB", "m:box");
  const f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.everywhere.machine.start_load).toBe(1.5);
  expect(f.machines.local.machine).toEqual({ start_memory: null, worker_memory: 4 });
  expect(() => s.set("machine.worker_memory", "3 GB", "all")).toThrow();
});

test("another machine's space keeps its machine/id key, and its machine is sent only its own", async () => {
  const { pushBody } = await import("./settings.ts");
  const s = new Settings();
  s.start();
  s.set("tasks.merge", "Right away", "vm/sp9", { id: "vm/sp9", name: "api", machine: "vm", folder: "/srv/api" });
  const f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.spaces["vm/sp9"]).toMatchObject({ machine: "vm", folder: "/srv/api", tasks: { merge: "auto" } });
  const sent = JSON.parse(pushBody(f, "vm"));
  expect(sent).toMatchObject({ pushed_from: "herdr-app", here: "vm", spaces: { sp9: { folder: "/srv/api" } } });
  expect(Object.keys(sent.spaces)).toEqual(["sp9"]);
});

test("a machine that isn't connected, a prototype key, or an unreadable file is refused, and nothing is written", () => {
  const s = new Settings();
  s.start();
  s.sections(null, [], ["vm"], "box");
  const before = readFileSync(file, "utf8");
  expect(() => s.set("machine.start_load", "150", "m:__proto__")).toThrow();
  expect(() => s.set("machine.start_load", "150", "m:typo")).toThrow();
  expect(({} as any).machine).toBeUndefined();
  expect(readFileSync(file, "utf8")).toBe(before);
  writeFileSync(file, "{ half");
  expect(() => s.set("tasks.merge", "Right away")).toThrow();
  expect(readFileSync(file, "utf8")).toBe("{ half");
  writeFileSync(file, before);
});

test("Machines is one page as the window's: every machine's limits, then each machine's block (key@machine)", () => {
  const s = new Settings();
  s.start();
  const page = s.sections(null, [], ["vm"], "box").filter((x) => x.name === "Machines");
  expect(page.length).toBe(1);
  expect(page[0].rows.find((r) => r.key === "machine.home@local")).toMatchObject({ group: "This computer", value: "on" });
  expect(page[0].rows.find((r) => r.key === "machine.home@vm")).toMatchObject({ group: "vm", value: "off" });
  s.set("machine.worker_memory@vm", "8 GB");
  const f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.machines.vm.machine.worker_memory).toBe(8);
  // the window's steppers: "Off"/"80%" stepping through percents; a percent back from the page sets the file's units
  const load = s.sections(null, [], ["vm"], "box").find((x) => x.name === "Machines")!.rows.find((r) => r.key === "machine.start_load")!;
  expect(load.steps?.[0]).toBe("25%");
  s.set("machine.start_load", "175%", "all");
  expect(JSON.parse(readFileSync(file, "utf8")).everywhere.machine.start_load).toBe(1.75);
});

test("Agents and Tasks say the window's words: the model button, Other CLI, Must fix only with a review", async () => {
  const C: any = await import("../core/settings.js");
  const s = new Settings();
  s.start();
  s.choices = C.choicesFrom({ claude: { model: "opus[1m]", effort: "high", per: {} }, codex: { models: [{ id: "gpt-5", label: "GPT-5", efforts: ["low", "high"] }] } });
  const agents = s.sections(null).find((x) => x.name === "Agents" && x.level === "all")!;
  expect(agents.rows.map((r) => r.label)).toEqual(["Assistant", "Workers", "Reviewer", "Backup agent", "Reactions", "Feedback offers", "Feedback repo", "Ask for a GitHub star"]);
  expect(agents.rows[0].value).toBe("Opus 5.5 · 1M · High");
  expect(agents.rows[2]).toMatchObject({ value: "Other CLI (Codex)", agent: { unset: true, other: false } });
  const tasks = s.sections(null).find((x) => x.name === "Tasks" && x.level === "all")!;
  expect(tasks.rows.some((r) => r.key === "tasks.must_fix")).toBe(false);
  expect(tasks.rows.find((r) => r.key === "tasks.max_running")).toMatchObject({ hint: C.ABOUT["tasks.max_running"], steps: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"] });
  const web = s.sections({ on: true, link: "https://box/shepherdr/", why: null }).find((x) => x.name === "Web")!;
  expect(web.rows.map((r) => r.label)).toEqual(["Shepherdr on the web", "Link"]);
  expect(web.rows[0].hint).toBe("On, private to your tailnet.");
});

// SHEP-48: Reactions, one Agents row for every agent: on by default, off Everywhere, a space's own on, Reset back
test("Reactions: on by default for every agent, Everywhere's or a space's own", () => {
  writeFileSync(file, "{}");
  const s = new Settings();
  s.start();
  const sp = { id: "sp7", name: "shop", machine: null, folder: "/shop" };
  const row = (level: string) => s.sections(null, [sp]).find((x) => x.name === "Agents" && x.level === level)!.rows;
  expect(row("all").find((r) => r.key === "agents.reactions")).toMatchObject({ key: "agents.reactions", label: "Reactions", value: "on", options: ["on", "off"], hint: CORE.REACTIONS.about });
  expect(CORE.REACTIONS.about).not.toMatch(/Assistant/);
  s.set("agents.reactions", "off", "all");
  let f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.everywhere.agents).toEqual({ reactions: false });
  expect(row("sp7").find((r) => r.key === "agents.reactions")).toMatchObject({ value: "off", from: "Everywhere" });
  s.set("agents.reactions", "on", "sp7", sp);
  f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.spaces.sp7.agents).toEqual({ reactions: true });
  expect(row("sp7").find((r) => r.key === "agents.reactions")).toMatchObject({ value: "on", inherits: { value: "off", from: "Everywhere" } });
  expect(row("all").find((r) => r.key === "agents.reactions")?.others).toEqual([{ id: "sp7", name: "shop" }]);
  // the same as what it would inherit unsets it; Reset too; back on Everywhere is the default again
  s.set("agents.reactions", null, "sp7", sp);
  s.set("agents.reactions", "on", "all");
  f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.spaces.sp7.agents).toBeUndefined();
  expect(f.everywhere.agents).toBeUndefined();
  expect(() => s.set("agents.reactions", "maybe", "all")).toThrow();
});

// SHEP-48: SHEP-42 kept it as the Assistant's (assistant.reactions): read as the Agents row, moved on the next change
test("Reactions set as the Assistant's before still apply, and move to agents on a change", () => {
  writeFileSync(file, JSON.stringify({ everywhere: { assistant: { reactions: false } }, spaces: { sp7: { folder: "/shop", assistant: { reactions: true } } } }));
  const s = new Settings();
  s.start();
  const sp = { id: "sp7", name: "shop", machine: null, folder: "/shop" };
  const row = (level: string) => s.sections(null, [sp]).find((x) => x.name === "Agents" && x.level === level)!.rows.find((r) => r.key === "agents.reactions");
  expect(row("all")).toMatchObject({ value: "off" });
  expect(row("sp7")).toMatchObject({ value: "on", inherits: { value: "off", from: "Everywhere" } });
  // its old key still sets it (a page from before), written as agents'
  s.set("assistant.reactions", "on", "all");
  const f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.everywhere).toEqual({});
  expect(f.spaces.sp7).toEqual({ folder: "/shop", agents: { reactions: true } });
  expect(CORE.upgradeReactions({ everywhere: { assistant: { reactions: false }, agents: { reactions: true } } })).toEqual({ everywhere: { agents: { reactions: true } } });
});

// SHEP-79: Ask for a GitHub star, Everywhere only: a switch until the card has shown, then just when it asked
test("Ask for a star: an Everywhere switch that turns it off before it ever shows, and never re-arms once asked", () => {
  writeFileSync(file, "{}");
  const s = new Settings();
  s.start();
  const sp = { id: "sp7", name: "shop", machine: null, folder: "/shop" };
  const row = (level: string) => s.sections(null, [sp]).find((x) => x.name === "Agents" && x.level === level)!.rows.find((r) => r.key === "star_prompt");
  expect(row("all")).toMatchObject({ label: CORE.STAR.title, value: "on", options: ["on", "off"] });
  expect(row("sp7")).toBeUndefined();
  expect(() => s.set("star_prompt", "off", "sp7", sp)).toThrow();
  s.set("star_prompt", "off", "all");
  expect(JSON.parse(readFileSync(file, "utf8")).everywhere.star_prompt).toEqual({ off: true });
  expect(row("all")).toMatchObject({ value: "off" });
  s.set("star_prompt", "on", "all");
  expect(JSON.parse(readFileSync(file, "utf8")).everywhere.star_prompt).toBeUndefined();
  // asked (herdr-task star ask, on any machine): read-only, says when, and a switch can't ask again
  writeFileSync(file, JSON.stringify({ everywhere: { star_prompt: { asked: Date.UTC(2026, 10, 6), answer: "no" } } }));
  (s as any).read();
  expect(row("all")).toMatchObject({ value: "Asked", fixed: true });
  expect(row("all")!.hint).toMatch(/won't ask again/);
  expect(() => s.set("star_prompt", "on", "all")).toThrow();
  expect(CORE.starState({ everywhere: { star_prompt: { asked: 1 } } }).on).toBe(false);
});

// SHEP-78: Feedback offers, on by default, per space as Reactions; the repo Everywhere's only, checked
test("Feedback offers and its repo", () => {
  writeFileSync(file, "{}");
  const s = new Settings();
  s.start();
  const sp = { id: "sp7", name: "shop", machine: null, folder: "/shop" };
  const row = (level: string) => s.sections(null, [sp]).find((x) => x.name === "Agents" && x.level === level)!.rows;
  expect(row("all").find((r) => r.key === "agents.feedback")).toMatchObject({ label: "Feedback offers", value: "on", options: ["on", "off"] });
  expect(row("all").find((r) => r.key === "agents.feedback_repo")).toMatchObject({ label: "Feedback repo", value: "", text: true, placeholder: "eliasstravik/shepherdr" });
  expect(row("sp7").find((r) => r.key === "agents.feedback_repo")).toBeUndefined();
  s.set("agents.feedback", "off", "sp7", sp);
  s.set("agents.feedback_repo", "https://github.com/acme/shep", "all");
  const f = JSON.parse(readFileSync(file, "utf8"));
  expect(f.spaces.sp7.agents).toEqual({ feedback: false });
  expect(f.everywhere.agents).toEqual({ feedback_repo: "acme/shep" });
  expect(() => s.set("agents.feedback_repo", "nope nope", "all")).toThrow();
  expect(() => s.set("agents.feedback_repo", "acme/x", "sp7", sp)).toThrow();
  s.set("agents.feedback_repo", "", "all");
  expect(JSON.parse(readFileSync(file, "utf8")).everywhere?.agents).toBeUndefined();
});

// ---- Settings › Agents › Provider (A2) ----------------------------------------------------------------------------
// The person's own Azure Foundry connection rows, checked as herdr-task checks them (one field table both judge), with a
// stand-in `az` for Refresh: no Azure, no sign-in and no agent. They prove the rows, the file and stale-pick refusal.
const { AzureDeployments } = await import("./azure-deployments.ts");
const BINDING: any = (await import("../test/azure-binding.cases.json")).default;
const providerOf = (level: string, scopes: any[] = []) => {
  const s = new Settings();
  s.start();
  return { s, rows: () => s.sections(null, scopes).find((x) => x.name === "Agents" && x.level === level)!.rows.filter((r) => r.key.startsWith("provider.")) };
};
const fileNow = () => JSON.parse(readFileSync(file, "utf8"));

test("the provider's fields are judged as herdr-task judges them, a refused one never repeated", () => {
  for (const c of BINDING.cases) {
    if (c.ok) expect(CORE.providerValue(c.field, c.value)).toBe(c.kept);
    else {
      let said = "";
      try { CORE.providerValue(c.field, c.value); } catch (e) { said = (e as Error).message; }
      expect(said).not.toBe("");
      expect(said).not.toContain(c.value.trim());
    }
  }
  expect(CORE.providerValue("route", "Azure Foundry")).toBe("azure-foundry");
  expect(CORE.providerValue("claude_auth", "Bearer token")).toBe("bearer-token");
  expect(() => CORE.providerValue("codex_auth", "Entra ID")).toThrow("API key only");
  expect(() => CORE.providerValue("api_key", "x")).toThrow();
});

test("Personal shows the route alone; Azure Foundry shows each CLI's connection, kept as the file's values", () => {
  const { s, rows } = providerOf("all");
  expect(rows().map((r) => r.key)).toEqual(["provider.route"]);
  expect(rows()[0]).toMatchObject({ value: "Personal", options: ["Personal", "Azure Foundry"] });
  s.set("provider.route", "Azure Foundry");
  s.set("provider.claude_resource", " example ");
  s.set("provider.claude_auth", "API key");
  s.set("provider.codex_endpoint", "https://example.openai.azure.com/openai/v1/");
  expect(fileNow().everywhere.provider).toEqual({ route: "azure-foundry", claude_resource: "example", claude_auth: "api-key",
    codex_endpoint: "https://example.openai.azure.com/openai/v1" });
  const keys = rows().map((r) => r.key);
  expect(keys).toContain("provider.claude_deployment");
  expect(keys).toContain("provider.coordinator_codex_deployment");
  expect(rows().find((r) => r.key === "provider.claude_deployment")).toMatchObject({ text: true, discovery: { kind: "claude", busy: false, options: [], revision: "" } });
  // A URL where a resource name goes, or a key pasted in: refused, the value never repeated, the file unchanged.
  const before = readFileSync(file, "utf8");
  expect(() => s.set("provider.claude_resource", "https://example.services.ai.azure.com/anthropic")).toThrow("not a URL");
  let said = "";
  try { s.set("provider.claude_deployment", "sk-marker pasted"); } catch (e) { said = (e as Error).message; }
  expect(said).not.toContain("sk-marker");
  expect(readFileSync(file, "utf8")).toBe(before);
  s.set("provider.route", "Personal");
  // Under Personal the half-set Azure setup is kept, only not shown.
  expect(rows().map((r) => r.key)).toEqual(["provider.route"]);
  expect(fileNow().everywhere.provider.claude_resource).toBe("example");
});

test("a space inherits field by field; its empty value is its own, and Reset follows Everywhere again", () => {
  const scope = { id: "sp7", name: "api", machine: null, folder: "/api7" };
  const { s, rows } = providerOf("sp7", [scope]);
  s.set("provider.route", "Azure Foundry");
  s.set("provider.claude_deployment", "everywhere-deployment");
  expect(rows().find((r) => r.key === "provider.claude_deployment")).toMatchObject({ value: "everywhere-deployment", from: "Everywhere" });
  s.set("provider.claude_deployment", "", "sp7", scope);
  expect(fileNow().spaces.sp7.provider).toEqual({ claude_deployment: "" });
  expect(rows().find((r) => r.key === "provider.claude_deployment")).toMatchObject({ value: "", inherits: { value: "everywhere-deployment", from: "Everywhere" } });
  s.set("provider.claude_deployment", null, "sp7", scope);
  expect(fileNow().spaces.sp7.provider).toBeUndefined();
  s.set("provider.route", "Personal");
});

test("Refresh's list is read only when asked, and a pick from a list read under another resource is refused", async () => {
  const dir = mkdtempSync(join(tmpdir(), "shep-az-settings-")), az = join(dir, "az");
  const SUB = "1111aaaa-2222-3333-4444-555555555555";
  writeFileSync(join(dir, "inventory.json"), JSON.stringify([
    { name: "opus-deployment", properties: { model: { name: "claude-opus-5-5", format: "Anthropic", version: "1" }, provisioningState: "Succeeded", capabilities: { chatCompletion: "true" } } }]));
  writeFileSync(az, `#!/bin/sh\necho "$*" >> "${dir}/calls"\ncase "$1 $2 $3" in\n"account show"*) echo '{"id":"${SUB}","environmentName":"AzureCloud"}';;\n"cognitiveservices account deployment") cat "${dir}/inventory.json";;\n"cognitiveservices account list") echo '[{"name":"example","resourceGroup":"g1"}]';;\n*) exit 2;;\nesac\n`, { mode: 0o755 });
  const { s, rows } = providerOf("all");
  s.deployments = new AzureDeployments({ az });
  s.set("provider.route", "Azure Foundry");
  s.set("provider.claude_resource", "example");
  // Showing the rows asks Azure nothing.
  rows();
  expect(existsSync(join(dir, "calls"))).toBe(false);
  const view = await s.refreshDeployments("claude", "all", null);
  expect(view.options.map((o: any) => o.value)).toEqual(["opus-deployment"]);
  const shown = rows().find((r) => r.key === "provider.claude_deployment")!.discovery!;
  expect(shown.options).toEqual([{ value: "opus-deployment", label: "opus-deployment · claude-opus-5-5 (1)", model: "claude-opus-5-5" }]);
  expect(shown.revision).not.toBe("");
  // Refresh selects nothing.
  expect(fileNow().everywhere.provider.claude_deployment).toBeUndefined();
  s.set("provider.claude_deployment", "opus-deployment", "all", null, shown.revision);
  expect(fileNow().everywhere.provider.claude_deployment).toBe("opus-deployment");
  // The resource changed: the list is gone, and a pick still carrying its revision is refused, the file unchanged.
  s.set("provider.claude_resource", "other");
  expect(rows().find((r) => r.key === "provider.claude_deployment")!.discovery!.options).toEqual([]);
  expect(() => s.set("provider.claude_deployment", "another", "all", null, shown.revision)).toThrow("refresh again");
  expect(fileNow().everywhere.provider.claude_deployment).toBe("opus-deployment");
  // Typed by hand, a deployment needs no list.
  s.set("provider.claude_deployment", "typed-deployment");
  expect(fileNow().everywhere.provider.claude_deployment).toBe("typed-deployment");
  // Everywhere with another machine connected has no single machine to read on: refused before asking Azure.
  s.sections(null, [], ["vm1"]);
  await expect(s.refreshDeployments("claude", "all", null)).rejects.toThrow("one machine");
  s.set("provider.route", "Personal");
});
