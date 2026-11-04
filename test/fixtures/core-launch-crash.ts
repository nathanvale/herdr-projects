// CI-only crash probe. No real core connection, shell or coding CLI is started.
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { CoreSource } from '../../server/core/source.ts'
const [home, point] = process.argv.slice(2)
if (!home || !point) throw Error('Expected scratch home and crash point')
const source = new CoreSource({ home, port: 0, socket: '/unused', session: 'test', binary: 'hc', plugins: false })
source.route = async () => undefined
source.core.current.connected = true
const space = { id: 'space', machine: 'machine', name: 'Example', folder: '/unused', base: 'main', prefix: 'EX', mode: 'regular' as const, added: 1 }
source.store.set('space', space.id, space)
const set = source.store.set.bind(source.store)
source.store.set = (kind, key, value) => {
  set(kind, key, value)
  if (kind === 'launch-claim' && point === 'claimed') queueMicrotask(() => process.exit(81))
  if (kind === 'agent-launch' && point === 'recorded') queueMicrotask(() => process.exit(81))
}
source.core.call = async <T>(method: string, params: Record<string, unknown> = {}) => {
  if (method !== 'terminal.run') throw Error('Unexpected call: '+method)
  if (point === 'submitted') writeFileSync(join(home, 'fake-core-receipt.json'), JSON.stringify({ address: 't-crash', pid: 123, state: 'live', labels: params.labels, created_ms: 1 }))
  process.exit(81)
  return undefined as T
}
await source.agents.launch(space, 'chat', 'codex', 'Wait', { readOnly: true })
throw Error('Crash probe unexpectedly returned')
