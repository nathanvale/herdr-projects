import { expect, test } from 'bun:test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'
import { CoreSource } from '../server/core/source.ts'
import { CoreClient } from '../server/core/client.ts'
import { CoreStore } from '../server/core/store.ts'
import { coreConfig } from '../server/core/config.ts'
import { prepareHome } from '../server/core/home.ts'
import { runCoreServer } from '../server/core/main.ts'
import { operatorRequest, startOperator } from '../server/core/operator.ts'
import type { CoreTerminal } from '../server/core/protocol.ts'

async function fixture(work: (f: Awaited<ReturnType<typeof setup>>) => Promise<void>) {
  const f = await setup(), env = { home: process.env.SHEPHERDR_HOME, port: process.env.SHEPHERDR_PORT }
  try { await work(f) } finally {
    f.close()
    if (env.home === undefined) delete process.env.SHEPHERDR_HOME; else process.env.SHEPHERDR_HOME = env.home
    if (env.port === undefined) delete process.env.SHEPHERDR_PORT; else process.env.SHEPHERDR_PORT = env.port
  }
}
async function setup() {
  const home = mkdtempSync(join(tmpdir(), 'shep-idle-'))
  const config = { home, port: 0, session: 'test', socket: '/unused', binary: 'hc', plugins: false, idleOnly: true }
  const source = new CoreSource(config), boot = randomUUID()
  source.core.current.connected = true
  source.route = async () => undefined
  const calls: string[] = []
  source.core.call = async <T>(method: string) => {
    calls.push(method)
    if (method !== 'terminal.list') throw Error('Unexpected side effect: ' + method)
    return { terminals: [...source.core.current.terminals.values()] } as T
  }
  let stops = 0
  const operator = await startOperator(source, boot, () => { stops++ })
  const stop = (identity: string = boot) => operatorRequest(home, operator.path, ['stop-if-idle', identity])
  const rows = () => source.store.db.query('SELECT kind,key,value FROM records ORDER BY kind,key').all()
  const agent = () => {
    source.store.set('agent', 'chat', { chat: 'chat', space: 'space', machine: source.localMachineId(), kind: 'codex', role: 'coordinator', launch: 'old', grant: 'grant', hook: '/unused', started: 1, state: 'idle', pid: 42, terminal: 't1' })
    return { address: 't1', state: 'finished', pid: 42, argv: ['fake'], cwd: '/unused', created_ms: 1, cols: 80, rows: 24, labels: { 'shepherdr.installation': prepareHome(home).id, 'shepherdr.launch': 'old' } }
  }
  return { source, home, config, boot, stop, rows, agent, calls, stops: () => stops,
    close() { operator.close(); source.stop(); source.mailbox.close(); source.store.close(); rmSync(home, { recursive: true, force: true }) } }
}

for (const state of ['live', 'missing', 'wrong-pid'] as const) test(`protected operator refuses ${state} worker without changing state or stopping`, () => fixture(async f => {
  const terminal = f.agent()
  if (state === 'live') terminal.state = 'live'
  if (state === 'wrong-pid') terminal.pid = 99
  if (state !== 'missing') (f.source.core.current.terminals as Map<string, CoreTerminal>).set('t1', terminal)
  const before = f.rows()
  expect((await f.stop()).code).toBe(1)
  expect(f.rows()).toEqual(before)
  expect(f.source.quiescing).toBe(false)
  expect(f.stops()).toBe(0); expect(f.calls).toEqual([])
}))

for (const [kind, value] of [
  ['permission', { id: 'pending', settled: false, question: { title: 'Approval remains pending' } }],
  ['pending-send', { id: 'pending', chat: 'chat', text: 'Do not send', state: 'queued' }],
  ['pending-send', { id: 'pending', chat: 'chat', text: 'Unknown delivery', state: 'uncertain' }],
  ['launch-attempt', { launch: 'pending', state: 'submission-uncertain' }],
  ['launch-attempt', { launch: 'pending', state: 'never-submitted' }],
] as const) test(`protected operator preserves ${kind} ${'state' in value ? value.state : 'approval'}`, () => fixture(async f => {
  f.source.store.set(kind, 'pending', value)
  const before = f.rows()
  expect((await f.stop()).code).toBe(1)
  const reader = new CoreStore(f.home)
  try { expect(reader.db.query('SELECT kind,key,value FROM records ORDER BY kind,key').all()).toEqual(before) }
  finally { reader.close() }
  expect(f.source.quiescing).toBe(false); expect(f.stops()).toBe(0); expect(f.calls).toEqual([])
}))

test('protected operator admits confirmed idle workers and owns the shutdown', () => fixture(async f => {
  ;(f.source.core.current.terminals as Map<string, CoreTerminal>).set('t1', f.agent())
  const before = f.rows()
  expect(await f.stop()).toEqual({ code: 0, out: `idle-stop:${f.boot}` })
  expect(f.stops()).toBe(1); expect(f.calls).toEqual(['terminal.list'])
  expect(f.source.quiescing).toBe(true); expect(f.rows()).toEqual(before)
}))

test('protected operator closes admission during its fresh observation and rechecks new permissions', () => fixture(async f => {
  let arrived!: () => void, release!: () => void
  const ready = new Promise<void>(resolve => { arrived = resolve })
  const wait = new Promise<void>(resolve => { release = resolve })
  f.source.core.call = async <T>() => { arrived(); await wait; return { terminals: [] } as T }
  const pending = f.stop()
  await ready
  expect(f.source.quiescing).toBe(true)
  await expect(f.source.agents.launch({ id: 'space', machine: 'local', name: 'Test', folder: '/unused', mode: 'regular', base: 'main', prefix: 'EX', added: 1 }, 'chat', 'claude', 'Do not start')).rejects.toThrow('stopping')
  f.source.store.set('permission', 'late', { settled: false })
  release()
  expect((await pending).code).toBe(1)
  expect(f.source.quiescing).toBe(false); expect(f.stops()).toBe(0)
  expect(f.source.store.get('permission', 'late')).toEqual({ settled: false })
  expect(f.source.store.all('launch-attempt')).toEqual([])
}))

test('protected operator refuses a worker appearing in fresh core inventory', () => fixture(async f => {
  f.source.core.call = async <T>() => ({ terminals: [{ address: 'late', state: 'live' }] }) as T
  expect((await f.stop()).code).toBe(1)
  expect(f.source.quiescing).toBe(false); expect(f.stops()).toBe(0)
}))

test('protected operator refuses stale boot, failed observation and unsupported older protocol', () => fixture(async f => {
  expect((await f.stop('different-boot')).code).toBe(1)
  expect(f.calls).toEqual([])
  f.source.core.call = async () => { throw Error('Core disconnected') }
  expect((await f.stop()).code).toBe(1)
  expect(f.source.quiescing).toBe(false); expect(f.stops()).toBe(0)
  const older = await startOperator(f.source, randomUUID())
  try { expect((await operatorRequest(f.home, older.path, ['stop-if-idle', f.boot])).code).toBe(1) }
  finally { older.close() }
}))

test('protected startup refuses before permission cleanup, notice delivery or subscriptions', () => fixture(async f => {
  f.source.store.set('permission', 'old-approval', { settled: false, question: { title: 'Retain this question' } })
  f.source.store.set('message:chat', 'permission-old-approval', { id: 'permission-old-approval', question: { title: 'Retain this question' } })
  const before = f.rows()
  await expect(runCoreServer(f.config)).rejects.toThrow('permission requests are still pending')
  const reader = new CoreStore(f.home)
  try { expect(reader.db.query('SELECT kind,key,value FROM records ORDER BY kind,key').all()).toEqual(before) }
  finally { reader.close() }
  expect(f.stops()).toBe(0); expect(f.calls).toEqual([])
}))

test('protected flag is explicit and ordinary configurations retain their defaults', () => {
  expect(coreConfig(['--core-session', 'test']).idleOnly).toBeUndefined()
  expect(coreConfig(['--core-session', 'test', '--idle-only']).idleOnly).toBe(true)
})


test('protected launcher refuses through the executable without signaling the app process', () => fixture(async f => {
  const terminal = f.agent(); terminal.state = 'live'
  ;(f.source.core.current.terminals as Map<string, CoreTerminal>).set('t1', terminal)
  const holder = Bun.spawn([process.execPath, '-e', 'setInterval(() => {}, 1000)'], { env: { PATH: process.env.PATH ?? '' }, stdout: 'ignore', stderr: 'ignore' })
  const server = Bun.serve({ hostname: '127.0.0.1', port: 0, fetch: () => Response.json({ product: 'shepherdr-core', boot: f.boot, pid: holder.pid, core: true }) })
  writeFileSync(join(f.home, 'run.json'), JSON.stringify({ pid: holder.pid, boot: f.boot, home: f.home, port: server.port, root: '/unused', operator: join(f.home, `operator.${f.boot.slice(0, 8)}.sock`) }))
  try {
    const cli = Bun.spawn([process.execPath, join(import.meta.dir, '../server/core/launcher.ts'), 'stop', '--home', f.home, '--port', String(server.port), '--core-session', 'test', '--core-socket', '/unused', '--idle-only'], { env: { PATH: process.env.PATH ?? '' }, stdout: 'pipe', stderr: 'pipe' })
    const [code, out, err] = await Promise.all([cli.exited, new Response(cli.stdout).text(), new Response(cli.stderr).text()])
    expect(code).toBe(1); expect(out).toBe(''); expect(err).toContain('Protected update refused')
    expect(holder.exitCode).toBeNull(); expect(f.stops()).toBe(0)
    expect(f.source.quiescing).toBe(false)
  } finally { server.stop(true); holder.kill(); await holder.exited }
}), 15_000)


test('protected startup observes core before accepting an apparently idle home', () => fixture(async f => {
  const open = CoreClient.open
  let closed = false, observed = 0
  CoreClient.open = async () => ({ call: async () => { observed++; return { terminals: [{ address: 'outside-records', state: 'live' }] } }, close: () => { closed = true } }) as unknown as CoreClient
  try {
    const before = f.rows()
    await expect(runCoreServer(f.config)).rejects.toThrow('core has live or unconfirmed terminals')
    expect(observed).toBe(1); expect(closed).toBe(true)
    expect(f.rows()).toEqual(before)
  } finally { CoreClient.open = open }
}))


test('protected operator leaves the app running while a public action awaits', () => fixture(async f => {
  let arrived!: () => void, release!: () => void
  const ready = new Promise<void>(resolve => { arrived = resolve })
  const wait = new Promise<void>(resolve => { release = resolve })
  f.source.registerAction('setting', async () => { arrived(); await wait; return {} })
  const action = f.source.act({ type: 'setting', key: 'task.model', value: 'default' })
  await ready
  try {
    expect((await f.stop()).code).toBe(1)
    expect(f.source.quiescing).toBe(false); expect(f.stops()).toBe(0)
    expect(f.calls).toEqual([])
  } finally { release(); await action }
  expect((await f.stop()).code).toBe(0)
  expect(f.stops()).toBe(1)
}))
