// Agents > Provider (A2): Personal or Azure Foundry at Everywhere or a space, as herdr-task reads it (herdr_task/
// providers.py: the "provider" section, its fields and their checks), with the same rows and words as the web app's
// (core/settings.js PROVIDER). These are the person's own controls: herdr-task and agents never write them. A field a
// level leaves out follows the level above, "" is that level's own empty value, and Reset removes it. On Azure, each
// CLI's deployment is typed, or picked from what Refresh found: Refresh asks this machine's Shepherdr service, which
// reads the resource's deployments with this machine's Azure CLI login (service/azure-deployments.ts) and selects
// nothing. A list read under another resource, endpoint or subscription is dropped, never saved from.

import { div } from "gpui-kit";
import { v_flex, h_flex, InputState, Input } from "gpui-base";
import { PROVIDER, providerValue, DISCOVERY_FIELDS } from "./core/settings.js";
import { button, menuRow, segmented, TEXT } from "./ui.js";
import { localService, localToken } from "./local.js";

const TEXT_FIELDS = PROVIDER.rows.filter((r) => !r.choices).map((r) => r.field);

// The value a scope's chain gives a field ("" when none sets it).
const valueOf = (view, field, scope = view.scope ?? null) => {
  const v = view.chain("provider", field, scope).find((x) => x.value !== undefined)?.value;
  return typeof v === "string" ? v : "";
};
// What a Refresh's list was read under at a scope: a pick from it is refused once this changes.
const configOf = (view, scope = view.scope ?? null) => JSON.stringify(DISCOVERY_FIELDS.map((f) => valueOf(view, f, scope)));
const STALE = "Those deployments were found under another resource, endpoint or subscription. Nothing was saved; refresh again.";

// Made in the window's init (an input needs a live host call): a box per typed field, and what Refresh found.
export function providerInit(view) {
  const p = { boxes: {}, err: {}, scope: undefined, focus: {}, setting: false, found: {}, busy: {} };
  for (const field of TEXT_FIELDS) {
    const box = InputState.new({ placeholder: PROVIDER.rows.find((r) => r.field === field).placeholder ?? "" });
    box.on("change", (_e, cx) => { if (!p.setting) { p.err[field] = ""; cx.notify(); } });
    box.on("focus", (_e, cx) => { p.focus[field] = true; cx.notify(); });
    box.on("blur", (_e, cx) => { p.focus[field] = false; save(view, p, field, box.value(), cx); });
    box.on("submit", (_e, cx) => save(view, p, field, box.value(), cx));
    p.boxes[field] = box;
  }
  return p;
}

// Checked as herdr-task checks it (never repeating a refused value: it could be a pasted secret), then kept at the level
// it was entered at (captured now: the write reloads the file first, and the person may switch levels meanwhile). A pick
// from Refresh's list (expect: the configuration it was read under) is checked again against that reloaded file and
// refused if another window or the web changed it. As view.set: the same as what the level inherits follows again.
function save(view, p, field, word, cx, expect = null) {
  let v;
  try { v = providerValue(field, word); } catch (e) { p.err[field] = e.message; return cx.notify(); }
  const scope = view.scope ?? null;
  if (v === valueOf(view, field, scope)) return cx.notify();
  p.err[field] = "";
  view.change((next) => {
    if (expect !== null && configOf(view, scope) !== expect) { p.err[field] = STALE; return false; }
    const inherited = view.chain("provider", field, scope).slice(1).find((x) => x.value !== undefined)?.value ?? null;
    if (JSON.stringify(v) === JSON.stringify(inherited)) return view.drop(view.layerOf(next, scope), "provider", field);
    const tg = view.target(next, scope);
    tg.provider = { ...(tg.provider ?? {}), [field]: v };
  }, cx);
  // A resource, endpoint, subscription or route changed: every list Refresh read here is stale now.
  if (DISCOVERY_FIELDS.includes(field)) p.found = {};
}

// Refresh: this machine's service reads one CLI's deployments at this level.
async function refresh(view, p, kind, cx) {
  const at = `${view.scope ?? "all"}:${kind}`, config = configOf(view);
  p.busy[at] = true;
  p.found[at] = null;
  cx.notify();
  let out = null;
  try {
    const token = await localToken();
    const svc = token ? await localService().catch(() => null) : null;
    if (!svc) out = { warn: "Refresh needs Shepherdr's service running here. Type the deployment's name instead." };
    else {
      const r = await fetch(`${svc.base}/api/action`, { method: "POST", headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
        body: JSON.stringify({ type: "azure-refresh", kind, place: view.scope ?? "all" }) });
      const j = await r.json().catch(() => null);
      out = j?.view ? { ...j.view, ...(j.ok === false && j.error ? { warn: j.error } : {}) } : { warn: j?.error ?? "Refresh didn't answer. Type the deployment's name instead." };
    }
  } catch {
    out = { warn: "Refresh didn't answer. Type the deployment's name instead." };
  }
  p.busy[at] = false;
  // The level's configuration changed while it read: that answer is for another resource, and is dropped.
  p.found[at] = configOf(view) === config ? { ...out, config } : null;
  cx.notify();
}

function pick(view, p, row, value, cx) {
  const f = p.found[`${view.scope ?? "all"}:${row.discover}`];
  if (!f || f.config !== configOf(view)) { p.err[row.field] = STALE; return cx.notify(); }
  save(view, p, row.field, value, cx, f.config);
}

// The rows: the route, and on Azure Foundry the rest (a half-set Azure setup under Personal is kept, only not shown).
export function providerRows(view, t) {
  const p = view.pv;
  if (p.scope !== (view.scope ?? null)) {
    p.scope = view.scope ?? null;
    p.err = {};
  }
  // A box shows what the file says now unless it is being edited or holds a refused value: a pick from Refresh's list,
  // a Reset or a change elsewhere shows at once, so a later blur never writes the old words back over it.
  p.setting = true;
  for (const field of TEXT_FIELDS) {
    const want = valueOf(view, field);
    if (!p.focus[field] && !p.err[field] && p.boxes[field].value() !== want) p.boxes[field].set_value(want);
  }
  p.setting = false;
  const azure = valueOf(view, "route") === "azure-foundry";
  return PROVIDER.rows.filter((r) => r.field === "route" || azure).map((r) => {
    const scoped = view.scoped("provider", r.field);
    if (r.choices) {
      const now = valueOf(view, r.field) || (r.field === "route" ? "personal" : PROVIDER[r.choices][0][0]);
      return view.row(t, r.label, r.about, segmented(`provider-${r.field}`, PROVIDER[r.choices].map(([v, w]) => [v, w]), now,
        (v, _e, cx) => save(view, p, r.field, v, cx)), scoped);
    }
    const err = p.err[r.field];
    const box = div().w(240).child(Input.new(p.boxes[r.field]).w_full().h(30).px(10).rounded(7).border_1()
      .border_color(err ? t.blocked : p.focus[r.field] ? t.accent : t.input).bg(t.background).text_size(13).text_color(t.foreground));
    let control = v_flex().items_end().gap(5).child(box);
    if (r.discover) {
      const at = `${view.scope ?? "all"}:${r.discover}`, f = p.found[at], busy = Boolean(p.busy[at]);
      control = control.child(button(`provider-refresh-${r.field}`, busy ? PROVIDER.refreshing : PROVIDER.refresh,
        { disabled: busy, onClick: (_e, cx) => cx.spawn(async (cx) => refresh(view, p, r.discover, cx)) }));
      if (f?.options?.length) control = control.child(v_flex().w(240).children(f.options.slice(0, 12).map((o, i) =>
        menuRow(`provider-found-${r.field}-${i}`, o.label, { check: o.value === valueOf(view, r.field), onClick: (_e, cx) => pick(view, p, r, o.value, cx) }))));
      const line = f?.warn ?? f?.hint;
      if (line) control = control.child(div().w(240).text_size(TEXT.label).line_height("17px").text_color(f?.warn ? t.blocked : t.dim).child(line));
    }
    if (err) control = control.child(div().w(240).text_size(12).line_height("17px").text_color(t.blocked).child(err));
    return view.row(t, r.label, r.about, h_flex().child(control), scoped);
  });
}
