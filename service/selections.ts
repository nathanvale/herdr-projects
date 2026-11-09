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
export type TaskChange = { agent?: string; deployment?: string; model?: string; effort?: string; default?: boolean; revision?: string };

/** A task's new-start selection: shown (change null), or saved (only with the revision it was shown at). On Azure, each
 *  CLI's deployment list as `menus`. */
export async function taskSelection(settings: Settings, t: TaskRef, change: TaskChange | null, dflts: any) {
  const args = [...(t.machine ? ["--on", t.machine] : []), "select", t.ref, "--folder", t.folder];
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
  return { ok: true, ...v, menus };
}

/** What an Assistant's new start in a space can pick from: herdr-task's route, each CLI's routing, the Assistant's
 *  deployment and the revision a pick is bound to (provider show), and on Azure each CLI's list. */
export async function assistantChoices(settings: Settings, space: { id: string; folder?: string | null } | null, dflts: any) {
  const v = await ask(["provider", "show", "--role", "coordinator", ...(space ? ["--space", space.id.split("/").pop()!] : []),
    ...(space?.folder ? ["--folder", space.folder] : [])]);
  const keep = Object.fromEntries(KINDS.map((k) => [k, [v.clis?.[k]?.deployment]])) as Record<Kind, string[]>;
  return { ok: true, ...v, menus: v.route === "azure-foundry" ? menusFor(settings, space?.id ?? null, keep, dflts) : null };
}
