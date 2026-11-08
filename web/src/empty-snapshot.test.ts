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

// The page's world, before kernel.ts loads: what it reads at once and what the socket handler touches.
const BROWSER = `
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
  const p = Bun.spawn([process.execPath, script], { env: { PATH: process.env.PATH ?? '', KERNEL, ...env }, stdout: 'pipe', stderr: 'pipe' })
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

process.on('exit', () => rmSync(root, { recursive: true, force: true }))
