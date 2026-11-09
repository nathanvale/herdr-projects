// Azure Foundry new-start selectors (A2): a task's save-only choice before its first start (the Tasks panel's row
// menu, through `herdr-task select`) and what an Assistant's new start can pick from (the window's chat and the web's,
// through `herdr-task provider show`). herdr-task owns the choice, its revision and the routing it is bound to; this
// module only adds what Refresh found (Settings' memory-only inventory) as each CLI's list, with effort levels where
// the deployment's model is one the CLI's own catalogue knows (core/agents.js azureMenu). Nothing here starts an agent,
// sends a prompt, signs in, or changes a hold: a save is the task's choice alone, and only when its revision is current.
import * as AG from "../core/agents.js";
import type { Settings } from "./settings.ts";

const { azureMenu } = AG as any;
type Kind = "claude" | "codex";
const KINDS: Kind[] = ["claude", "codex"];
/** herdr-task on PATH, or a test's stand-in (SHEPHERDR_HERDR_TASK, as service/spaces.ts). */
const herdrTask = () => process.env.SHEPHERDR_HERDR_TASK || "herdr-task";

async function run(argv: string[]) {
  const p = Bun.spawn(argv, { stdout: "pipe", stderr: "pipe", stdin: "ignore" });
  const [out, err] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text()]);
  return { code: await p.exited, out, err };
}

/** herdr-task's JSON answer, or its refusal's own words as an Error (never Azure CLI's or a credential's: it says none). */
async function ask(args: string[]) {
  const r = await run([herdrTask(), ...args, "--json"]);
  let out: any = null;
  try { out = JSON.parse(r.out || "null"); } catch {}
  if (r.code !== 0 || !out || out.error) throw new Error(out?.error || r.err.trim().split("\n").pop() || "herdr-task refused it.");
  return out;
}

/** Each CLI's list at a space (null: Everywhere): what Refresh found at the space itself, else Everywhere's only when it
 *  was read under the space's own configuration (Settings.discoveryFor), with the saved deployments kept in it. */
export function menusFor(settings: Settings, space: string | null, keep: Record<Kind, (string | null | undefined)[]>, dflts: any) {
  return Object.fromEntries(KINDS.map((k) => [k, azureMenu(k, settings.discoveryFor(space, k).options, (keep[k] ?? []).filter(Boolean), dflts?.[k])]));
}

export type TaskRef = { ref: string; folder: string; machine: string | null; space?: string | null };
/** inventory: the Refresh list's revision a deployment picked from it was shown with (none for one typed by hand) */
export type TaskChange = { agent?: string; deployment?: string; model?: string; effort?: string; default?: boolean; revision?: string; inventory?: string };

/** A pick from a list read under another resource, endpoint or subscription (Settings.discoveryFor's revision). */
export const STALE_LIST = "Those deployments were found under another resource, endpoint or subscription. Nothing was saved; refresh and choose again.";
/** A space's web Assistant pick changed (saved, cleared or used) since its menu showed it. */
export const STALE_PICK = "This space's Assistant pick changed since this menu was opened. Nothing was saved; open it again.";

/** A web Assistant pick's own revision: what a save or a reset must quote, so an older menu can't overwrite a newer pick. */
export function pickRevision(pick: unknown) {
  return new Bun.CryptoHasher("sha256").update(JSON.stringify(pick ?? null)).digest("hex").slice(0, 16);
}

/** assistant.picks with only this space's pick changed (null: cleared), refused when it isn't the one the menu showed
 *  (expected: its pickRevision). Run inside the shared store's update, so each retry sees the current document. */
export function withPick(picks: Record<string, unknown> | undefined, space: string, pick: unknown | null, expected: string) {
  const cur = { ...(picks ?? {}) };
  if (pickRevision(cur[space]) !== expected) throw new Error(STALE_PICK);
  if (pick === null) delete cur[space]; else cur[space] = pick;
  return cur;
}

/** assistant.picks without this space's pick once its start used it, only while it is still that same pick (a newer one
 *  saved meanwhile stays), every other space's kept. */
export function withoutUsedPick(picks: Record<string, unknown> | undefined, space: string, used: unknown) {
  const cur = { ...(picks ?? {}) };
  if (JSON.stringify(cur[space]) === JSON.stringify(used)) delete cur[space];
  return cur;
}

/** A task's new-start selection: shown (change null), or saved (only with the revision it was shown at). On Azure, each
 *  CLI's deployment list as `menus`. */
export async function taskSelection(settings: Settings, t: TaskRef, change: TaskChange | null, dflts: any) {
  // its space when known, so the choice is judged by the settings its start reads (else the folder's own layers)
  const args = [...(t.machine ? ["--on", t.machine] : []), "select", t.ref, "--folder", t.folder, ...(t.space ? ["--space", String(t.space).split("/").pop()!] : [])];
  // A deployment picked from Refresh's list must come from the list in force now (typed by hand needs none).
  if (change && !change.default && change.deployment && change.inventory !== undefined && (change.agent === "claude" || change.agent === "codex")
      && change.inventory !== settings.discoveryFor(t.space ?? null, change.agent).revision) throw new Error(STALE_LIST);
  if (change) {
    if (change.default) args.push("--default");
    else {
      if (change.agent !== undefined) args.push("--agent", String(change.agent));
      if (change.deployment !== undefined) args.push("--deployment", String(change.deployment));
      if (change.model !== undefined) args.push("--model", String(change.model));
      if (change.effort !== undefined) args.push("--effort", String(change.effort));
    }
    args.push("--revision", String(change.revision ?? ""));
  }
  const v = await ask(args);
  // Another machine's task: Refresh reads this computer's Azure CLI only, so its lists keep the saved ones alone.
  const keep = Object.fromEntries(KINDS.map((k) => [k, [v.selection?.agent === k ? v.selection.deployment : null, v.clis?.[k]?.deployment]])) as Record<Kind, string[]>;
  const menus = v.route === "azure-foundry" ? (t.machine ? Object.fromEntries(KINDS.map((k) => [k, azureMenu(k, [], keep[k], dflts?.[k])])) : menusFor(settings, t.space ?? null, keep, dflts)) : null;
  // each CLI's list revision (and what it lists), which a pick from the list carries back
  const inventory = menus && !t.machine ? Object.fromEntries(KINDS.map((k) => [k, settings.discoveryFor(t.space ?? null, k).revision])) : null;
  const listed = menus && !t.machine ? Object.fromEntries(KINDS.map((k) => [k, settings.discoveryFor(t.space ?? null, k).options.map((o: any) => o.value)])) : null;
  return { ok: true, ...v, menus, ...(inventory ? { inventory, listed } : {}) };
}

/** What an Assistant's new start in a space can pick from: herdr-task's route, each CLI's routing, the Assistant's
 *  deployment and the revision a pick is bound to (provider show), and on Azure each CLI's list. */
export async function assistantChoices(settings: Settings, space: { id: string; folder?: string | null } | null, dflts: any) {
  const v = await ask(["provider", "show", "--role", "coordinator", ...(space ? ["--space", space.id.split("/").pop()!] : []),
    ...(space?.folder ? ["--folder", space.folder] : [])]);
  const keep = Object.fromEntries(KINDS.map((k) => [k, [v.clis?.[k]?.deployment]])) as Record<Kind, string[]>;
  return { ok: true, ...v, menus: v.route === "azure-foundry" ? menusFor(settings, space?.id ?? null, keep, dflts) : null };
}
