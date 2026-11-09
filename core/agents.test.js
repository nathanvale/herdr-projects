import { expect, test } from "bun:test";
import { argvFor, azureMenu, current, line, menuFor, modelSections, parseDefaults, parsePicks, pickKey, providerRefusal, ROUTE_HELD, ROUTE_UNKNOWN, routeArgs, routeRefusal, withPin, withRecent } from "./agents.js";

const codex = { models: Array.from({ length: 250 }, (_, i) => ({ id: `gpt-${i}`, label: `GPT ${i}`, efforts: ["low", "high"] })) };
const menus = { claude: menuFor("claude", {}), codex: menuFor("codex", codex) };

test("Codex lists every model it has, not its first five", () => {
  expect(menus.codex.models.length).toBe(250);
});

test("nothing typed: pinned, then recent, then the rest of the agent shown", () => {
  const picks = withRecent(withPin(parsePicks(""), pickKey("claude", "haiku")), pickKey("claude", "sonnet"));
  const s = modelSections(menus, "claude", picks, "");
  expect(s.map((x) => x.title)).toEqual(["Pinned", "Recent", "All models"]);
  expect(s[0].rows.map((r) => r.id)).toEqual(["haiku"]);
  expect(s[1].rows.map((r) => r.id)).toEqual(["sonnet"]);
  expect(s[2].rows.some((r) => r.id === "haiku" || r.id === "sonnet")).toBe(false);
});

test("a long list is capped and counts the rest", () => {
  const [all] = modelSections(menus, "codex", null, "");
  expect(all.rows.length).toBe(200);
  expect(all.more).toBe(50);
});

test("typed: every agent's matches, and a row to use the id typed", () => {
  const s = modelSections(menus, "codex", null, "opus 1m");
  expect(s.map((x) => x.key)).toEqual(["claude"]);
  expect(s[0].rows.map((r) => r.id)).toEqual(["opus[1m]"]);
  const t = modelSections(menus, "codex", null, "gpt-7-preview").find((x) => x.key === "typed");
  expect(t.rows.map((r) => [r.agent, r.id, r.typed])).toEqual([["codex", "gpt-7-preview", true], ["claude", "gpt-7-preview", true]]);
  expect(modelSections(menus, "codex", null, "gpt-999").map((x) => x.key)).toEqual(["typed"]);
  expect(modelSections(menus, "codex", null, "gpt-12").find((x) => x.key === "typed").rows.map((r) => r.agent)).toEqual(["claude"]);
});

test("an exact id typed needs no extra row; picks survive bad files", () => {
  expect(parsePicks("not json")).toEqual({ pinned: [], recent: [] });
  expect(withPin(withPin(parsePicks(""), "a:b"), "a:b").pinned).toEqual([]);
});

test("a running model typed by id stays in its agent's list", () => {
  expect(menuFor("claude", {}, "claude-opus-4-8").models[0]).toMatchObject({ id: "claude-opus-4-8", name: "Opus 4.8" });
});

test("a pinned or recent model typed by id stays on offer", () => {
  const picks = withRecent(withPin(parsePicks(""), "claude:claude-opus-4-8"), "codex:gpt-x");
  expect(modelSections(menus, "claude", picks, "")[0].rows[0]).toMatchObject({ id: "claude-opus-4-8", name: "Opus 4.8", pinned: true });
  expect(modelSections(menus, "codex", picks, "")[0]).toMatchObject({ title: "Recent", rows: [{ id: "gpt-x" }] });
  expect(modelSections(menus, "claude", picks, "gpt-x").map((x) => x.key)).toEqual(["codex", "typed"]);
});

// SHEP-41: Fast was hidden (and stuck on) for a Codex whose config.toml set service_tier.
test("every agent with a fast mode shows the Fast switch, and turning it off sticks", () => {
  const cache = JSON.stringify({ models: [{ slug: "gpt-x", display_name: "GPT-X", supported_reasoning_levels: [{ effort: "high" }], service_tiers: [{ id: "priority" }] },
    { slug: "gpt-slow", display_name: "GPT-Slow", service_tiers: [] }] });
  const dflt = parseDefaults("codex", `model\tgpt-x\nservice_tier\tfast\nmodels\t${cache}\n`);
  const codexMenu = menuFor("codex", dflt);
  expect(codexMenu.models.find((m) => m.id === "gpt-x").fast).toBe(true);
  expect(codexMenu.models.find((m) => m.id === "gpt-slow").fast).toBe(false);
  expect(codexMenu.fastLocked).toBeUndefined();
  expect(menuFor("claude", {}).models.find((m) => m.id === "opus").fast).toBe(true);
  // off: said on the command line, so config.toml's fast loses, and the label reads it back
  const off = argvFor({ agent: "codex", model: "gpt-x", effort: "high", fast: false }, { agent: "codex", argv: ["codex", "-c", 'service_tier="fast"'] }).argv;
  expect(off.filter((a) => a.startsWith("service_tier"))).toEqual(['service_tier="default"']);
  expect(current("codex", off, {}, dflt).fast).toBe(false);
  expect(line(current("codex", off, {}, dflt))).toBe("Codex · GPT-X · High");
  const on = argvFor({ agent: "codex", model: "gpt-x", fast: true }, { agent: "codex", argv: off }).argv;
  expect(current("codex", on, {}, dflt).fast).toBe(true);
  const claudeOff = argvFor({ agent: "claude", model: "opus", fast: false }, { agent: "claude", argv: ["claude"] }).argv;
  expect(current("claude", claudeOff, {}, { fast: true }).fast).toBe(false);
});

// A2: the L2 sites' refusals and the words they ask herdr-task's provider owner with.
test("restart, fork, a lost session and revival refuse anything but Personal", () => {
  expect(routeRefusal({ route: "personal" })).toBe(null);
  expect(routeRefusal({ route: "azure-foundry" })).toBe(ROUTE_HELD);
  for (const shown of [null, {}, { route: 7 }]) expect(routeRefusal(shown)).toBe(ROUTE_UNKNOWN);
  expect(providerRefusal({ labels: {} })).toBe(null);
  expect(providerRefusal({ labels: { "herdr.provider": "personal" } })).toBe(null);
  expect(providerRefusal({ labels: { "herdr.provider": "azure-foundry" } })).toContain("started on Azure Foundry");
});

test("the route is asked for the agent's role, space and folder, on its own machine", () => {
  const task = { labels: { "herdr.task": "repo#4", "herdr.task.space": "sp1" }, cwd: "/w", foreground: { cwd: "/w/sub" } };
  expect(routeArgs(task)).toEqual(["provider", "show", "--role", "worker", "--space", "sp1", "--folder", "/w/sub", "--json"]);
  const assistant = { labels: { "herdr.coordinator.space": "vm1/sp2" }, cwd: "/r" };
  expect(routeArgs(assistant, "vm1")).toEqual(["--on", "vm1", "provider", "show", "--role", "coordinator", "--space", "sp2", "--folder", "/r", "--json"]);
  expect(routeArgs(null)).toEqual(["provider", "show", "--role", "coordinator", "--json"]);
});

test("an Azure list offers each deployment as found, the saved ones first, efforts only for a known model", () => {
  const m = azureMenu("claude", [{ value: "opus-dep", label: "opus-dep · claude-opus-5-5 (1)", model: "claude-opus-5-5" },
    { value: "house", label: "house · house-model", model: "house-model" }], ["saved", "opus-dep"], {});
  expect(m.models.map((x) => x.id)).toEqual(["saved", "opus-dep", "house"]);
  expect(m.models.find((x) => x.id === "opus-dep").efforts.length).toBeGreaterThan(0);
  expect(m.models.find((x) => x.id === "house").efforts).toEqual([]);
  expect(m.models.every((x) => x.fast === false && x.deployment === true)).toBe(true);
  expect(m.azure).toBe(true);
});
