import { afterAll, expect, test } from 'bun:test'
import type { Snapshot } from '@shared/types.ts'

// A window between a phone's width and 1024 px is a "tablet" to the page (kernel.ts deviceFor). On a desktop
// browser with a mouse and keyboard there, the Assistant's terminal (Chat | Terminal on Terminal) said "Keys go to
// the terminal" and gave no typing box, yet the page's key handler took keys only on a "desktop": nothing typed
// reached the terminal. These tests drive the real handler with the real kernel and terminal socket client.
const g = globalThis as Record<string, unknown>
const noop = () => {}
const storage = { getItem: () => null, setItem: noop, removeItem: noop }
const page: Record<string, unknown> = {
  location: new URL('http://app.test/'),
  localStorage: storage,
  sessionStorage: storage,
  addEventListener: noop,
  removeEventListener: noop,
  innerWidth: 1280,
  innerHeight: 800,
  history: { replaceState: noop, pushState: noop, state: null },
  requestAnimationFrame: (f: () => void) => setTimeout(f, 0),
  document: {
    head: { innerHTML: '', append: noop }, visibilityState: 'visible', addEventListener: noop, removeEventListener: noop,
    documentElement: { style: {}, dataset: {} }, activeElement: null, querySelector: () => null, createElement: () => ({}),
  },
}
const before = new Map<string, { had: boolean; value: unknown }>()
function swap(k: string, v: unknown) {
  if (!before.has(k)) before.set(k, { had: k in g, value: g[k] })
  if (v === undefined) delete g[k]
  else g[k] = v
}
afterAll(() => {
  for (const [k, b] of before) {
    if (b.had) g[k] = b.value
    else delete g[k]
  }
})
for (const [k, v] of Object.entries(page)) swap(k, v)
let coarse = false
swap('matchMedia', (q: string) => ({ matches: q.includes('coarse') ? coarse : false }))
swap('window', undefined)
// every socket the page opens, as a stand-in: the kernel's and each terminal's (api/terminal)
type Sock = { url: string; readyState: number; sent: string[]; onopen?: () => void; onmessage?: (e: { data: string }) => void }
const socks: Sock[] = []
swap('WebSocket', class {
  static OPEN = 1
  readyState = 0
  sent: string[] = []
  url: string
  constructor(url: URL | string) { this.url = String(url); socks.push(this as unknown as Sock) }
  send(d: string) { this.sent.push(d) }
  close() {}
})
const { connect, installPlugins, registry, setUI, getState } = await import('@client/kernel.ts')
const terminalModule = await import('./client.tsx')
const terminal = terminalModule.default
const { connectTerminal, pasteMode } = await import('./stream.ts')
installPlugins([terminal], [terminal.name])
connect()
const app = socks.at(-1)!
app.onopen?.()
swap('window', globalThis)

const snap = {
  name: 'vm', host: 'vm', user: 'you', off: [], terminalTransport: 'core',
  places: [{ id: 'sp1', name: 'sp1', machine: 'vm', level: 2, status: 'idle', mode: 'regular', chat: 'p:sp1' }],
  machines: [{ id: 'm:vm', machine: 'vm', name: 'vm', status: 'idle', here: true }],
  tasks: [], automations: {}, artifacts: [], asks: {}, needs: [], settings: [],
} as unknown as Snapshot
app.onmessage!({ data: JSON.stringify({ type: 'snapshot', snapshot: snap }) })

// the Assistant's terminal, open on its socket, as the Terminal view opens it
connectTerminal('p:sp1', noop, noop, noop, noop)
const term = socks.find((s) => s.url.includes('api/terminal') && s.url.includes('chat=p%3Asp1'))!
term.readyState = 1
term.onopen?.()

/** a key pressed with the Assistant's terminal in place of its chat, on this device: what reached the terminal */
function press(device: 'phone' | 'tablet' | 'desktop', key: string) {
  setUI({ device, place: 'sp1', term: 'p:sp1' })
  const sent = term.sent.length
  let prevented = false
  const e = { key, ctrlKey: false, altKey: false, metaKey: false, shiftKey: false, target: null, preventDefault: () => { prevented = true } }
  const taken = registry.keys.some((k) => k.handle({ e: e as unknown as KeyboardEvent, ui: getState().ui, snap: getState().snap! }))
  return { taken, prevented, sent: term.sent.slice(sent).map((d) => JSON.parse(d)) }
}

test('the terminal shown in place of the chat takes keys on a desktop', () => {
  coarse = false
  const got = press('desktop', 'x')
  expect(got.prevented).toBe(true)
  expect(got.sent).toEqual([expect.objectContaining({ type: 'text', text: 'x' })])
})

test('a desktop browser narrower than 1024 px (a "tablet" to the page) types into the terminal too', () => {
  coarse = false
  const got = press('tablet', 'y')
  expect(got.prevented).toBe(true)
  expect(got.sent).toEqual([expect.objectContaining({ type: 'text', text: 'y' })])
})

test('a phone and a touch screen keep their typing box: the page-wide handler leaves their keys alone', () => {
  coarse = false
  expect(press('phone', 'z').sent).toEqual([])
  coarse = true
  expect(press('tablet', 'z').sent).toEqual([])
  coarse = false
})

// Pasting (Cmd+V, or the browser's Paste) while the terminal takes the keys put nothing in: no handler took the
// page's paste. A paste goes in as one paste: newlines as Enter's carriage return, inside bracketed-paste marks when
// the program asked for them (Claude Code does), so a multi-line paste is not sent line by line, and in pieces the
// socket takes.
function paste(device: 'phone' | 'tablet' | 'desktop', text: string, target: unknown = null) {
  setUI({ device, place: 'sp1', term: 'p:sp1' })
  const sent = term.sent.length
  let prevented = false
  const e = { target, clipboardData: { getData: (t: string) => (t === 'text/plain' ? text : '') }, preventDefault: () => { prevented = true } }
  terminalModule.pasteToTerminal(e)
  const got = term.sent.slice(sent).map((d) => JSON.parse(d))
  return { prevented, got, typed: got.map((m: { text?: string }) => m.text ?? '').join('') }
}

test('a paste on a desktop goes into the terminal, newlines as carriage returns', () => {
  coarse = false
  const got = paste('desktop', 'echo one\necho two')
  expect(got.prevented).toBe(true)
  expect(got.typed).toBe('echo one\recho two')
})

test('a paste is bracketed when the program asked for bracketed paste', () => {
  coarse = false
  const off = pasteMode('p:sp1', () => true)
  const got = paste('tablet', 'line 1\r\nline 2')
  off()
  expect(got.typed).toBe('\x1b[200~line 1\rline 2\x1b[201~')
})

test('a long paste reaches the terminal whole, in pieces the socket takes', () => {
  coarse = false
  const long = 'x'.repeat(20_000)
  const got = paste('desktop', long)
  expect(got.got.length).toBeGreaterThan(1)
  expect(got.got.every((m: { text: string }) => JSON.stringify(m).length < 32_768)).toBe(true)
  expect(got.typed).toBe(long)
})

test("a paste into the chat's own box, with no terminal taking the keys, is left to the box", () => {
  coarse = false
  setUI({ device: 'desktop', place: 'sp1', term: null })
  const sent = term.sent.length
  let prevented = false
  terminalModule.pasteToTerminal({ target: { tagName: 'TEXTAREA' }, clipboardData: { getData: () => 'hello' }, preventDefault: () => { prevented = true } })
  expect(prevented).toBe(false)
  expect(term.sent.length).toBe(sent)
})
