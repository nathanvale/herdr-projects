// Azure deployment discovery (azure-deployments.ts) against a stand-in `az` that really runs as a process: it records
// every command it is given and answers from a control file. No Azure, no sign-in and no agent exists here, so these
// prove what discovery asks for and what it shows; they don't prove Azure access or what a deployment can do.
import { expect, test } from "bun:test";
import { chmodSync, existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AzureDeployments, deploymentName, discoveryResource, discoverySubscription, type AzureKind } from "./azure-deployments.ts";
import table from "../test/azure-binding.cases.json";

const SUB = "1111aaaa-2222-3333-4444-555555555555";
const ENDPOINT = "https://example.openai.azure.com/openai/v1";
const IDLE = "Refresh reads this resource's deployments with this machine's Azure CLI login, or type a deployment's name. Changes apply to new conversations; existing ones keep theirs.";
const CHECKED = `Subscription ${SUB}. Checked 2027-01-15T08:00:00.000Z. Inventory is not a sign-in, model-request or tool-use test.`;
const TAIL = ["--output", "json", "--only-show-errors"];
const SHOW = ["account", "show", "--query", "{id:id,environmentName:environmentName}", ...TAIL];
const RESOURCES = ["cognitiveservices", "account", "list", "--subscription", SUB, "--query", "[].{name:name,resourceGroup:resourceGroup}", ...TAIL];
const DEPLOYMENTS = ["cognitiveservices", "account", "deployment", "list", "--name", "example", "--resource-group", "example-group", "--subscription", SUB,
  "--query", "[].{name:name,properties:{model:properties.model,provisioningState:properties.provisioningState,capabilities:properties.capabilities}}", ...TAIL];
// The only commands discovery may ever run, by their leading words.
const READ_ONLY = ["account show", "cognitiveservices account list", "cognitiveservices account deployment list"];

const FAKE = `import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const dir = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
appendFileSync(join(dir, "calls.jsonl"), JSON.stringify(argv) + "\\n");
const c = JSON.parse(readFileSync(join(dir, "control.json"), "utf8"));
const is = (...words) => words.every((w, i) => argv[i] === w);
const out = (v) => process.stdout.write(JSON.stringify(v));
if (c.fail && is(...c.fail)) { process.stderr.write(c.stderr); process.exit(1); }
if (is("account", "show")) out({ id: c.subscription, environmentName: c.cloud });
else if (is("cognitiveservices", "account", "deployment", "list")) {
  if (c.hold) { writeFileSync(join(dir, "entered"), ""); while (!existsSync(join(dir, "release"))) await new Promise((r) => setTimeout(r, 10)); }
  out(c.inventory);
} else if (is("cognitiveservices", "account", "list")) out(c.resources);
else process.exit(2);
`;

const deployment = (name: string, format: string, capabilities: Record<string, unknown>, state = "Succeeded", model: unknown = "test-model") =>
  ({ name, properties: { model: { name: model, format, version: "1" }, provisioningState: state, capabilities } });
const INVENTORY = [
  deployment("code-deployment", "OpenAI", { responses: "true" }, "Succeeded", "gpt-test"),
  deployment("claude-deployment", "Anthropic", { chatCompletion: "true" }, "Succeeded", "claude-test"),
  deployment("bool-capability", "OpenAI", { responses: true }),
  deployment("embedding-only", "OpenAI", { embeddings: "true" }),
  deployment("still-creating", "OpenAI", { responses: "true" }, "Creating"),
  deployment("unknown-capabilities", "OpenAI", {}),
  deployment("capability-off", "OpenAI", { responses: "false" }),
  deployment("chat-only-openai", "OpenAI", { chatCompletion: "true" }),
  deployment("anthropic-responses", "Anthropic", { responses: "true" }),
  deployment("--not a name", "OpenAI", { responses: "true" }),
  deployment("no-model-name", "OpenAI", { responses: "true" }, "Succeeded", null),
];

function fixture(patch: Record<string, unknown> = {}, options: { timeoutMs?: number } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "shep-az-")), az = join(dir, "az"), log = join(dir, "calls.jsonl");
  const control: Record<string, unknown> = { subscription: SUB, cloud: "AzureCloud", stderr: "", hold: false, inventory: INVENTORY,
    resources: [{ name: "Example", resourceGroup: "example-group" }, { name: "another", resourceGroup: "other-group" }] };
  const set = (next: Record<string, unknown>) => writeFileSync(join(dir, "control.json"), JSON.stringify(Object.assign(control, next)));
  set(patch);
  writeFileSync(join(dir, "az.mjs"), FAKE);
  writeFileSync(az, `#!/bin/sh\nexec "${process.execPath}" "${join(dir, "az.mjs")}" "$@"\n`);
  chmodSync(az, 0o755);
  const calls = (): string[][] => (existsSync(log) ? readFileSync(log, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)) : []);
  const state = { changed: 0 };
  const make = () => new AzureDeployments({ az, now: () => 1_800_000_000_000, changed: () => { state.changed++; }, ...options });
  const d = make();
  const codex = (scope = "all", machines: (string | null)[] = [null], target = ENDPOINT, subscription = "") =>
    d.refresh({ scope, kind: "codex", machines, target, subscription });
  const entered = async () => { for (let i = 0; i < 400 && !existsSync(join(dir, "entered")); i++) await Bun.sleep(10); expect(existsSync(join(dir, "entered"))).toBe(true); };
  const release = () => writeFileSync(join(dir, "release"), "");
  /** Everything discovery ran was one of its three read-only commands. */
  const readOnly = () => { for (const c of calls()) expect(READ_ONLY.some((w) => c.join(" ").startsWith(w + " "))).toBe(true); };
  return { dir, az, d, make, set, calls, state, codex, entered, release, readOnly };
}

test("a refresh offers only ready deployments with the CLI's own format and capability, and picks none", async () => {
  const f = fixture();
  expect(f.d.view("all", "codex", { target: ENDPOINT })).toEqual({ busy: false, options: [], hint: IDLE });
  expect(f.calls()).toEqual([]); // looking never asks Azure
  const view = await f.codex();
  expect(view).toEqual({ busy: false, subscription: SUB, checkedAt: 1_800_000_000_000, hint: `2 matching deployments. ${CHECKED}`, options: [
    { value: "bool-capability", label: "bool-capability · test-model (1)", model: "test-model", version: "1" },
    { value: "code-deployment", label: "code-deployment · gpt-test (1)", model: "gpt-test", version: "1" },
  ] });
  expect(f.calls()).toEqual([SHOW, RESOURCES, DEPLOYMENTS]);
  const claude = await f.d.refresh({ scope: "all", kind: "claude", machines: ["local"], target: "example" });
  expect(claude.options).toEqual([{ value: "claude-deployment", label: "claude-deployment · claude-test (1)", model: "claude-test", version: "1" }]);
  expect(claude.hint).toBe(`1 matching deployment. ${CHECKED}`);
  expect(f.calls()).toEqual([SHOW, RESOURCES, DEPLOYMENTS, SHOW, RESOURCES, DEPLOYMENTS]);
  // one CLI's inventory is never the other's
  expect(f.d.view("all", "codex", { target: ENDPOINT }).options.map((o) => o.value)).toEqual(["bool-capability", "code-deployment"]);
  f.readOnly();
});

test("the discovery subscription is named on every read, and the Azure CLI's own is never changed", async () => {
  const f = fixture();
  const pinned = await f.codex("all", [null], ENDPOINT, SUB.toUpperCase());
  expect(pinned.subscription).toBe(SUB);
  expect(f.calls()).toEqual([["account", "show", "--subscription", SUB, "--query", "{id:id,environmentName:environmentName}", ...TAIL], RESOURCES, DEPLOYMENTS]);
  // Azure CLI answering for another subscription than the one set is refused before any listing
  f.set({ subscription: "99999999-2222-3333-4444-555555555555" });
  const other = await f.codex("all", [null], ENDPOINT, SUB);
  expect(other).toEqual({ busy: false, options: [], hint: IDLE, warn: "Azure CLI answered for another subscription than the one set. Check the discovery subscription." });
  expect(f.calls()).toHaveLength(4);
  // not a subscription id: refused before az runs at all, so it can never become an az option
  await expect(f.codex("all", [null], ENDPOINT, "--debug")).rejects.toThrow("Use an Azure subscription ID");
  await expect(f.codex("all", [null], "", "")).rejects.toThrow("Set the Azure resource or endpoint before refreshing deployments");
  expect(f.calls()).toHaveLength(4);
  f.readOnly();
});

test("an inventory belongs to its scope and to this run's memory only", async () => {
  const f = fixture();
  await f.codex("sp1");
  expect(f.d.view("sp1", "codex", { target: ENDPOINT }).options).toHaveLength(2);
  expect(f.d.view("all", "codex", { target: ENDPOINT })).toEqual({ busy: false, options: [], hint: IDLE });
  expect(f.d.view("m:local", "codex", { target: ENDPOINT }).options).toEqual([]);
  expect(f.d.view("sp1", "claude", { target: "example" }).options).toEqual([]);
  // read under one endpoint and subscription: shown under no other
  expect(f.d.view("sp1", "codex", { target: "https://different.openai.azure.com/openai/v1" })).toEqual({ busy: false, options: [], hint: IDLE });
  expect(f.d.view("sp1", "codex", { target: ENDPOINT, subscription: SUB })).toEqual({ busy: false, options: [], hint: IDLE });
  // a new run (a restart) starts with nothing and asks nothing until Refresh
  expect(f.make().view("sp1", "codex", { target: ENDPOINT })).toEqual({ busy: false, options: [], hint: IDLE });
  expect(f.calls()).toHaveLength(3);
});

test("a failed refresh clears the old choices, hides Azure CLI's words and leaves manual entry", async () => {
  const f = fixture();
  expect((await f.codex()).options).toHaveLength(2);
  const failing: [string[], string][] = [
    [["account"], "Cannot read the Azure CLI account. Check that az is installed and signed in on this machine and that the subscription is accessible. Manual entry is still available."],
    [["cognitiveservices", "account", "list"], "Cannot list Azure resources. Check Cognitive Services resource read access in this subscription, or enter the deployment manually."],
    [["cognitiveservices", "account", "deployment"], "Cannot list Azure deployments. Check deployment read access and connectivity, then refresh. Manual entry is still available."],
  ];
  for (const [fail, warn] of failing) {
    f.set({ fail, stderr: "private-token-do-not-display" });
    const view = await f.codex();
    expect(view).toEqual({ busy: false, options: [], hint: IDLE, warn });
    expect(JSON.stringify(f.d.view("all", "codex", { target: ENDPOINT }))).not.toContain("private-token-do-not-display");
  }
  // a deployment typed by hand needs no inventory, and is only checked for being a name
  expect(deploymentName("  manual-deployment ")).toBe("manual-deployment");
  expect(deploymentName("")).toBe("");
  expect(() => deploymentName("--model")).toThrow("explicit Azure deployment name");
  // no az on this machine at all
  const none = new AzureDeployments({ az: join(f.dir, "missing-az") });
  expect((await none.refresh({ scope: "all", kind: "codex", machines: [null], target: ENDPOINT })).warn).toBe(failing[0][1]);
  f.readOnly();
});

test("a response that lands after the configuration changed is dropped, and a second click joins the first", async () => {
  const f = fixture({ hold: true });
  const pending = f.codex();
  await f.entered();
  expect(f.d.view("all", "codex", { target: ENDPOINT })).toEqual({ busy: true, options: [], hint: IDLE });
  const again = f.codex(); // the same Refresh, clicked again
  await Bun.sleep(50);
  expect(f.calls()).toHaveLength(3);
  f.d.invalidate(); // the endpoint, resource or subscription changed
  expect(f.d.view("all", "codex", { target: ENDPOINT })).toEqual({ busy: false, options: [], hint: IDLE });
  f.release();
  expect(await pending).toEqual({ busy: false, options: [], hint: IDLE });
  expect(await again).toEqual({ busy: false, options: [], hint: IDLE });
  expect(f.d.view("all", "codex", { target: ENDPOINT })).toEqual({ busy: false, options: [], hint: IDLE });
  expect(f.calls()).toHaveLength(3);
});

test("a refresh for a new endpoint replaces one still running, whose late answer can't overwrite it", async () => {
  const f = fixture({ hold: true });
  const old = f.codex();
  await f.entered();
  const moved = "https://moved.openai.azure.com/openai/v1";
  f.set({ hold: false, resources: [{ name: "moved", resourceGroup: "moved-group" }], inventory: [deployment("moved-deployment", "OpenAI", { responses: "true" })] });
  const fresh = await f.codex("all", [null], moved);
  expect(fresh.options.map((o) => o.value)).toEqual(["moved-deployment"]);
  f.release();
  expect((await old).options).toEqual([]); // the older Refresh's own answer shows nothing under its old endpoint
  expect(f.d.view("all", "codex", { target: moved }).options.map((o) => o.value)).toEqual(["moved-deployment"]);
  expect(f.d.view("all", "codex", { target: ENDPOINT })).toEqual({ busy: false, options: [], hint: IDLE });
  expect(f.calls()).toHaveLength(6);
  f.readOnly();
});

test("discovery stays on this computer and Azure public cloud, and Everywhere needs exactly one machine", async () => {
  const f = fixture();
  expect(await f.codex("all", ["vm"])).toEqual({ busy: false, options: [], hint: IDLE, warn: "Azure discovery reads only this computer's Azure CLI. Enter the deployment manually for other machines." });
  await expect(f.codex("all", [])).rejects.toThrow("Choose one machine or space before discovering Azure deployments");
  await expect(f.codex("all", [null, "vm"])).rejects.toThrow("Choose one machine or space before discovering Azure deployments");
  expect(f.calls()).toEqual([]);
  f.set({ cloud: "AzureUSGovernment" });
  expect(await f.codex()).toEqual({ busy: false, options: [], hint: IDLE, warn: "Discovery supports Azure public cloud only. The host's Azure cloud and login were not changed." });
  expect(f.calls()).toEqual([SHOW]);
});

test("an empty inventory, an unreadable one and a resource that isn't uniquely there are different answers", async () => {
  const f = fixture({ inventory: [] });
  expect(await f.codex()).toEqual({ busy: false, options: [], subscription: SUB, checkedAt: 1_800_000_000_000, hint: `0 matching deployments. ${CHECKED}` });
  f.set({ inventory: {} });
  expect((await f.codex()).warn).toBe("Azure returned an unreadable deployment inventory. Try refreshing again.");
  const unique = "The configured resource was not uniquely found in this subscription. Check the resource and subscription, or enter the deployment manually.";
  f.set({ inventory: INVENTORY, resources: [{ name: "example", resourceGroup: "a" }, { name: "EXAMPLE", resourceGroup: "b" }] });
  expect((await f.codex()).warn).toBe(unique);
  f.set({ resources: [{ name: "another", resourceGroup: "other-group" }] });
  expect((await f.codex()).warn).toBe(unique);
  f.set({ resources: [{ name: "example", resourceGroup: "--subscription" }] }); // never passed on as an az option
  expect((await f.codex()).warn).toBe(unique);
  f.set({ resources: { value: [] } });
  expect((await f.codex()).warn).toBe("Azure returned an unreadable resource inventory. Try refreshing again.");
  expect(f.calls().filter((c) => c[2] === "deployment")).toHaveLength(2);
  f.readOnly();
});

test("an Azure CLI that doesn't answer in time is a failed refresh, not a hang", async () => {
  const f = fixture({ hold: true }, { timeoutMs: 300 });
  const view = await f.codex();
  f.release();
  expect(view).toEqual({ busy: false, options: [], hint: IDLE, warn: "Cannot list Azure deployments. Check deployment read access and connectivity, then refresh. Manual entry is still available." });
});

test("the binding's fields are judged as herdr-task judges them", () => {
  const cases = table.cases as { field: string; value: string; ok: boolean; kept?: string; resource?: string }[];
  expect([cases.length, cases.filter((c) => c.ok).length]).toEqual([33, 8]);
  for (const c of cases) {
    const kind: AzureKind = c.field.startsWith("codex") ? "codex" : "claude";
    const judge = c.field === "azure_subscription" ? () => discoverySubscription(c.value)
      : c.field.endsWith("_deployment") ? () => deploymentName(c.value) : () => discoveryResource(kind, c.value);
    if (!c.ok) { expect(judge, `${c.field} ${c.value}`).toThrow(); continue; }
    // discovery keeps a subscription id in lower case, a deployment's name as typed, and reads an endpoint's resource
    const kept = c.field === "azure_subscription" ? c.kept!.toLowerCase() : c.field.endsWith("_deployment") ? c.kept! : c.resource!;
    expect(judge(), `${c.field} ${c.value}`).toBe(kept);
  }
});
