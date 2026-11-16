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
const terminal = (await import('./client.tsx')).default
const { connectTerminal } = await import('./stream.ts')
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
