// Changing a running agent's model, reasoning level or Fast in place (SHEP-181): no restart, the same conversation.
// Both CLIs switch mid-session through their own commands, typed into the agent's terminal as a person would:
//   Claude Code: /model <id>, /effort <level>, /fast on|off. Each also saves the choice as the default for new
//   sessions in ~/.claude/settings.json, so the keys it touched are put back afterwards (the running agent keeps the
//   new choice: it doesn't reread them).
//   Codex: /model opens a picker (model, then its reasoning level); "s" there applies it to this session only. /fast
//   toggles and saves service_tier in ~/.codex/config.toml, put back the same way.
// Another CLI or another permission mode still needs a restart (liveOK says which).
// `io` is where it runs: { send(text), keys(...names), screen(), readFile(rel), writeFile(rel, text), sleep(ms) }, rel
// under the agent's machine's home. readFile resolves the file's text, or null when there is no such file, and throws
// when it can't be read (or its machine can't be reached): then nothing is switched, as what a command saves there
// couldn't be put back. writeFile throws when the write fails: the switch then says the default stayed.

export const CLAUDE_SETTINGS = ".claude/settings.json";
export const CODEX_CONFIG = ".codex/config.toml";
const CLAUDE_KEYS = ["model", "effortLevel", "fastMode", "modelSettings"];
const CODEX_KEYS = ["model", "model_reasoning_effort", "service_tier"];
const LEVEL = { minimal: "Minimal", low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Max", ultra: "Ultra", none: "None" };

/** Whether the change from what runs (`from`: { agent, model, effort, fast, perm }) to `to` can happen in place:
 *  the same CLI and the same permission mode. */
export function liveOK(from, to) {
  return !!from && !!to && from.agent === to.agent && (!to.perm || !from.perm || to.perm === from.perm);
}

/** What changes: { model, effort, fast } (each only when it differs; model/effort '' for the CLI's default). A new
 *  model always says its level again: Claude Code keeps a level per model, so a model switch can move it. */
export function liveChanges(from, to) {
  const out = {};
  const model = to.model ?? "", effort = to.effort ?? "";
  if (model !== (from.model ?? "")) out.model = model;
  if (out.model !== undefined || effort !== (from.effort ?? "")) out.effort = effort;
  if (!!to.fast !== !!from.fast) out.fast = !!to.fast;
  return out;
}

/** Claude Code's commands for the changes, in order: [{ text, done: RegExp, fail?: RegExp }]. */
export function claudeCommands(ch) {
  const out = [];
  if (ch.model !== undefined) out.push({ text: `/model ${ch.model || "default"}`, done: /Set model to /, fail: /(?:Model .*not (?:found|available)|Invalid model|isn't available|not a valid model)[^\n]*/i });
  if (ch.effort !== undefined) out.push({ text: `/effort ${ch.effort || "auto"}`, done: /Set effort level to |Effort level set to /, fail: /Invalid (?:effort|argument)[^\n]*/i });
  if (ch.fast !== undefined) out.push({ text: `/fast ${ch.fast ? "on" : "off"}`, done: /Fast mode (?:ON|OFF)\b/, fail: /Fast mode unavailable:?[^\n]*/ });
  return out;
}

const echoed = (line, text) => line.replace(/^[\s❯>›»]+/, "").trimEnd() === text;
/** The screen's text after the newest line that echoes `text` as typed (the command's own answer), or null. */
export function after(screen, text) {
  const lines = String(screen ?? "").split("\n");
  for (let i = lines.length - 1; i >= 0; i--) if (echoed(lines[i], text)) return lines.slice(i + 1).join("\n");
  return null;
}
/** How many lines echo `text` as typed, or match `re`: what grows once a command was taken. */
export const echoes = (screen, text) => String(screen ?? "").split("\n").filter((l) => echoed(l, text)).length;
export const count = (screen, re) => String(screen ?? "").split("\n").filter((l) => re.test(l)).length;

/** Claude Code asking whether to switch a model whose conversation is cached ("Switch model?"): its Yes is first. */
export const claudeAsksSwitch = (screen) => /Switch model\?/.test(screen ?? "") && /❯\s*1\.\s*Yes/.test(screen ?? "");

/** The settings file with the keys a command touched as they were before (null: nothing to put back). Only those
 *  keys: anything else written meanwhile stays. Throws when either isn't a settings object: nothing could be put back. */
export function claudeRestore(before, now) {
  const b = JSON.parse(before || "{}"), n = JSON.parse(now || "{}");
  if (!n || typeof n !== "object" || !b || typeof b !== "object") throw new Error("not a settings object");
  let changed = false;
  for (const k of CLAUDE_KEYS) {
    if (JSON.stringify(b[k]) === JSON.stringify(n[k])) continue;
    changed = true;
    if (k in b) n[k] = b[k]; else delete n[k];
  }
  return changed ? JSON.stringify(n, null, 2) + (String(now).endsWith("\n") ? "\n" : "") : null;
}

/** config.toml's top-level lines for `keys` as they were before (null: nothing to put back). */
export function codexRestore(before, now) {
  const top = (text) => {
    const lines = String(text ?? "").split("\n"), end = lines.findIndex((l) => /^\s*\[/.test(l));
    return { lines, end: end < 0 ? lines.length : end };
  };
  const key = (l) => /^\s*([\w.-]+)\s*=/.exec(l)?.[1];
  const b = top(before), n = top(now);
  const was = new Map(b.lines.slice(0, b.end).filter((l) => CODEX_KEYS.includes(key(l))).map((l) => [key(l), l]));
  const head = n.lines.slice(0, n.end), out = [];
  let changed = false;
  for (const l of head) {
    const k = key(l);
    if (!CODEX_KEYS.includes(k)) { out.push(l); continue; }
    if (was.get(k) !== l) changed = true;
    if (was.has(k)) { out.push(was.get(k)); was.delete(k); }
  }
  // a key it removed: back where the top-level lines end (before the first table)
  if (was.size) {
    changed = true;
    let at = out.length;
    while (at > 0 && out[at - 1].trim() === "") at--;
    out.splice(at, 0, ...was.values());
  }
  return changed ? [...out, ...n.lines.slice(n.end)].join("\n") : null;
}

/** A Codex picker's numbered rows on screen: [{ n, label, sel, current, dflt }] (the newest picker only). */
export function codexRows(screen) {
  const lines = String(screen ?? "").split("\n");
  let start = -1;
  for (let i = lines.length - 1; i >= 0; i--) if (/^\s*(Select Model|Select Reasoning|Advanced Reasoning)/.test(lines[i])) { start = i; break; }
  if (start < 0) return [];
  const rows = [];
  for (const l of lines.slice(start + 1)) {
    const m = /^\s*(›)?\s*(\d+)\.\s+(.+?)(?:\s{2,}.*)?$/.exec(l);
    if (!m) continue;
    const words = m[3].trim();
    rows.push({ n: Number(m[2]), sel: !!m[1], label: words.replace(/\s*\((current|default)\)/g, "").trim(), current: /\(current\)/.test(words), dflt: /\(default\)/.test(words) });
  }
  return rows;
}

/** Which picker shows: "model", "effort", "more" (Max and Ultra) or null. */
export function codexPicker(screen) {
  const lines = String(screen ?? "").split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    if (/^\s*Select Model/.test(lines[i])) return "model";
    if (/^\s*Select Reasoning/.test(lines[i])) return "effort";
    if (/^\s*Advanced Reasoning/.test(lines[i])) return "more";
    if (/^\s*›\s*Ask Codex|^\s*[›»]\s*$/.test(lines[i])) return null;
  }
  return null;
}

const squash = (s) => String(s ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");
/** The row of Codex's model picker for a model (by its id or its label as the picker says it). */
export function codexModelRow(rows, id, label) {
  const want = [squash(id), squash(label)].filter(Boolean);
  return rows.find((r) => want.includes(squash(r.label))) ?? null;
}
/** The row of Codex's level picker for a level ('' the model's default); "more" when it is behind More reasoning. */
export function codexEffortRow(rows, effort) {
  if (!effort) return rows.find((r) => r.dflt) ?? null;
  const name = squash(LEVEL[effort] ?? effort);
  return rows.find((r) => squash(r.label) === name) ?? (rows.find((r) => /^More reasoning/i.test(r.label)) ? "more" : null);
}

/** The keys that move a picker's highlight from its row to row n. */
export function moveTo(rows, n) {
  const at = rows.find((r) => r.sel)?.n ?? rows[0]?.n ?? n;
  return Array(Math.abs(n - at)).fill(n > at ? "down" : "up");
}

async function waitFor(io, test, ms = 8000) {
  for (let t = 0; t < ms; t += 250) {
    const s = await io.screen();
    if (test(s)) return s;
    await io.sleep(250);
  }
  return null;
}

/** What a file held before the commands: its text, "" when it didn't exist (a command may make it). One that can't be
 *  read, or that `check` can't take as the CLI's settings, stops the switch here, before anything is typed. */
async function prior(io, rel, check = () => {}) {
  try {
    const text = (await io.readFile(rel)) ?? "";
    check(text);
    return text;
  } catch {
    throw new Error(`Can't switch it in place: ~/${rel} couldn't be read, so the default a switch saves there couldn't be put back.`);
  }
}

/** The keys the commands touched, put back (restore(before, now): the file's new text, or null when nothing changed). Its
 *  words when that couldn't be done, else null. */
async function putBack(io, rel, before, restore) {
  // its save lands with its answer; a moment more, then the keys it touched go back
  await io.sleep(300);
  try {
    const now = await io.readFile(rel);
    const back = now === null ? null : restore(before, now);
    if (back !== null) await io.writeFile(rel, back);
    return null;
  } catch {
    return `~/${rel} couldn't be put back, so new sessions may start on this choice.`;
  }
}

/** The switch's outcome: a command's failure (with the default not put back, said too; after an earlier command took,
 *  said as a switch part of the way), or a switch whose default stayed. `switched` on the error: what runs did change. */
function outcome(failed, lost, took) {
  if (failed) {
    const words = lost ? `${failed.message} Also, ${lost}` : failed.message;
    throw took ? Object.assign(new Error(`It switched part of the way, then: ${words}`), { switched: true }) : lost ? new Error(words) : failed;
  }
  if (lost) throw Object.assign(new Error(`It switched, but ${lost}`), { switched: true });
}

/** Claude Code: the commands typed one by one, each waited for; its default put back. Resolves with what it ran. */
async function claude(io, ch) {
  const before = await prior(io, CLAUDE_SETTINGS, (text) => claudeRestore(text, text));
  let failed = null, took = false;
  try {
    for (const c of claudeCommands(ch)) {
      // an answer counts only after this command's own echo (the same command may be on screen from before)
      const was = echoes(await io.screen(), c.text);
      await io.send(c.text);
      let asked = false;
      const s = await waitFor(io, (s) => {
        const a = echoes(s, c.text) > was ? after(s, c.text) : null;
        if (a !== null && (c.done.test(a) || c.fail?.test(a))) return true;
        // a model whose conversation is cached asks first: Yes
        if (!asked && claudeAsksSwitch(s)) { asked = true; void io.keys("enter"); }
        return false;
      });
      const a = s ? after(s, c.text) : null;
      if (!s || a === null) throw new Error(`Claude Code didn't answer ${c.text.split(" ")[0]}.`);
      const bad = c.fail && !c.done.test(a) ? c.fail.exec(a) : null;
      if (bad) throw new Error(bad[0].trim());
      took = true;
    }
  } catch (e) {
    failed = e;
  }
  outcome(failed, await putBack(io, CLAUDE_SETTINGS, before, claudeRestore), took);
}

/** Codex: /model's two pickers (its level for this session only, "s"), then /fast; config.toml put back. */
async function codex(io, ch, labels) {
  const before = await prior(io, CODEX_CONFIG);
  const pick = async (rows, n) => {
    for (const k of moveTo(rows, n)) await io.keys(k);
    await io.sleep(150);
  };
  let failed = null, took = false;
  try {
    const CHANGED = /^\s*•\s*Model changed to /, TIER = /^\s*•\s*Service tier set to /;
    if (ch.model !== undefined || ch.effort !== undefined) {
      const was = count(await io.screen(), CHANGED);
      await io.send("/model");
      let s = await waitFor(io, (s) => codexPicker(s) === "model");
      if (!s) throw new Error("Codex didn't open its model list.");
      let rows = codexRows(s);
      const want = ch.model !== undefined ? ch.model : labels.model;
      const row = want ? codexModelRow(rows, want, labels.names?.[want]) : rows.find((r) => r.current) ?? rows.find((r) => r.dflt);
      if (!row) { await io.keys("esc"); throw new Error(`${labels.names?.[want] ?? want ?? "That model"} isn't in Codex's list.`); }
      await pick(rows, row.n);
      await io.keys("enter");
      s = await waitFor(io, (s) => codexPicker(s) === "effort" || count(s, CHANGED) > was);
      if (!s) { await io.keys("esc"); throw new Error("Codex didn't offer its levels."); }
      if (codexPicker(s) === "effort") {
        rows = codexRows(s);
        let r = codexEffortRow(rows, ch.effort ?? labels.effort ?? "");
        if (r === "more") {
          await pick(rows, rows.find((x) => /^More reasoning/i.test(x.label)).n);
          await io.keys("enter");
          s = await waitFor(io, (s) => codexPicker(s) === "more");
          rows = s ? codexRows(s) : [];
          r = codexEffortRow(rows, ch.effort);
        }
        if (!r || r === "more") { await io.keys("esc", "esc", "esc"); throw new Error(`Codex doesn't offer ${LEVEL[ch.effort] ?? ch.effort} for that model.`); }
        await pick(rows, r.n);
        // s: this session only (Enter would save it as the default too)
        await io.keys("s");
        s = await waitFor(io, (s) => count(s, CHANGED) > was);
        if (!s) throw new Error("Codex didn't confirm the change.");
      }
      took = true;
    }
    if (ch.fast !== undefined) {
      const was = count(await io.screen(), TIER);
      await io.send("/fast");
      const s = await waitFor(io, (s) => count(s, TIER) > was);
      if (!s) throw new Error("Codex didn't confirm Fast.");
      took = true;
      const said = String(s).split("\n").filter((l) => TIER.test(l)).pop();
      const on = /set to (fast|priority)/i.test(said);
      // a toggle: once more if it went the other way
      if (on !== ch.fast) {
        await io.sleep(300);
        await io.send("/fast");
        await io.sleep(1000);
      }
    }
  } catch (e) {
    failed = e;
  }
  outcome(failed, await putBack(io, CODEX_CONFIG, before, codexRestore), took);
}

/** Switches the agent in place. `labels`: Codex's { names: { id: label }, model, effort } (the picker's words for
 *  its models, and what runs now). Throws with plain words when it can't; `switched` on the error when it did switch but
 *  the default it saved couldn't be put back. */
export async function switchLive(io, kind, from, to, labels = {}) {
  const ch = liveChanges(from, to);
  if (!Object.keys(ch).length) return ch;
  if (kind === "claude") await claude(io, ch);
  else await codex(io, ch, { ...labels, model: from.model, effort: to.effort });
  return ch;
}
