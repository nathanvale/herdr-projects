import { afterAll, expect, test } from 'bun:test'

// Settings › Machines › Find machines (#967): its one button as things stand. After a run the server says wait 10 min;
// the button counts that down and comes back by itself once it is over (a read of the list, never a run). A read of the
// list that failed leaves no hosts: the button then reads the list again, so the screen needn't be left and reopened.
// find.tsx loads ui.tsx, which loads kernel.ts, which reads the page (its address, storage, width) as it loads: the
// little it needs, for this file only, as composer.test.tsx gives it
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
swap('matchMedia', undefined)
swap('window', undefined)
swap('WebSocket', class { static OPEN = 1; readyState = 0; send() {} close() {} })
const { findButton, nextTick } = await import('./find.tsx')

const hosts = [{ to: 'vm-a', over: 'ssh' }, { to: 'vm-b', over: 'tailscale' }]
const ran = { hosts, last: { at: 1, hosts }, wait_ms: 600000 }

test('after a run it counts the wait down, then offers the hosts again', () => {
  expect(findButton(ran, false, 600000)).toEqual({ label: 'Again in 10 min', disabled: true, retry: false })
  expect(findButton(ran, false, 61000)).toEqual({ label: 'Again in 2 min', disabled: true, retry: false })
  expect(findButton(ran, false, 1)).toEqual({ label: 'Again in 1 min', disabled: true, retry: false })
  // over: the wait the server said then no longer holds it back
  expect(findButton(ran, false, 0)).toEqual({ label: 'Try 2 hosts', disabled: false, retry: false })
})

test('the countdown wakes as each minute it shows passes, and when the wait is over', () => {
  expect(nextTick(600000)).toBe(60000)
  expect(nextTick(90000)).toBe(30000)
  expect(nextTick(1500)).toBe(1500)
})

test("a list that couldn't be read can be read again", () => {
  const failed = { hosts: [], last: null, wait_ms: 0, error: "Couldn't reach Shepherdr. Try again." }
  expect(findButton(failed, false, 0)).toEqual({ label: 'Try again', disabled: false, retry: true })
  expect(findButton(failed, true, 0)).toEqual({ label: 'Checking…', disabled: true, retry: true })
})

test('nothing to try, still loading, or trying: no press', () => {
  expect(findButton({ hosts: [], last: null, wait_ms: 0 }, false, 0).disabled).toBe(true)
  expect(findButton(null, false, 0).disabled).toBe(true)
  expect(findButton({ hosts, last: null, wait_ms: 0 }, true, 0)).toEqual({ label: 'Trying…', disabled: true, retry: false })
  // a run that failed keeps its hosts: the button is the run's again
  expect(findButton({ hosts, last: null, wait_ms: 0, error: 'Find machines is already running' }, false, 0))
    .toEqual({ label: 'Try 2 hosts', disabled: false, retry: false })
})
