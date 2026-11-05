import { expect, test } from 'bun:test'
import { mkdtempSync, chmodSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'
import { createConnection } from 'node:net'
import { once } from 'node:events'
import { CoreSource } from '../server/core/source.ts'
import { operatorRequest, startOperator } from '../server/core/operator.ts'
import { CoreStore } from '../server/core/store.ts'
import { CoreError } from '../server/core/client.ts'
import { readHostBoot, type HostBoot, type LaunchRecovery } from '../server/core/launch-recovery.ts'
import type { CoreAgent, PendingSend, CoreSpace } from '../server/core/model.ts'
import type { CoreTerminal } from '../server/core/protocol.ts'
import type { CoreTask } from '../server/core/tasks.ts'
import { runChild } from './child.ts'
import { startApp } from '../server/app.ts'

test('private operator socket writes via the server vault and refuses insecure socket permissions', async () => {
  const home = mkdtempSync(join(tmpdir(), 'shep-op-'))
  const source = new CoreSource({ home, port: 17887, session: 'test', socket: '/unused', binary: 'hc' })
  const operator = await startOperator(source, randomUUID())
  try {
    expect(await operatorRequest(home, operator.path, ['secret', 'set', 'DEMO'], 'operator-fixture')).toEqual({ code: 0, out: 'Saved DEMO for Everywhere.\n' })
    expect(source.secrets.vault.has('all', 'DEMO')).toBe(true)
    expect((await operatorRequest(home, operator.path, ['secret', 'rm', 'DEMO'])).code).toBe(0)
    expect(source.secrets.vault.has('all', 'DEMO')).toBe(false)
    chmodSync(operator.path, 0o666)
    await expect(operatorRequest(home, operator.path, ['secret', 'rm', 'DEMO'])).rejects.toThrow('private')
    chmodSync(operator.path, 0o600)
    expect((await operatorRequest(home, operator.path, ['secret', 'set', 'BAD', 'command-word-value'])).code).toBe(1)
  } finally { operator.close(); source.stop(); source.mailbox.close(); source.store.close(); rmSync(home, { recursive: true, force: true }) }
})

const originalBoot = '11111111-1111-4111-8111-111111111111'
const nextBoot = '22222222-2222-4222-8222-222222222222'
type BootProbe = { value: HostBoot; before?: () => Promise<void> }

function recoveryTask(space: CoreSpace, id = 'EX-1'): CoreTask {
  return { id, chat: `${id}/Agent`, name: 'Retained task', desc: 'Preserve the existing work', place: space.id, machine: space.machine,
      folder: '/retained-worktree', repo: space.folder, branch: 'work/retained', base: 'main', kind: 'codex', workflow: 'todo', status: 'todo', state: 'To do',
      mergePolicy: 'ask', review: { on: false, kind: 'codex', rounds: 3, mustFix: 'major' }, model: 'gpt-6.1-sol', effort: 'high', speed: 'fast', age: 'now', created: '2026-11-05', on: 'test' }
}

async function recoveryFixture(work: (f: Awaited<ReturnType<typeof recoverySetup>>) => Promise<void>, role: 'coordinator' | 'task' = 'coordinator', deployment = 'gpt-6.1-sol') {
  const home = mkdtempSync(join(tmpdir(), 'shep-boot-')), boot = { value: { host: 'a'.repeat(64), boot: originalBoot } }
  const f = await recoverySetup(home, boot, role, false, deployment)
  try { await work(f) } finally { await f.close(); rmSync(home, { recursive: true, force: true }) }
}
async function recoverySetup(home: string, boot: BootProbe, role: 'coordinator' | 'task', reopen = false, deployment = 'gpt-6.1-sol') {
  const source = new CoreSource({ home, port: 0, session: 'test', socket: '/unused', binary: 'hc', plugins: false }, async () => { await boot.before?.(); return boot.value })
  const space: CoreSpace = { id: 'space', machine: source.localMachineId(), name: 'Example', folder: '/retained-repo', base: 'main', prefix: 'EX', mode: 'regular', added: 1 }
  const chat = role === 'task' ? 'EX-1/Agent' : space.id
  const calls: { method: string; params: Record<string, unknown> }[] = []
  let fail = false, terminalSequence = 0
  source.route = async () => undefined
  source.core.current.connected = true
  source.tasks.git.ensureWorktree = async () => false // Actual checkout preservation is owned by core-tasks.
  source.tasks.seedIncludes = async () => {}
  source.browsers.close = async () => {}
  source.core.call = async <T>(method: string, params: Record<string, unknown> = {}) => {
    // CoreAgents owns its own CoreFiles. Fake credential presence at their shared
    // core transport, using Core's exec result contract; no command or model runs.
    if (method === 'machine.exec') {
      expect((params.argv as string[]).at(-1)).toBe('AZURE_OPENAI_API_KEY')
      return { code: 0, stdout: '', stderr: '', timed_out: false, truncated: false } as T
    }
    calls.push({ method, params })
    if (method === 'terminal.run') {
      if (fail) throw new CoreError('spawn_failed', 'cannot start codex: Device not configured (os error 6)')
      const sequence = ++terminalSequence
      const terminal = { address: `t${sequence}`, pid: sequence, state: 'live', labels: params.labels, created_ms: sequence } as CoreTerminal
      ;(source.core.current.terminals as Map<string, CoreTerminal>).set(terminal.address, terminal)
      return terminal as T
    }
    if (method === 'terminal.send' || method === 'terminal.label') return {} as T
    throw Error('Unexpected recovery fixture core call: ' + method)
  }
  if (!reopen) {
    source.store.set('space', space.id, space)
    source.store.set('health-sample', space.machine, { at: Date.now(), cores: 8, load: 1, memTotal: 1000, memUsed: 400, disks: [], gpus: [] })
    if (role === 'task') source.store.set('task', 'EX-1', recoveryTask(space))
    source.settings.set('provider.route', 'Azure Foundry'); source.settings.set('coordinator.agent', 'Codex')
    source.settings.set('azure.codexEndpoint', 'https://example.openai.azure.com/openai/v1'); source.settings.set('azure.codexDeployment', deployment)
    const before = await source.agents.launch(space, chat, 'codex', 'Initial test turn', { role, model: 'gpt-6.1-sol', effort: 'high', speed: 'fast' })
    source.agents.update(before, { session: '33333333-3333-4333-8333-333333333333', transcript: '/retained-native-session.jsonl' })
    source.agents.terminal(before)!.state = 'finished'; fail = true
    await expect(source.agents.launch(space, chat, 'codex', 'Original uncertain instruction', { role, model: 'gpt-6.1-sol', effort: 'high', speed: 'fast', resume: true })).rejects.toThrow('Device not configured')
    source.agents.update(source.agents.get(chat)!, { speed: 'fast' }) // Independently observed native binding, not the role default.
  }
  const agent = source.agents.get(chat)!, launch = agent.launch
  if (!reopen) {
    source.store.set('pending-send', 'submitted', { id: 'submitted', chat, text: 'Original uncertain instruction', state: 'uncertain', submission: { launch, promptHash: 'retained-hash' } } satisfies PendingSend)
    source.store.set('pending-send', 'queued', { id: 'queued', chat, text: 'Old queued instruction', state: 'queued' } satisfies PendingSend)
  }
  fail = false; calls.length = 0
  const operator = await startOperator(source, randomUUID())
  writeFileSync(join(home, 'run.json'), JSON.stringify({ pid: process.pid, boot: randomUUID(), home, port: 0, root: '/unused', operator: operator.path }))
  let closed = false
  return { source, home, boot, chat, launch, agent, space, calls, operatorPath: operator.path,
    request: (operation: string, extra: string[] = []) => operatorRequest(home, operator.path, ['recover-launch', operation, chat, launch, ...extra]),
    read: <T>(kind: string, key: string) => { const reader = new CoreStore(home); try { return reader.get<T>(kind, key) } finally { reader.close() } },
    rows: () => { const reader = new CoreStore(home); try { return reader.db.query('SELECT kind,key,value FROM records ORDER BY kind,key').all() } finally { reader.close() } },
    close: async () => { if (closed) return; closed = true; operator.close(); await source.drain(); source.stop(); source.mailbox.close(); source.store.close() },
  }
}

test('boot recovery arm and same-boot refusal preserve the exact uncertain launch and grant', () => recoveryFixture(async f => {
  const beforeAgent = f.read<CoreAgent>('agent', f.chat), grants = f.source.mailbox.active().map(row => row.id)
  expect((await f.request('arm')).code).toBe(0)
  const armed = f.rows()
  expect((await f.request('arm')).out).toBe(`${f.launch}: armed\n`)
  expect(f.rows()).toEqual(armed)
  expect(await f.request('settle')).toMatchObject({ code: 1, out: expect.stringContaining('has not rebooted') })
  expect(f.rows()).toEqual(armed); expect(f.read('agent', f.chat)).toEqual(beforeAgent)
  expect(f.source.mailbox.active().map(row => row.id)).toEqual(grants)
  expect(f.calls).toEqual([])
}))

test('boot recovery settlement preserves current native bindings and never replays old delivery', () => recoveryFixture(async f => {
  const unrelated = f.source.mailbox.issue('unrelated-chat', 'unrelated-native-session', f.space.machine, ['cli'])
  expect((await f.request('arm')).code).toBe(0)
  // A legitimate same-session observation after arming must survive settlement.
  f.source.agents.update(f.agent, { transcript: '/observed-current-session.jsonl', runtime: { model: 'gpt-6.1-sol', source: 'session', at: 5 } })
  const current = f.read<CoreAgent>('agent', f.chat)!
  f.boot.value = { ...f.boot.value, boot: nextBoot }
  expect((await f.request('settle')).code).toBe(0)
  expect(f.read('agent', f.chat)).toEqual({ ...current, state: 'idle' })
  expect(f.read('launch-attempt', f.launch)).toMatchObject({ state: 'execution-ended-after-host-reboot' })
  expect(f.source.mailbox.active().map(row => row.id)).not.toContain(f.agent.grant)
  expect(f.source.mailbox.active().find(row => row.id === unrelated.id)).toMatchObject({ chat: 'unrelated-chat', session: 'unrelated-native-session', machine: f.space.machine })
  expect(f.read('pending-send', 'submitted')).toMatchObject({ state: 'uncertain', submission: { launch: f.launch, promptHash: 'retained-hash' } })
  const settled = f.rows()
  expect((await f.request('settle')).out).toBe(`${f.launch}: settled\n`); expect(f.rows()).toEqual(settled)
  expect((await f.request('resume')).code).toBe(1)
  expect((await f.request('resume', ['--cancel-queued'])).code).toBe(0)
  expect(f.read('pending-send', 'queued')).toMatchObject({ state: 'cancelled' })
  expect(f.read('message:' + f.chat, 'cancelled-queued')).toMatchObject({ text: 'Stopped before your saved message was sent.' })
  expect(f.read('pending-send', 'submitted')).toMatchObject({ state: 'uncertain' })
  const resumed = f.rows()
  expect((await f.request('resume', ['--cancel-queued'])).out).toBe(`${f.launch}: resumed\n`); expect(f.rows()).toEqual(resumed)
  f.source.retryPending(); await f.source.tasks.tick(); await new Promise<void>(resolve => setImmediate(resolve))
  expect(f.calls).toEqual([])
  await f.source.act({ type: 'restart', chat: f.chat, kind: 'codex', model: 'gpt-6.1-sol', effort: 'high', speed: 'fast' })
  const runs = f.calls.filter(call => call.method === 'terminal.run')
  expect(runs).toHaveLength(1)
  expect(runs[0]!.params.argv).toContain('33333333-3333-4333-8333-333333333333')
  expect(JSON.stringify(runs)).not.toContain('Original uncertain instruction')
  expect(f.source.agents.get(f.chat)).toMatchObject({ session: current.session, model: current.model, effort: current.effort, speed: current.speed, provider: current.provider })
}))

test('boot recovery hold survives a persisted reopen and holds task starts and queued messages', () => recoveryFixture(async f => {
  expect((await f.request('arm')).code).toBe(0)
  await f.close()
  const reopened = await recoverySetup(f.home, f.boot, 'task', true)
  try {
    expect((await reopened.request('status')).out).toBe(`${f.launch}: armed\n`)
    reopened.source.agents.update(reopened.agent, { state: 'idle' })
    await expect(reopened.source.tasks.launch(reopened.source.tasks.get('EX-1')!)).rejects.toThrow('held')
    await expect(reopened.source.agents.preflight(reopened.space, reopened.chat, 'codex')).rejects.toThrow('held')
    reopened.source.retryPending(); await reopened.source.tasks.tick(); await new Promise<void>(resolve => setImmediate(resolve))
    expect(reopened.calls).toEqual([])
    expect(reopened.read('pending-send', 'queued')).toMatchObject({ state: 'queued' })
    expect(reopened.read('task', 'EX-1')).toMatchObject({ folder: '/retained-worktree', branch: 'work/retained' })
  } finally { await reopened.close() }
}, 'task'))

for (const replacement of ['host', 'launch', 'session', 'provider'] as const) test(`boot recovery refuses replaced ${replacement} without changing state`, () => recoveryFixture(async f => {
  expect((await f.request('arm')).code).toBe(0)
  f.boot.value = { ...f.boot.value, boot: nextBoot }
  if (replacement === 'host') f.boot.value.host = 'b'.repeat(64)
  else f.source.store.set('agent', f.chat, { ...f.agent, ...(replacement === 'launch' ? { launch: randomUUID() } : replacement === 'session' ? { session: randomUUID() } : { provider: { ...f.agent.provider, fingerprint: 'changed' } }) })
  const before = f.rows(), grants = f.source.mailbox.active().map(row => row.id)
  expect((await f.request('settle')).code).toBe(1)
  expect(f.rows()).toEqual(before); expect(f.source.mailbox.active().map(row => row.id)).toEqual(grants)
}))

test('boot recovery final admission fences a preflight admitted before the hold', () => recoveryFixture(async f => {
  const prepared = await f.source.agents.preflight(f.space, f.chat, 'codex')
  expect((await f.request('arm')).code).toBe(0)
  expect(() => f.source.agents.admit(prepared)).toThrow('held')
  await expect(f.source.act({ type: 'restart', chat: f.chat, kind: 'codex' })).rejects.toThrow('held')
  expect(f.calls).toEqual([])
}))

test('boot recovery refuses an in-flight application sender before arming', () => recoveryFixture(async f => {
  let arrived!: () => void, release!: () => void
  const reached = new Promise<void>(resolve => { arrived = resolve }), gate = new Promise<void>(resolve => { release = resolve })
  f.source.chats.text = async () => { arrived(); await gate; return 'New instruction' }
  const sending = f.source.act({ type: 'send', chat: f.chat, text: 'New instruction', cid: 'held-sending' })
  await reached
  try {
    const before = f.rows()
    expect((await f.request('arm')).out).toContain('sender or action is still in progress')
    expect(f.rows()).toEqual(before); expect(f.read('launch-recovery', f.launch)).toBeUndefined()
  } finally { release(); await sending }
  expect((await f.request('arm')).code).toBe(0)
  expect(f.calls).toEqual([])
}))

test('boot recovery retains a late confirmed identity and holds a queued task after explicit resume', () => recoveryFixture(async f => {
  await f.request('arm')
  const terminal: CoreTerminal = { address: 'late-terminal', pid: 99, state: 'live', created_ms: 7, argv: ['codex'], cwd: '/retained-worktree', rows: 24, cols: 80, labels: { 'shepherdr.installation': f.read<LaunchRecovery>('launch-recovery', f.launch)!.installation, 'shepherdr.launch': f.launch } }
  ;(f.source.core.current.terminals as Map<string, CoreTerminal>).set(terminal.address, terminal)
  f.source.agents.reconcile()
  expect(f.read('launch-attempt', f.launch)).toMatchObject({ state: 'confirmed' })
  f.boot.value = { ...f.boot.value, boot: nextBoot }; terminal.state = 'finished'
  expect((await f.request('settle')).code).toBe(0)
  expect(f.read('agent', f.chat)).toMatchObject({ terminal: 'late-terminal', pid: 99, session: f.agent.session, speed: 'fast' })
  const task = f.source.tasks.get('EX-1')!
  f.source.store.set('task', task.id, { ...task, workflow: 'queued', capacity: 'Previous queue' })
  expect((await f.request('resume', ['--cancel-queued'])).code).toBe(0)
  await f.source.tasks.tick(); f.source.retryPending(); await new Promise<void>(resolve => setImmediate(resolve))
  expect(f.calls).toEqual([])
  expect(f.read('task', task.id)).toMatchObject({ workflow: 'queued', folder: '/retained-worktree', branch: 'work/retained' })
  await f.source.tasks.launch(f.source.tasks.get(task.id)!)
  const runs = f.calls.filter(call => call.method === 'terminal.run')
  expect(runs).toHaveLength(2) // Fresh coordinator, then the exact retained worker session.
  expect(runs[1]!.params.cwd).toBe('/retained-worktree')
  expect(runs[1]!.params.argv).toContain('33333333-3333-4333-8333-333333333333')
  expect(f.source.agents.get(f.chat)).toMatchObject({ kind: 'codex', model: 'gpt-6.1-sol', effort: 'high', speed: 'fast', provider: f.agent.provider })
}, 'task'))

test('boot recovery interruption after revocation leaves an armed durable hold for exact retry', () => recoveryFixture(async f => {
  await f.request('arm'); f.boot.value = { ...f.boot.value, boot: nextBoot }
  const revoke = f.source.mailbox.revoke.bind(f.source.mailbox)
  f.source.mailbox.revoke = (chat, launch) => { revoke(chat, launch); throw Error('Interrupted after grant revocation') }
  expect((await f.request('settle')).code).toBe(1)
  expect(f.read<LaunchRecovery>('launch-recovery', f.launch)?.phase).toBe('armed')
  expect(f.read('launch-recovery-hold', f.chat)).toBe(f.launch)
  expect(f.read('launch-attempt', f.launch)).toMatchObject({ state: 'submission-uncertain' })
  expect(f.source.mailbox.active().some(row => row.session === f.launch)).toBe(false)
  f.source.mailbox.revoke = revoke
  expect((await f.request('settle')).code).toBe(0)
}))

test('boot recovery refuses unsupported proof, remote execution and expired operator authority', () => recoveryFixture(async f => {
  const before = f.rows()
  f.boot.value.host = 'not-a-platform-identity'
  expect((await f.request('arm')).code).toBe(1); expect(f.rows()).toEqual(before)
  f.boot.value.host = 'a'.repeat(64)
  f.source.store.set('agent', f.chat, { ...f.agent, machine: 'remote-host' })
  const remote = f.rows()
  expect((await f.request('arm')).code).toBe(1); expect(f.rows()).toEqual(remote)
  f.source.store.set('agent', f.chat, f.agent)
  const controller = new AbortController(); controller.abort()
  await expect(f.source.launchRecovery.operator(['recover-launch', 'arm', f.chat, f.launch], controller.signal, performance.now() + 1000)).rejects.toThrow('expired')
  await expect(f.source.launchRecovery.operator(['recover-launch', 'arm', f.chat, f.launch], new AbortController().signal, 0)).rejects.toThrow('expired')
  expect(f.rows()).toEqual(before)
  if (process.platform !== 'darwin') await expect(readHostBoot()).rejects.toThrow('unsupported')
}))

test('boot recovery real operator peer loss during host observation cannot commit', () => recoveryFixture(async f => {
  let arrived!: () => void, release!: () => void, aborted!: (reason: unknown) => void, finished!: () => void
  const reached = new Promise<void>(resolve => { arrived = resolve }), gate = new Promise<void>(resolve => { release = resolve })
  const lost = new Promise<unknown>(resolve => { aborted = resolve }), complete = new Promise<void>(resolve => { finished = resolve })
  const operate = f.source.launchRecovery.operator.bind(f.source.launchRecovery)
  f.source.launchRecovery.operator = async (args, signal, expires) => {
    signal.addEventListener('abort', () => aborted(signal.reason), { once: true })
    try { return await operate(args, signal, expires) } finally { finished() }
  }
  f.boot.before = async () => { arrived(); await gate }
  const before = f.rows(), peer = createConnection(f.operatorPath)
  try {
    await once(peer, 'connect')
    peer.write(JSON.stringify({ args: ['recover-launch', 'arm', f.chat, f.launch] }) + '\n')
    await reached
    const closed = once(peer, 'close'); peer.destroy(); await closed
    // Observe the server's real peer-loss signal, not a caller-created AbortController
    // or its five-second expiry. The boot reader remains blocked until that signal.
    expect(String(await lost)).toContain('Recovery operator peer disconnected')
  } finally { peer.destroy(); release(); await complete }
  expect(f.rows()).toEqual(before); expect(f.calls).toEqual([])
}))

test('boot recovery rejects legacy EOF requests before reading host evidence', () => recoveryFixture(async f => {
  let observed = false
  f.boot.before = async () => { observed = true }
  const before = f.rows(), peer = createConnection(f.operatorPath), chunks: Buffer[] = []
  peer.on('data', bytes => chunks.push(Buffer.from(bytes)))
  const ended = once(peer, 'end')
  await once(peer, 'connect')
  peer.end(JSON.stringify({ args: ['recover-launch', 'arm', f.chat, f.launch] }))
  await ended
  const result = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  expect(result).toMatchObject({ code: 1, out: expect.stringContaining('newline-framed request') })
  expect(observed).toBe(false); expect(f.rows()).toEqual(before)
}))

for (const selection of [{ kind: 'claude' }, { model: 'different-deployment' }, { effort: 'low' }, { speed: 'normal' }] as const) test(`boot recovery public task Restart refuses changed ${Object.keys(selection)[0]} before effects`, () => recoveryFixture(async f => {
  await f.request('arm'); f.boot.value = { ...f.boot.value, boot: nextBoot }
  await f.request('settle'); await f.request('resume', ['--cancel-queued'])
  f.source.store.set('models', `${f.space.machine}:codex`, { models: [], efforts: ['low', 'high'] })
  const effects: string[] = []
  f.source.tasks.git.ensureWorktree = async () => { effects.push('checkout'); return false }
  f.source.browsers.close = async () => { effects.push('browser') }
  const before = f.rows()
  await expect(f.source.act({ type: 'restart', chat: f.chat, kind: 'codex', ...selection })).rejects.toThrow('first recovered continuation')
  expect(f.rows()).toEqual(before); expect(effects).toEqual([]); expect(f.calls).toEqual([])
}, 'task'))

test('boot recovery normal coordinator task start recognizes settled execution without a terminal', () => recoveryFixture(async f => {
  await f.request('arm'); f.boot.value = { ...f.boot.value, boot: nextBoot }
  await f.request('settle'); await f.request('resume', ['--cancel-queued'])
  const coordinator = await f.source.agents.launch(f.space, f.space.id, 'codex', 'Wait for the human', { model: 'gpt-6.1-sol', effort: 'high' })
  const grant = f.source.mailbox.active().find(row => row.session === coordinator.launch)!
  f.calls.length = 0
  const result = await f.source.tasks.cli(grant, ['task', 'start', 'EX-1', 'Fresh explicit instruction'])
  expect(result.code).toBe(0)
  const runs = f.calls.filter(call => call.method === 'terminal.run')
  expect(runs).toHaveLength(1); expect(runs[0]!.params.cwd).toBe('/retained-worktree')
  expect(runs[0]!.params.argv).toContain('33333333-3333-4333-8333-333333333333')
  expect(f.read('agent', f.chat)).toMatchObject({ recoveredFrom: f.launch, session: f.agent.session, model: 'gpt-6.1-sol', effort: 'high', speed: 'fast', provider: f.agent.provider })
  expect(f.read('pending-send', 'submitted')).toMatchObject({ state: 'uncertain' })
}, 'task'))

test('boot recovery public continuation with a missing native session refuses a fresh fallback', () => recoveryFixture(async f => {
  await f.request('arm'); f.boot.value = { ...f.boot.value, boot: nextBoot }
  await f.request('settle'); await f.request('resume', ['--cancel-queued'])
  await f.source.act({ type: 'restart', chat: f.chat, kind: 'codex', model: 'gpt-6.1-sol', effort: 'high', speed: 'fast' })
  const current = f.source.agents.get(f.chat)!, terminal = f.source.agents.terminal(current)!
  expect(f.read('agent', f.chat)).toMatchObject({ recoveredFrom: f.launch })
  terminal.state = 'finished'; terminal.reason = 'exited'; terminal.exit_code = 1
  const call = f.source.core.call.bind(f.source.core)
  f.source.core.call = async <T>(method: string, params: Record<string, unknown> = {}) => method === 'terminal.read'
    ? { text: 'ERROR: No saved session found with ID 33333333-3333-4333-8333-333333333333' } as T : call<T>(method, params)
  await f.source.failedStarts.tick(); await f.source.failedStarts.tick(); await f.source.failedStarts.tick()
  expect(f.calls.filter(call => call.method === 'terminal.run')).toHaveLength(1)
  expect(f.read('agent', f.chat)).toMatchObject({ launch: current.launch, recoveredFrom: f.launch, session: f.agent.session, model: 'gpt-6.1-sol', effort: 'high', speed: 'fast', provider: f.agent.provider, state: 'idle' })
  expect(f.read('pending-send', `session-gone-${current.launch}`)).toBeUndefined()
  expect(f.source.store.all<{ text?: string }>(`message:${f.chat}`).some(row => row.text?.includes('no fresh session was started'))).toBe(true)
}))

test('boot recovery human executable routes to private operator and exposes no HTTP or agent action', () => recoveryFixture(async f => {
  const env = { ...process.env, SHEPHERDR_CORE_CREDENTIAL: undefined, SHEPHERDR_BACKEND: undefined, SHEPHERDR_HOME: f.home }
  const root = join(import.meta.dir, '..'), command = join(root, 'bin/shepherdr')
  expect((await runChild([command, 'recover-launch', 'status', f.chat, f.launch, '--home', f.home], { env })).toString()).toBe(`${f.launch}: not-armed\n`)
  await expect(runChild([process.execPath, join(root, 'helper/core-operator.ts'), 'recover-launch', 'arm', f.chat, f.launch], { env: { ...env, SHEPHERDR_BACKEND: 'core' } })).rejects.toThrow('Agents must use their authenticated core mailbox')
  const app = startApp({ source: f.source, dist: '/unused', port: 0 })
  try {
    const response = await fetch(`http://127.0.0.1:${app.port}/api/action`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ type: 'recover-launch', operation: 'arm', chat: f.chat, launch: f.launch }) })
    expect(response.status).toBe(500)
    expect(await response.text()).toContain('has not implemented recover-launch')
    expect(f.read('launch-recovery', f.launch)).toBeUndefined()
  } finally { app.stop(true) }
}))


for (const entry of ['send', 'start'] as const) test(`boot recovery implicit task ${entry} keeps the retained Azure deployment`, () => recoveryFixture(async f => {
  expect(f.read<CoreTask>('task', 'EX-1')?.model).toBe('gpt-6.1-sol')
  expect(f.agent.model).toBe('team-codex')
  const task = f.source.tasks.get('EX-1')!
  f.source.store.set('task', task.id, { ...task, effort: 'low', speed: 'normal' })
  await f.request('arm'); f.boot.value = { ...f.boot.value, boot: nextBoot }
  await f.request('settle'); await f.request('resume', ['--cancel-queued'])
  const coordinator = await f.source.agents.launch(f.space, f.space.id, 'codex', 'Wait for the human', { model: 'gpt-6.1-sol', effort: 'high' })
  const grant = f.source.mailbox.active().find(row => row.session === coordinator.launch)!
  f.calls.length = 0
  if (entry === 'start') expect((await f.source.tasks.cli(grant, ['task', 'start', 'EX-1', 'Fresh instruction'])).code).toBe(0)
  else await f.source.tasks.deliver('EX-1', f.chat, 'Fresh instruction', false, true)
  const runs = f.calls.filter(call => call.method === 'terminal.run')
  expect(runs).toHaveLength(1)
  expect(runs[0]!.params.argv).toContain('33333333-3333-4333-8333-333333333333')
  expect(f.read('agent', f.chat)).toMatchObject({ recoveredFrom: f.launch, model: 'team-codex', effort: 'high', speed: 'fast', session: f.agent.session, provider: f.agent.provider })
  expect(f.read('task', 'EX-1')).toMatchObject({ model: 'gpt-6.1-sol', folder: '/retained-worktree', branch: 'work/retained' })
  expect(f.read('pending-send', 'submitted')).toMatchObject({ state: 'uncertain' })
}, 'task', 'team-codex'))

for (const entry of ['launch', 'restart'] as const) test(`boot recovery explicit task ${entry} still refuses a different Azure deployment`, () => recoveryFixture(async f => {
  await f.request('arm'); f.boot.value = { ...f.boot.value, boot: nextBoot }
  await f.request('settle'); await f.request('resume', ['--cancel-queued'])
  f.source.store.set('models', `${f.space.machine}:codex`, {
    models: [{ id: 'different-deployment', label: 'Different deployment', efforts: ['high'] }], efforts: ['high'],
  })
  const effects: string[] = []
  f.source.tasks.git.ensureWorktree = async () => { effects.push('checkout'); return false }
  f.source.browsers.close = async () => { effects.push('browser') }
  const attempt = entry === 'launch'
    ? f.source.tasks.launch(f.source.tasks.get('EX-1')!, 'Explicit change', 'different-deployment')
    : f.source.act({ type: 'restart', chat: f.chat, kind: 'codex', model: 'different-deployment' })
  await expect(attempt).rejects.toThrow('first recovered continuation')
  expect(f.read('agent', f.chat)).toMatchObject({ launch: f.launch, model: 'team-codex', session: f.agent.session })
  expect(effects).toEqual([]); expect(f.calls).toEqual([])
}, 'task', 'team-codex'))

for (const scope of ['chat', 'place'] as const) for (const timing of ['before', 'during-profile'] as const) test(`boot recovery task start preserves metadata when ${scope} is held ${timing}`, () => recoveryFixture(async f => {
  // A confirmed finished task passes the old-process gate. Without the hold
  // checks, start clears retained metadata before launchNow finally refuses.
  const previous = [...f.source.core.current.terminals.values()][0]!
  const finished: CoreTerminal = { ...previous, address: 'late-finished-task', pid: 99, created_ms: 99, state: 'finished', labels: { ...previous.labels, 'shepherdr.launch': f.launch } }
  ;(f.source.core.current.terminals as Map<string, CoreTerminal>).set(finished.address, finished)
  f.source.agents.reconcile()
  const coordinator = await f.source.agents.launch(f.space, f.space.id, 'codex', 'Wait', { model: 'gpt-6.1-sol', effort: 'high' })
  const grant = f.source.mailbox.active().find(row => row.session === coordinator.launch)!
  const task = f.source.tasks.get('EX-1')!
  f.source.store.set('task', task.id, { ...task, startError: 'Retain error', readyHead: 'retained-head', approvedHead: 'approved-head', mergeQuestion: 'retained-question' })
  const held = scope === 'chat' ? f.chat : f.space.id
  if (timing === 'before') f.source.store.set('launch-recovery-hold', held, f.launch)
  const before = f.read('task', task.id), agent = f.read('agent', f.chat)
  f.calls.length = 0
  const starting = f.source.tasks.start(grant, task.id)
  // profile is async even when no access-profile change is needed. Publish the
  // hold at its await boundary, before start can mutate workflow metadata.
  if (timing === 'during-profile') f.source.store.set('launch-recovery-hold', held, f.launch)
  await expect(starting).rejects.toThrow('held')
  expect(f.read('task', task.id)).toEqual(before); expect(f.read('agent', f.chat)).toEqual(agent)
  expect(f.calls).toEqual([])
}, 'task'))

for (const entry of ['deliver', 'fresh', 'backup'] as const) test(`boot recovery task ${entry} refuses a coordinator hold before mutation`, () => recoveryFixture(async f => {
  const task = f.source.tasks.get('EX-1')!
  f.source.store.set('task', task.id, { ...task, workflow: entry === 'backup' ? 'working' : 'todo' })
  f.source.store.set('launch-recovery-hold', f.space.id, f.launch)
  const before = f.rows()
  const action = entry === 'deliver' ? f.source.tasks.deliver(task.id, f.chat, 'Do not send')
    : entry === 'fresh' ? f.source.tasks.startFresh(task.id, f.launch, 'Do not erase the session')
    : f.source.tasks.providerFallback(task.id, f.launch, 'Do not switch provider')
  await expect(action).rejects.toThrow('held')
  expect(f.rows()).toEqual(before); expect(f.calls).toEqual([])
}, 'task'))

for (const entry of ['stop', 'close', 'delete'] as const) test(`boot recovery task ${entry} cleans up after replacing the terminal-less recovered launch`, () => recoveryFixture(async f => {
  await f.request('arm'); f.boot.value = { ...f.boot.value, boot: nextBoot }
  await f.request('settle'); await f.request('resume', ['--cancel-queued'])
  await f.source.act({ type: 'restart', chat: f.chat, kind: 'codex', model: 'gpt-6.1-sol', effort: 'high', speed: 'fast' })
  const replacement = f.source.agents.get(f.chat)!, terminal = f.source.agents.terminal(replacement)!
  const call = f.source.core.call.bind(f.source.core), killed: string[] = []
  f.source.core.call = async <T>(method: string, params: Record<string, unknown> = {}) => {
    if (method === 'terminal.kill') { killed.push(String(params.terminal)); f.source.core.current.terminals.get(String(params.terminal))!.state = 'finished'; return {} as T }
    return call<T>(method, params)
  }
  f.source.tasks.git.run = async () => '' // This regression proves lifecycle cleanup; checkout preservation has its own suite.
  await f.source.act({ type: entry, chat: f.chat })
  expect(killed).toEqual([terminal.address]); expect(terminal.state).toBe('finished')
  if (entry === 'delete') expect(f.read('task', 'EX-1')).toBeUndefined()
  else expect(f.read('task', 'EX-1')).toMatchObject({ workflow: entry === 'stop' ? 'todo' : 'closed' })
  expect(f.read('launch-attempt', f.launch)).toMatchObject({ chat: f.chat, launch: f.launch, state: 'execution-ended-after-host-reboot' })
}, 'task'))

test('boot recovery coordinator resume cancels owned descendant queues and preserves uncertain and unrelated work', () => recoveryFixture(async f => {
  const task = { ...recoveryTask(f.space), reviewChat: 'custom-review' }, unrelated = recoveryTask({ ...f.space, id: 'other-space' }, 'EX-10')
  f.source.store.set('task', task.id, task); f.source.store.set('task', unrelated.id, unrelated)
  const cancelled = [task.chat, task.reviewChat, `${task.id}/Reviewer-2`, `${task.id}/Child`, `${task.id}/Child/Nested`]
  for (const [index, chat] of cancelled.entries()) f.source.store.set('pending-send', `descendant-${index}`, { id: `descendant-${index}`, chat, text: 'Old queued work', state: 'queued' } satisfies PendingSend)
  const uncertain: PendingSend = { id: 'child-uncertain', chat: `${task.id}/Child`, text: 'Unknown submission', state: 'uncertain', submission: { launch: 'child-launch', promptHash: 'child-hash' } }
  const outside: PendingSend = { id: 'outside', chat: `${unrelated.id}/Child`, text: 'Unrelated work', state: 'queued' }
  f.source.store.set('pending-send', uncertain.id, uncertain); f.source.store.set('pending-send', outside.id, outside)
  await f.request('arm'); f.boot.value = { ...f.boot.value, boot: nextBoot }
  await f.request('settle')
  expect((await f.request('resume', ['--cancel-queued'])).code).toBe(0)
  expect(cancelled).toHaveLength(5)
  for (const [index, chat] of cancelled.entries()) {
    expect(f.read('pending-send', `descendant-${index}`)).toMatchObject({ chat, state: 'cancelled' })
    expect(f.read(`message:${chat}`, `cancelled-descendant-${index}`)).toMatchObject({ text: 'Stopped before your saved message was sent.' })
  }
  expect(f.read('pending-send', 'queued')).toMatchObject({ state: 'cancelled' })
  expect(f.read('pending-send', uncertain.id)).toEqual(uncertain); expect(f.read('pending-send', outside.id)).toEqual(outside)
  expect(f.read('pending-send', 'submitted')).toMatchObject({ state: 'uncertain' })
  expect(f.read('launch-recovery-hold', f.chat)).toBeUndefined(); expect(f.calls).toEqual([])
}))


test('boot recovery final task admission fences a newly held coordinator place', () => recoveryFixture(async f => {
  const task = recoveryTask(f.space)
  f.source.store.set('task', task.id, task)
  const prepared = await f.source.agents.preflight(f.space, task.chat, 'codex', { model: task.model, effort: task.effort })
  expect((await f.request('arm')).code).toBe(0)
  const before = f.rows()
  expect(() => f.source.agents.admit(prepared)).toThrow('held')
  expect(f.rows()).toEqual(before); expect(f.calls).toEqual([])
}))

test('boot recovery task delivery rechecks a coordinator hold after its asynchronous label', () => recoveryFixture(async f => {
  await f.request('arm'); f.boot.value = { ...f.boot.value, boot: nextBoot }
  await f.request('settle'); await f.request('resume', ['--cancel-queued'])
  await f.source.act({ type: 'restart', chat: f.chat, kind: 'codex', model: 'gpt-6.1-sol', effort: 'high', speed: 'fast' })
  f.source.agents.update(f.source.agents.get(f.chat)!, { state: 'idle' })
  const call = f.source.core.call.bind(f.source.core)
  f.source.core.call = async <T>(method: string, params: Record<string, unknown> = {}) => {
    if (method === 'terminal.label') f.source.store.set('launch-recovery-hold', f.space.id, f.launch)
    return call<T>(method, params)
  }
  f.calls.length = 0
  await expect(f.source.tasks.deliver('EX-1', f.chat, 'Do not dispatch after the hold', false, true)).rejects.toThrow('held')
  expect(f.calls.filter(call => call.method === 'terminal.send' || call.method === 'terminal.run')).toEqual([])
  expect(f.read('agent', f.chat)).toMatchObject({ session: f.agent.session, model: f.agent.model })
}, 'task'))


test('boot recovery task backup rechecks its coordinator hold after reading handover context', () => recoveryFixture(async f => {
  const task = f.source.tasks.get('EX-1')!
  f.source.store.set('task', task.id, { ...task, workflow: 'working' })
  f.source.settings.backupFor = () => ({ kind: 'claude', model: undefined, effort: undefined })
  f.source.tasks.git.run = async () => { f.source.store.set('launch-recovery-hold', f.space.id, f.launch); return '' }
  const before = f.read('task', task.id), agent = f.read('agent', f.chat)
  await expect(f.source.tasks.providerFallback(task.id, f.launch, 'Provider unavailable')).rejects.toThrow('held')
  expect(f.read('task', task.id)).toEqual(before); expect(f.read('agent', f.chat)).toEqual(agent)
  expect(f.calls).toEqual([])
}, 'task'))
