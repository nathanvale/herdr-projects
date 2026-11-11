import { afterAll, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import type { Chat, SettingSection, Snapshot } from '@shared/types.ts'

// PR 60: the message box's suggested next message (SHEP-186) as a screen reader gets it, read from the real Composer's
// HTML. The store is filled the way the page fills it: the kernel's own socket, its snapshot and chat messages.
// kernel.ts reads the page (its address, storage, width) as it loads: the little it needs, for this file only
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
  // theme.ts sets the page's colour as it loads (its theme-color meta)
  document: {
    head: { innerHTML: '', append: noop }, visibilityState: 'visible', addEventListener: noop, removeEventListener: noop,
    documentElement: { style: {}, dataset: {} }, activeElement: null, querySelector: () => null, createElement: () => ({}),
  },
}
// This file's page while it runs. Another test file in the same run may have left its own stand-ins on globalThis (a
// document with no documentElement, a matchMedia), so each name is this file's until its tests end, then back as it
// was (absent: removed)
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
// no device answer: not a touch screen (the touch test gives one); no window as the modules load (page-only work skips)
swap('matchMedia', undefined)
swap('window', undefined)
// the server's socket, as a stand-in the test speaks for
type Sock = { onopen?: () => void; onmessage?: (e: { data: string }) => void }
const socks: Sock[] = []
swap('WebSocket', class { static OPEN = 1; readyState = 0; constructor() { socks.push(this as unknown as Sock) } send() {} close() {} })
const { connect } = await import('@client/kernel.ts')
const { Composer } = await import('./client.tsx')
connect()
const sock = socks.at(-1)!
sock.onopen?.()
// the snapshot handler reads the page's window (an add-on switched off): set once the modules have loaded
swap('window', globalThis)

const row = (value: 'on' | 'off') => ({ label: 'Suggested next message', key: 'agents.suggestions', value, options: ['on', 'off'] })
const agents = (level: string, value: 'on' | 'off') => ({ name: 'Agents', level, rows: [row(value)] }) as SettingSection
const place = (id: string) => ({ id, name: id, machine: 'vm', level: 2, status: 'idle', mode: 'regular', chat: `p:${id}` })
function snapshot(settings: SettingSection[]) {
  const snap = {
    name: 'vm', host: 'vm', user: 'you', off: ['insights'], places: [place('sp1'), place('sp2'), place('sp4')],
    machines: [{ id: 'm:vm', machine: 'vm', name: 'vm', status: 'idle', here: true }],
    tasks: [], automations: {}, artifacts: [], asks: {}, needs: [], settings,
  } as unknown as Snapshot
  sock.onmessage!({ data: JSON.stringify({ type: 'snapshot', snapshot: snap }) })
}
function chat(key: string, suggest?: string) {
  const c = { key, cli: 'Claude Code', messages: [{ id: `${key}-m1`, who: 'agent', at: 1, text: 'Merge it?', ...(suggest ? { suggest } : {}) }] } as unknown as Chat
  sock.onmessage!({ data: JSON.stringify({ type: 'chat', chat: c }) })
}
chat('p:sp1', 'yes, merge it')
chat('p:sp2', 'ship it now')
chat('p:sp4')
chat('t:solo', 'run it')  // a chat in no space

// What the HTML gives a screen reader: the box's and Send's descriptions, each id's words, ids under aria-hidden, and
// the grey copy (data-ghost) with whether it is hidden
async function read(chatKey: string) {
  const html = renderToStaticMarkup(<Composer chatKey={chatKey} placeholder="Message the Assistant" cli="Claude Code" />)
  const got = { box: null as string | null, send: null as string | null, described: 0, words: new Map<string, string>(), hidden: [] as string[], ghosts: 0, hiddenGhosts: [] as string[] }
  let at: string | null = null
  await new HTMLRewriter()
    .on('textarea', { element(el) { got.box = el.getAttribute('aria-describedby') } })
    .on('button[aria-label="Send"]', { element(el) { got.send = el.getAttribute('aria-describedby') } })
    .on('[aria-describedby]', { element() { got.described++ } })
    .on('[id]', {
      element(el) {
        at = el.getAttribute('id')
        got.words.set(at!, '')
        try { el.onEndTag(() => { at = null }) } catch { at = null } // an element with no end tag holds no words
      },
      text(t) { if (at) got.words.set(at, got.words.get(at)! + t.text) },
    })
    .on('[aria-hidden="true"] [id]', { element(el) { got.hidden.push(el.getAttribute('id')!) } })
    .on('[id][aria-hidden="true"]', { element(el) { got.hidden.push(el.getAttribute('id')!) } })
    .on('[data-ghost]', { element() { got.ghosts++ } })
    .on('[aria-hidden="true"] [data-ghost]', { element() { got.hiddenGhosts.push('') }, text(t) { got.hiddenGhosts[got.hiddenGhosts.length - 1] += t.text } })
    .transform(new Response(html)).text()
  return got
}

test('a suggestion is described to a screen reader on the box and on Send', async () => {
  snapshot([agents('all', 'on')])
  const got = await read('p:sp1')
  expect(got.box).toBeTruthy()
  expect(got.send).toBe(got.box)
  expect(got.words.get(got.box!)).toBe('Suggested next message: yes, merge it. Enter sends it, Tab fills it in.')
  // its words are not hidden from the screen reader; the grey copy is, and is the only copy shown
  expect(got.hidden).not.toContain(got.box!)
  expect(got.ghosts).toBe(1)
  expect(got.hiddenGhosts).toEqual(['yes, merge it'])
})

test('no suggestion, no description', async () => {
  snapshot([agents('all', 'on')])
  const got = await read('p:sp4')
  expect([got.box, got.send, got.described, got.ghosts]).toEqual([null, null, 0, 0])
})

test("the chat's space's own setting decides whether its suggestion shows", async () => {
  // Everywhere on, sp2's own off: none in sp2; sp1 (its own on) has it
  snapshot([agents('all', 'on'), agents('sp1', 'on'), agents('sp2', 'off')])
  let got = await read('p:sp2')
  expect([got.box, got.send, got.described, got.ghosts]).toEqual([null, null, 0, 0])
  expect((await read('p:sp1')).ghosts).toBe(1)
  expect((await read('t:solo')).ghosts).toBe(1)  // in no space: Everywhere's
  // Everywhere off, sp1's own on: sp1 has it, sp2 (its own off) has none
  snapshot([agents('all', 'off'), agents('sp1', 'on'), agents('sp2', 'off')])
  got = await read('p:sp1')
  expect(got.words.get(got.box!)).toBe('Suggested next message: yes, merge it. Enter sends it, Tab fills it in.')
  expect((await read('p:sp2')).ghosts).toBe(0)
  expect((await read('t:solo')).ghosts).toBe(0)
})

test('on a touch screen, where Enter makes a new line, the words say Send', async () => {
  snapshot([agents('all', 'on')])
  g.matchMedia = (q: string) => ({ matches: q === '(any-pointer: coarse)' })
  try {
    const got = await read('p:sp1')
    expect(got.words.get(got.box!)).toBe('Suggested next message: yes, merge it. Send sends it.')
    expect(got.send).toBe(got.box)
  } finally {
    delete g.matchMedia
  }
})
