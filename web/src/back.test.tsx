import { afterAll, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'

// v3.1.32's merge (SHEP-210): a conversation header's Back (LeadBack) is a 20px chevron now. A voice call's close and
// back find the screen's own Back by its data-back mark (web/plugins/voice/client.tsx closeTop), so the new chevron
// must carry it as BackIcon does. Read from the real components' HTML.
// ui.tsx loads kernel.ts, which reads the page (its address, storage, width) as it loads: the little it needs, for this
// file only, as composer.test.tsx gives it
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
const { BackIcon, LeadBack } = await import('./ui.tsx')

test('a conversation header Back carries the mark a voice call finds Back by', () => {
  const html = renderToStaticMarkup(<LeadBack onClick={() => {}} to="Tasks" />)
  expect(html).toContain('aria-label="Back to Tasks"')
  expect(html).toContain('data-back=""')
  // the same mark as every other Back's icon
  expect(renderToStaticMarkup(<BackIcon />)).toContain('data-back=""')
})
