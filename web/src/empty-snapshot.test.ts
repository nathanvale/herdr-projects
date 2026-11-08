import { expect, test } from 'bun:test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// The web app with no spaces at all (GitHub #747; a fresh install, or the last space closed): the snapshot the
// service sends then has `places: []`. kernel.ts runs in a page, so each case runs it in a Bun process of its own
// with stand-ins for what it reads of the browser (location, storage, document, history, a WebSocket that records
// what the page sends), never the test runner's own globals. Nothing reaches a server, an agent or a model.

const root = mkdtempSync(join(tmpdir(), 'shep-empty-'))
const KERNEL = join(import.meta.dir, 'kernel.ts')

/** compat.snapshot()'s shape (service/compat.ts) for a machine with no spaces and no tasks */
const EMPTY = {
  terminalTransport: 'core', name: 'Shepherdr', host: 'm1', user: 'You',
  places: [], machines: [{ id: 'm:m1', machine: 'm1', name: 'm1', ownName: 'This computer', status: 'idle', here: true }],
  tasks: [], automations: {}, asks: {}, needs: [], settings: [], artifacts: [], sections: [], last: {}, read: {}, off: [],
  look: { tabs: true, worktrees: true, unread: true, red: true, green: true, filters: true, place: true, helpers: true },
  panels: ['files', 'changes'],
}

// The page's world, before kernel.ts loads: what it reads at once and what the socket handler touches. React's
// server renderer (for the panel tests) wants useSyncExternalStore's server snapshot, which the page's store, made
// for the browser only, never passes: here its one getter serves for both.
const BROWSER = `
import { createRequire } from 'node:module'
const require = createRequire(process.env.KERNEL)  // the worktree's own React, the one the page imports
const React = require('react')
const sync = React.useSyncExternalStore
React.useSyncExternalStore = (subscribe, get, server) => sync(subscribe, get, server ?? get)
// DOMPurify (the chat's Markdown, which the Tasks panel's imports reach) needs a real DOM to load: a stand-in that the
// panels rendered here never call (no Markdown on an empty list)
Bun.plugin({ name: 'page-stand-ins', setup(b) { b.module('dompurify', () => ({ loader: 'object', exports: { default: { addHook() {}, sanitize: () => { throw new Error('the DOMPurify stand-in was used') } } } })) } })
const store = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), clear: () => m.clear() } }
const errors = []
const node = () => ({ style: {}, setAttribute() {}, appendChild() {}, remove() {}, addEventListener() {}, classList: { add() {}, remove() {}, toggle() {} } })
Object.assign(globalThis, {
  window: globalThis,
  location: Object.assign(new URL(process.env.PAGE_URL || 'http://127.0.0.1:1/shepherdr/'), { reload() { errors.push('reload') } }),
  localStorage: store(), sessionStorage: store(),
  innerWidth: Number(process.env.PAGE_WIDTH || 1400), innerHeight: 900,
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  history: { state: null, pushState() {}, replaceState() {}, back() {} },
  addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true },
  document: { visibilityState: 'visible', head: { innerHTML: '' }, body: node(), activeElement: null,
    addEventListener() {}, removeEventListener() {}, createElement: node, querySelector: () => null, querySelectorAll: () => [] },
})
const sockets = []
class FakeSocket {
  static OPEN = 1
  constructor(url) { this.url = String(url); this.readyState = 1; this.sent = []; sockets.push(this) }
  send(text) { this.sent.push(JSON.parse(text)) }
  close() { this.readyState = 3 }
}
globalThis.WebSocket = FakeSocket
const K = await import(process.env.KERNEL)
const sock = () => sockets[sockets.length - 1]
const deliver = (msg) => sock().onmessage({ data: JSON.stringify(msg) })
const run = (what, fn) => { try { return { ok: true, value: fn() } } catch (e) { return { ok: false, error: String(e && e.stack ? e.stack.split('\\n')[0] : e) } } }
const out = {}
const finish = () => { console.log(JSON.stringify({ ...out, errors })); process.exit(0) }
`

let n = 0
async function page(code: string, env: Record<string, string> = {}) {
  const script = join(root, `page-${n++}.mjs`)
  writeFileSync(script, BROWSER + code)
  const p = Bun.spawn([process.execPath, script], { env: { PATH: process.env.PATH ?? '', KERNEL, TASKS: join(import.meta.dir, '..', 'plugins', 'tasks', 'client.tsx'), ...env }, stdout: 'pipe', stderr: 'pipe' })
  const [text, err] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text()])
  await p.exited
  const last = text.trim().split('\n').pop() ?? ''
  if (!last.startsWith('{')) throw new Error(err || text)
  return JSON.parse(last)
}

test('the real empty snapshot through the socket handler: no TypeError, the page has it, and it watches no chat', async () => {
  const r = await page(`
K.connect()
sock().onopen()
out.handled = run('snapshot', () => deliver({ type: 'snapshot', snapshot: ${JSON.stringify(EMPTY)} }))
out.places = K.getState().snap?.places ?? null
out.watch = sock().sent.filter((m) => m.type === 'watch').pop() ?? null
finish()
`)
  expect(r.handled).toEqual({ ok: true })
  expect(r.places).toEqual([])
  expect(r.watch?.chats).toEqual([])
}, 30_000)


/** One space, as compat.snapshot() makes it, for the cases that have one (a test fixture: nothing real) */
const ONE = { ...EMPTY, places: [{ id: 'p1', name: 'proj', machine: 'm1', level: 2, status: 'idle', mode: 'regular', chat: 'p1', where: '~/proj', tabs: [] }] }

test('first run: nothing kept and the empty snapshot: the page has it, no space is picked, and no chat is watched', async () => {
  const r = await page(`
K.connect()
sock().onopen()
out.handled = run('snapshot', () => deliver({ type: 'snapshot', snapshot: ${JSON.stringify(EMPTY)} }))
const st = K.getState()
out.place = st.ui.place
out.placeOf = K.placeOf(st.snap, st.ui.place) ?? null
out.watch = sock().sent.filter((m) => m.type === 'watch').pop() ?? null
finish()
`)
  expect(r.handled).toEqual({ ok: true })
  expect(r.placeOf).toBeNull()
  expect(r.place).toBe('')
  expect(r.watch?.chats).toEqual([])
}, 30_000)

test('closing the last space: its snapshot, then the empty one: no error, the space goes, and its chat is no longer watched', async () => {
  const r = await page(`
K.connect()
sock().onopen()
out.one = run('one', () => deliver({ type: 'snapshot', snapshot: ${JSON.stringify(ONE)} }))
out.first = sock().sent.filter((m) => m.type === 'watch').pop()?.chats ?? null
out.placeBefore = K.getState().ui.place
out.none = run('empty', () => deliver({ type: 'snapshot', snapshot: ${JSON.stringify(EMPTY)} }))
out.last = sock().sent.filter((m) => m.type === 'watch').pop()?.chats ?? null
out.placeAfter = K.getState().ui.place
finish()
`)
  expect([r.one, r.none]).toEqual([{ ok: true }, { ok: true }])
  expect([r.placeBefore, r.first]).toEqual(['p1', ['p1']])
  expect([r.placeAfter, r.last]).toEqual(['', []])
}, 30_000)

test('with no spaces, navigation and New space still work: picking a place, the keys, a split and New space throw nothing', async () => {
  const r = await page(`
K.connect()
sock().onopen()
deliver({ type: 'snapshot', snapshot: ${JSON.stringify(EMPTY)} })
out.pick = run('pick', () => K.setUI({ place: 'gone' }))
out.keys = run('keys', () => K.keysChat(K.getState().ui, K.getState().snap))
out.split = run('split', () => K.openSplit({ kind: 'artifact', id: 'a1' }))
out.add = run('add', () => K.setUI({ adding: true, drawer: false, menu: false, plus: null, search: false }))
out.adding = K.getState().ui.adding
out.ladder = run('ladder', () => K.ladder(K.getState().snap, 'gone'))
out.name = run('name', () => K.chatName(K.getState().snap, 'gone'))
finish()
`)
  for (const k of ['pick', 'split', 'add']) expect(r[k].ok).toBe(true)
  expect(r.keys).toEqual({ ok: true, value: null })
  expect(r.adding).toBe(true)
  expect(r.ladder).toEqual({ ok: true, value: '' })
  expect(r.name).toEqual({ ok: true, value: 'gone' })
}, 30_000)

test('no place to show: no chat is visible, on a desktop or a phone, whichever tab is open', async () => {
  const r = await page(`
const ui = K.getState().ui
const snap = ${JSON.stringify(EMPTY)}
out.desktop = run('desktop', () => K.visibleChats({ ...ui, device: 'desktop' }, snap))
out.phoneChat = run('phone chat', () => K.visibleChats({ ...ui, device: 'phone', tab: 'chat', task: null }, snap))
out.phoneTasks = run('phone tasks', () => K.visibleChats({ ...ui, device: 'phone', tab: 'tasks', task: null }, snap))
finish()
`)
  for (const k of ['desktop', 'phoneChat', 'phoneTasks']) expect(r[k]).toEqual({ ok: true, value: [] })
}, 30_000)

test('a space as before: it is found, a name it does not have falls back to it, and its chat is watched', async () => {
  const r = await page(`
K.connect()
sock().onopen()
out.handled = run('snapshot', () => deliver({ type: 'snapshot', snapshot: ${JSON.stringify(ONE)} }))
const snap = K.getState().snap
out.found = K.placeOf(snap, 'p1')?.id ?? null
out.fallback = K.placeOf(snap, 'unknown')?.id ?? null
out.name = K.chatName(snap, 'p1')
out.ladder = K.ladder(snap, 'p1')
out.keys = K.keysChat(K.getState().ui, snap)
out.watch = sock().sent.filter((m) => m.type === 'watch').pop()?.chats ?? null
finish()
`)
  expect(r.handled).toEqual({ ok: true })
  expect([r.found, r.fallback, r.name, r.ladder, r.keys]).toEqual(['p1', 'p1', 'proj', 'proj', 'p1'])
  expect(r.watch).toEqual(['p1'])
}, 30_000)

// The Tasks panel with what a snapshot holds (a test fixture). A snapshot doesn't say whether the service has read the
// task lists yet (service/model.ts builds one on any terminal event, before its first read is done), so with no
// spaces and no tasks the panel can't know: it says nothing is shown here, never that there are no tasks, and never
// that it is still reading (that would never end).
const panel = (snapshot: unknown) => page(`
const { renderToStaticMarkup } = require('react-dom/server')
const P = await import(process.env.TASKS)
K.installPlugins([P.default], ['tasks'])
K.connect()
sock().onopen()
deliver({ type: 'snapshot', snapshot: ${JSON.stringify(snapshot)} })
out.html = run('render', () => renderToStaticMarkup(React.createElement(K.registry.views.tasks, { placeId: '' })))
finish()
`)
const ABSENCE = ['No tasks', 'Nothing to do', 'Nothing in ']

test('the Tasks panel with no spaces: neither "Reading tasks" nor a claim that there are none, but that nothing is shown', async () => {
  const r = await panel(EMPTY)
  expect(r.html).toMatchObject({ ok: true })
  expect(r.html.value).not.toContain('Reading tasks')
  for (const words of ABSENCE) expect(r.html.value).not.toContain(words)
  expect(r.html.value).toContain('Nothing to show here.')
}, 30_000)

test('the Tasks panel with a space and no tasks: upstream\'s words, as before', async () => {
  const r = await panel(ONE)
  expect(r.html).toMatchObject({ ok: true })
  expect(r.html.value).toContain('No tasks on any machine. Ask an Assistant to plan some.')
  expect(r.html.value).not.toContain('Nothing to show here.')
}, 30_000)

process.on('exit', () => rmSync(root, { recursive: true, force: true }))
