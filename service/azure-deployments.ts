// Azure deployment discovery for Settings' deployment pickers (Claude Code and Codex): an explicit Refresh reads the
// deployments of one configured resource through this machine's own Azure CLI and its existing login. Three read-only
// commands, nothing else: az account show, az cognitiveservices account list, az cognitiveservices account deployment
// list. It never signs in, starts an agent, sends a model request, or picks or changes a deployment: this module holds
// no settings writer and no terminal. What it finds is an inventory, not proof of an account, of inference access or
// of what a deployment's model supports; a deployment typed by hand (deploymentName) needs none of it.
//
// Results live in memory only, per settings scope and CLI, for the configuration they were read under (resource or
// endpoint, and discovery subscription). A view under another configuration shows nothing, a response that lands after
// the configuration changed is dropped, and a failed refresh clears what was there. Azure CLI's own words never leave
// here: a failure is one of the fixed lines below.

export type AzureKind = "claude" | "codex";
/** One deployment a picker may offer: its id (the value kept), and separately the model it serves. */
export type DeploymentOption = { value: string; label: string; model: string; version?: string };
/** What a picker shows for one scope and CLI now. */
export type DiscoveryView = { busy: boolean; options: DeploymentOption[]; hint: string; warn?: string; subscription?: string; checkedAt?: number };
/** The nonsecret configuration discovery reads under: Claude's resource name or Codex's endpoint, and the optional
 *  discovery subscription (empty: the Azure CLI's own). */
export type DiscoveryConfig = { target: string; subscription?: string };
/** A Refresh: the settings scope ("all", a space's id, "m:<machine>"), and the machines agents at that scope run on
 *  (null or "local": this computer). */
export type DiscoveryRequest = DiscoveryConfig & { scope: string; kind: AzureKind; machines: (string | null)[] };
/** Runs one Azure CLI command and gives its JSON; throws when it fails (its words are never kept). */
type AzRun = (args: string[]) => Promise<unknown>;

const DEPLOYMENT = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const RESOURCE = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;
const SUBSCRIPTION = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const ENDPOINT = /^https:\/\/([a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)\.openai\.azure\.com\/openai\/v1\/?$/;
const GROUP = /^[\w.()][\w.()-]{0,89}$/;
const LOCAL = "local";
const MAX_JSON = 4 << 20;

const IDLE = "Refresh reads this resource's deployments with this machine's Azure CLI login, or type a deployment's name. Changes apply to new conversations; existing ones keep theirs.";
const NOT_A_TEST = "Inventory is not a sign-in, model-request or tool-use test.";
const NO_TARGET = "Set the Azure resource or endpoint before refreshing deployments";
const NO_SUBSCRIPTION = "Use an Azure subscription ID (a UUID), or leave it empty for the host's Azure CLI subscription";
const ONE_MACHINE = "Choose one machine or space before discovering Azure deployments";
const NO_DEPLOYMENT = "Set an explicit Azure deployment name (letters, digits, dots, dashes and underscores)";
const FAILED = "Azure discovery failed. Enter the deployment manually or refresh again.";
const REPAIR = {
  remote: "Azure discovery reads only this computer's Azure CLI. Enter the deployment manually for other machines.",
  account: "Cannot read the Azure CLI account. Check that az is installed and signed in on this machine and that the subscription is accessible. Manual entry is still available.",
  cloud: "Discovery supports Azure public cloud only. The host's Azure cloud and login were not changed.",
  identity: "Azure CLI returned an unreadable subscription identity. Check its account configuration.",
  other: "Azure CLI answered for another subscription than the one set. Check the discovery subscription.",
  resources: "Cannot list Azure resources. Check Cognitive Services resource read access in this subscription, or enter the deployment manually.",
  resourcesShape: "Azure returned an unreadable resource inventory. Try refreshing again.",
  unique: "The configured resource was not uniquely found in this subscription. Check the resource and subscription, or enter the deployment manually.",
  deployments: "Cannot list Azure deployments. Check deployment read access and connectivity, then refresh. Manual entry is still available.",
  deploymentsShape: "Azure returned an unreadable deployment inventory. Try refreshing again.",
};

/** A failure whose words are one of this module's own fixed lines: the only kind a view ever shows. */
class Refusal extends Error {}

const rec = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);

/** A deployment's name as Settings keeps it, typed by hand or picked: discovery isn't needed for it. "" stays "". */
export function deploymentName(value: string): string {
  const v = value.trim();
  if (v && !DEPLOYMENT.test(v)) throw new Error(NO_DEPLOYMENT);
  return v;
}

/** The resource discovery reads for a CLI: Claude's resource name itself, Codex's from its public-cloud endpoint. */
export function discoveryResource(kind: AzureKind, target: string): string {
  const v = target.trim();
  if (!v) throw new Error(NO_TARGET);
  if (kind === "claude") {
    if (!RESOURCE.test(v)) throw new Error("Set the Claude Azure resource name, not a URL");
    return v;
  }
  const m = ENDPOINT.exec(v);
  if (!m) throw new Error("Use https://RESOURCE.openai.azure.com/openai/v1 without credentials or query parameters");
  return m[1];
}

/** The discovery subscription as kept: a UUID, or "" for the Azure CLI's own. */
export function discoverySubscription(value: string | undefined): string {
  const v = (value ?? "").trim();
  if (v && !SUBSCRIPTION.test(v)) throw new Error(NO_SUBSCRIPTION);
  return v.toLowerCase();
}

/** The Azure CLI, as JSON: stderr is never read, a failure or a timeout only throws. */
function azCli(bin: string, timeoutMs: number): AzRun {
  return async (args) => {
    const p = Bun.spawn([bin, ...args, "--output", "json", "--only-show-errors"], { stdout: "pipe", stderr: "ignore", stdin: "ignore" });
    const timer = setTimeout(() => p.kill(), timeoutMs);
    try {
      const [text, code] = await Promise.all([new Response(p.stdout).text(), p.exited]);
      if (code !== 0 || text.length > MAX_JSON) throw new Error("az failed");
      return JSON.parse(text);
    } finally { clearTimeout(timer); }
  };
}

type Entry = { key: string; busy: boolean; pending: Promise<void>; options: DeploymentOption[]; subscription?: string; checkedAt?: number; warn?: string };

export class AzureDeployments {
  /** `${scope}\0${kind}` -> what the last Refresh under one configuration found. Memory only: gone on restart. */
  private entries = new Map<string, Entry>();
  private run: AzRun;
  private now: () => number;
  private changed: () => void;

  constructor(o: { az?: string; timeoutMs?: number; now?: () => number; changed?: () => void } = {}) {
    this.run = azCli(o.az ?? "az", o.timeoutMs ?? 30_000);
    this.now = o.now ?? Date.now;
    this.changed = o.changed ?? (() => {});
  }

  private static key(kind: AzureKind, config: DiscoveryConfig): string {
    return `${kind}\n${discoveryResource(kind, config.target).toLowerCase()}\n${discoverySubscription(config.subscription)}`;
  }

  /** What the picker shows now, under the configuration in force. Never asks Azure: only Refresh does. A result read
   *  under another resource, endpoint or subscription isn't shown. */
  view(scope: string, kind: AzureKind, current: DiscoveryConfig): DiscoveryView {
    const e = this.entries.get(`${scope}\0${kind}`);
    let key: string | null = null;
    try { key = AzureDeployments.key(kind, current); } catch {}
    if (!e || e.key !== key) return { busy: false, options: [], hint: IDLE };
    const hint = e.checkedAt === undefined ? IDLE
      : `${e.options.length} matching deployment${e.options.length === 1 ? "" : "s"}. Subscription ${e.subscription}. Checked ${new Date(e.checkedAt).toISOString()}. ${NOT_A_TEST}`;
    return { busy: e.busy, options: e.options.map((o) => ({ ...o })), hint, ...(e.warn ? { warn: e.warn } : {}),
      ...(e.subscription ? { subscription: e.subscription } : {}), ...(e.checkedAt === undefined ? {} : { checkedAt: e.checkedAt }) };
  }

  /** The resource, endpoint or discovery subscription changed at some scope (scopes inherit, so every scope's result
   *  goes): a response still on its way finds its place gone and is dropped. */
  invalidate() {
    if (!this.entries.size) return;
    this.entries.clear();
    this.changed();
  }

  /** Refresh, asked for by the person: reads the inventory for this scope and CLI. Throws before asking Azure when the
   *  request can't be one (nothing set, a bad subscription id, no single machine); any failure after that clears the
   *  scope's choices and leaves one fixed line in the view. A second Refresh for this computer under the same
   *  configuration while one runs joins it; one for another configuration or another machine replaces it, and the
   *  older response is dropped when it lands. */
  async refresh(req: DiscoveryRequest): Promise<DiscoveryView> {
    const resource = discoveryResource(req.kind, req.target), subscription = discoverySubscription(req.subscription);
    if (req.machines.length !== 1) throw new Error(ONE_MACHINE);
    const id = `${req.scope}\0${req.kind}`, key = AzureDeployments.key(req.kind, req);
    const local = req.machines[0] === null || req.machines[0] === LOCAL;
    const running = this.entries.get(id);
    // The key names no machine, so only a Refresh for this computer may join: another machine's must get its own
    // refusal, never this computer's inventory. (A busy entry is always local: a refusal settles before anything waits.)
    if (local && running?.busy && running.key === key) { await running.pending; return this.view(req.scope, req.kind, req); }
    const entry: Entry = { key, busy: true, options: [], pending: Promise.resolve() };
    this.entries.set(id, entry);
    this.changed();
    entry.pending = (async () => {
      let found: { options: DeploymentOption[]; subscription: string } | null = null, warn: string | undefined;
      try {
        if (!local) throw new Refusal(REPAIR.remote);
        found = await this.discover(req.kind, resource, subscription);
      } catch (e) { warn = e instanceof Refusal ? e.message : FAILED; }
      entry.busy = false;
      // Replaced by a newer Refresh or dropped by a configuration change: this response is stale.
      if (this.entries.get(id) !== entry) return;
      if (found) { entry.options = found.options; entry.subscription = found.subscription; entry.checkedAt = this.now(); }
      else entry.warn = warn;
      this.changed();
    })();
    await entry.pending;
    return this.view(req.scope, req.kind, req);
  }

  private async az(args: string[], repair: string): Promise<unknown> {
    try { return await this.run(args); } catch { throw new Refusal(repair); }
  }

  private async discover(kind: AzureKind, resource: string, subscription: string) {
    const account = rec(await this.az(["account", "show", ...(subscription ? ["--subscription", subscription] : []), "--query", "{id:id,environmentName:environmentName}"], REPAIR.account));
    if (account?.environmentName !== "AzureCloud") throw new Refusal(REPAIR.cloud);
    const sub = typeof account.id === "string" && SUBSCRIPTION.test(account.id) ? account.id.toLowerCase() : null;
    if (!sub) throw new Refusal(REPAIR.identity);
    if (subscription && sub !== subscription) throw new Refusal(REPAIR.other);
    // Every later read names the resolved subscription itself: the Azure CLI's default is never relied on or changed.
    const scope = ["--subscription", sub];
    const accounts = await this.az(["cognitiveservices", "account", "list", ...scope, "--query", "[].{name:name,resourceGroup:resourceGroup}"], REPAIR.resources);
    if (!Array.isArray(accounts)) throw new Refusal(REPAIR.resourcesShape);
    const matches = accounts.map(rec).filter((a) => typeof a?.name === "string" && a.name.toLowerCase() === resource.toLowerCase());
    const group = matches.length === 1 ? matches[0]?.resourceGroup : null;
    if (typeof group !== "string" || !GROUP.test(group)) throw new Refusal(REPAIR.unique);
    const inventory = await this.az(["cognitiveservices", "account", "deployment", "list", "--name", resource, "--resource-group", group, ...scope,
      "--query", "[].{name:name,properties:{model:properties.model,provisioningState:properties.provisioningState,capabilities:properties.capabilities}}"], REPAIR.deployments);
    if (!Array.isArray(inventory)) throw new Refusal(REPAIR.deploymentsShape);
    // Only a deployment that is ready, in this CLI's format, and says it serves this CLI's API. One without capability
    // metadata is left out (it can still be typed by hand).
    const format = kind === "codex" ? "OpenAI" : "Anthropic", capability = kind === "codex" ? "responses" : "chatCompletion";
    const options: DeploymentOption[] = [];
    for (const item of inventory.map(rec)) {
      const p = rec(item?.properties), model = rec(p?.model), can = rec(p?.capabilities)?.[capability];
      if (!item || !p || !model || typeof item.name !== "string" || !DEPLOYMENT.test(item.name)) continue;
      if (p.provisioningState !== "Succeeded" || model.format !== format || !(can === "true" || can === true)) continue;
      if (typeof model.name !== "string" || !model.name || model.name.length > 128) continue;
      const version = typeof model.version === "string" && model.version ? model.version.slice(0, 64) : undefined;
      options.push({ value: item.name, label: `${item.name} · ${model.name}${version ? ` (${version})` : ""}`, model: model.name, ...(version ? { version } : {}) });
    }
    options.sort((a, b) => (a.value < b.value ? -1 : a.value > b.value ? 1 : 0));
    return { options, subscription: sub };
  }
}
