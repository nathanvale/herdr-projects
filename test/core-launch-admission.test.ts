import { expect, test } from 'bun:test'
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CoreSource } from '../server/core/source.ts'
import { CoreStore } from '../server/core/store.ts'
import type { LaunchAttempt } from '../server/core/launches.ts'
import type { CoreSpace } from '../server/core/model.ts'
import type { CoreTerminal } from '../server/core/protocol.ts'
import type { CoreTask } from '../server/core/tasks.ts'

function setup(home: string) {
  const source = new CoreSource({ home, port: 0, session: 'test', socket: '/unused', binary: 'hc', plugins: false })
  const space: CoreSpace = { id: 'space', machine: 'machine', name: 'Example', folder: '/unused', base: 'main', prefix: 'EX', mode: 'regular', added: 1 }
  const fresh = !source.store.get('space', space.id)
  if (fresh) source.store.set('space', space.id, space)
  source.route = async () => undefined
  source.core.current.connected = true
  if (fresh) {
  source.settings.set('provider.route', 'Azure Foundry')
  source.settings.set('azure.claudeResource', 'example')
  source.settings.set('azure.claudeDeployment', 'claude-sonnet-5-5')
  source.settings.set('azure.codexEndpoint', 'https://example.openai.azure.com/openai/v1')
  source.settings.set('azure.codexDeployment', 'gpt-6.1-sol')
  }
  const runs: Record<string, unknown>[] = [], effects: string[] = []
  source.core.call = async <T>(method: string, params: Record<string, unknown> = {}) => {
    if (method === 'machine.exec') return { code: 0, stdout: '', stderr: '', timed_out: false, truncated: false } as T
    if (method === 'terminal.run') {
      runs.push(params)
      const terminal = { address: `t${runs.length}`, pid: runs.length, state: 'live', labels: params.labels, created_ms: runs.length } as CoreTerminal
      ;(source.core.current.terminals as Map<string, CoreTerminal>).set(terminal.address, terminal)
      return terminal as T
    }
    if (method === 'terminal.label') return {} as T
    throw Error('Unexpected core method: '+method)
  }
  source.tasks.git.ensureWorktree = async () => { effects.push('worktree'); return false }
  source.tasks.git.addWorktree = async () => { effects.push('add-worktree') }
  source.tasks.seedIncludes = async () => { effects.push('includes') }
  source.browsers.close = async () => { effects.push('browser') }
  source.files.exec = async () => { effects.push('files'); return Buffer.from('') }
  const close = () => { source.stop(); source.mailbox.close(); source.store.close() }
  return { source, space, runs, effects, close }
}
async function fixture(work: (f: ReturnType<typeof setup>) => Promise<void>) {
  const home = mkdtempSync(join(tmpdir(), 'shep-admission-')), f = setup(home)
  try { await work(f) } finally { f.close(); rmSync(home, { recursive: true, force: true }) }
}
function task(f: ReturnType<typeof setup>): CoreTask {
  const value: CoreTask = { id: 'EX-1', chat: 'EX-1/Agent', name: 'Held task', desc: 'Keep this brief and wait', place: f.space.id, machine: f.space.machine,
    folder: '/unused-worktree', repo: f.space.folder, branch: 'work/1-task', base: 'main', kind: 'claude', deployment: 'claude-sonnet-5-5',
    workflow: 'todo', status: 'todo', state: 'To do', mergePolicy: 'ask', after: ['EX-0'], review: { on: false, kind: 'codex', rounds: 3, mustFix: 'major' }, age: 'now', created: new Date().toISOString(), on: 'test' }
  f.source.store.set('task', value.id, value)
  return value
}
function barrier() {
  let release!: () => void, reached!: () => void
  const wait = new Promise<void>(resolve => { release = resolve })
  const ready = new Promise<void>(resolve => { reached = resolve })
  return { wait, ready, release, reached }
}

for (const route of ['Personal', 'Azure Foundry'] as const) test(`task restart replaces a finished coordinator without stale parent admission (${route})`, () => fixture(async f => {
  f.source.settings.set('provider.route', route)
  f.source.machineConnected = () => true
  const row = task(f)
  const parent = await f.source.agents.launch(f.space, f.space.id, 'claude', 'Wait')
  const worker = await f.source.agents.launch(f.space, row.chat, 'claude', 'Wait', { role: 'task', parent })
  f.source.agents.terminal(parent)!.state = 'finished'
  const oldTerminal = f.source.agents.terminal(worker)!, kills: string[] = []
  const call = f.source.core.call.bind(f.source.core)
  f.source.core.call = async <T>(method: string, params: Record<string, unknown> = {}, timeout?: number) => {
    if (method !== 'terminal.kill') return call<T>(method, params, timeout)
    kills.push(String(params.terminal)); oldTerminal.state = 'finished'; return {} as T
  }
  await f.source.act({ type: 'restart', chat: row.chat, kind: 'claude' })
  const reader = new CoreStore(f.source.config.home)
  try {
    const newParent = reader.get<import('../server/core/model.ts').CoreAgent>('agent', f.space.id)!
    const newWorker = reader.get<import('../server/core/model.ts').CoreAgent>('agent', row.chat)!
    expect(newParent.launch).not.toBe(parent.launch); expect(newWorker.launch).not.toBe(worker.launch)
    expect(reader.get<CoreTask>('task', row.id)).toMatchObject({ desc: row.desc, after: ['EX-0'], mergePolicy: 'ask', workflow: 'todo' })
    expect(reader.get<CoreTask>('task', row.id)?.startError).toBeUndefined()
    expect(newWorker.provider?.route).toBe(route === 'Personal' ? 'personal' : 'azure-foundry')
    expect(f.runs).toHaveLength(4)
    expect(f.runs[3]!.parent).toBe(newParent.terminal)
    expect(kills).toEqual([oldTerminal.address])
  } finally { reader.close() }
}))

for (const change of ['settings', 'selection'] as const) test(`launch admission refuses ${change} changed after admission`, () => fixture(async f => {
  const prepared = await f.source.agents.preflight(f.space, 'chat', 'claude')
  f.source.agents.admit(prepared)
  if (change === 'settings') f.source.settings.set('azure.claudeResource', 'changed')
  else f.source.agents.saveSelection(f.space, 'chat', f.source.agents.selectionToken('chat'), { kind: 'claude', deployment: 'claude-sonnet-5-5' })
  await expect(f.source.agents.launch(f.space, 'chat', 'claude', 'Wait', { prepared })).rejects.toThrow('Selection changed')
  expect(f.runs).toEqual([]); expect(f.source.mailbox.active()).toEqual([])
}))

for (const stage of ['before-record', 'before-submit'] as const) test(`launch admission rechecks stale settings ${stage}`, () => fixture(async f => {
  if (stage === 'before-record') {
    const issue = f.source.mailbox.issue.bind(f.source.mailbox)
    f.source.mailbox.issue = (...args) => { const grant = issue(...args); queueMicrotask(() => f.source.settings.set('azure.claudeResource', 'changed')); return grant }
  } else {
    const set = f.source.store.set.bind(f.source.store)
    f.source.store.set = (kind, key, value) => { set(kind, key, value); if (kind === 'agent-launch') queueMicrotask(() => f.source.settings.set('azure.codexDeployment', 'changed')) }
  }
  await expect(f.source.agents.launch(f.space, 'chat', stage === 'before-submit' ? 'codex' : 'claude', 'Wait', { readOnly: true })).rejects.toThrow('Selection changed')
  const reader = new CoreStore(f.source.config.home)
  try {
    expect(reader.all<LaunchAttempt>('launch-attempt').map(row => row.state)).toEqual(['cancelled'])
    expect(reader.get('agent', 'chat')).toBeUndefined()
  } finally { reader.close() }
  expect(f.runs).toEqual([]); expect(f.source.mailbox.active()).toEqual([])
}))

test('launch admission commits uncertainty and dispatches before a queued settings edit', () => fixture(async f => {
  const set = f.source.store.set.bind(f.source.store), observed: string[] = []
  f.source.store.set = (kind, key, value) => {
    set(kind, key, value)
    if (kind === 'launch-attempt' && (value as LaunchAttempt).state === 'submission-uncertain') queueMicrotask(() => { observed.push('settings'); f.source.settings.set('azure.claudeResource', 'changed') })
  }
  const call = f.source.core.call.bind(f.source.core)
  f.source.core.call = <T>(method: string, params?: Record<string, unknown>, timeout?: number) => { if (method === 'terminal.run') observed.push('dispatch'); return call<T>(method, params, timeout) }
  const agent = await f.source.agents.launch(f.space, 'chat', 'claude', 'Wait')
  expect(observed).toEqual(['dispatch', 'settings'])
  expect(f.runs).toHaveLength(1)
  expect(f.source.store.get<LaunchAttempt>('launch-attempt', agent.launch)?.state).toBe('confirmed')
}))

test('launch admission refuses shutdown after recording without submitting', () => fixture(async f => {
  const set = f.source.store.set.bind(f.source.store)
  f.source.store.set = (kind, key, value) => { set(kind, key, value); if (kind === 'agent-launch') queueMicrotask(() => { f.source.quiescing = true }) }
  await expect(f.source.agents.launch(f.space, 'chat', 'codex', 'Wait', { readOnly: true })).rejects.toThrow('stopping')
  expect(f.runs).toEqual([])
  expect(f.source.store.all<LaunchAttempt>('launch-attempt').map(row => row.state)).toEqual(['cancelled'])
}))

test('launch admission excludes a competing start while preflight is pending', () => fixture(async f => {
  const gate = barrier()
  f.source.route = async () => { gate.reached(); await gate.wait; return undefined }
  const first = f.source.agents.launch(f.space, 'chat', 'claude', 'Wait')
  try { await gate.ready; await expect(f.source.agents.launch(f.space, 'chat', 'claude', 'Wait')).rejects.toThrow('already starting') }
  finally { gate.release() }
  await first; expect(f.runs).toHaveLength(1)
}))

test('launch admission fences a recovered delayed operation and preserves replacement grants', () => fixture(async f => {
  // A read-only reviewer awaits local helper preparation after its durable record.
  // Cancel via an independently opened source while that continuation is pending.
  let second: ReturnType<typeof setup> | undefined, recovery!: Promise<void>
  const set = f.source.store.set.bind(f.source.store)
  let launch: string | undefined
  f.source.store.set = (kind, key, value) => {
    set(kind, key, value)
    if (kind === 'agent-launch' && !launch) {
      launch = key
      recovery = Promise.resolve().then(async () => {
        second = setup(f.source.config.home)
        second.source.agents.recoverUnsubmitted('chat', key)
        await second.source.agents.launch(second.space, 'chat', 'claude', 'Replacement')
      })
    }
  }
  try {
    await expect(f.source.agents.launch(f.space, 'chat', 'codex', 'Wait', { readOnly: true })).rejects.toThrow(/Launch (authority|identity) changed/)
    await recovery
    expect(f.runs).toEqual([]); expect(second!.runs).toHaveLength(1)
    expect(second!.source.mailbox.active().map(grant => grant.session)).toEqual([second!.source.agents.get('chat')!.launch])
    expect(second!.source.store.get<LaunchAttempt>('launch-attempt', launch!)?.state).toBe('cancelled')
  } finally { await recovery?.catch(() => {}); second?.close() }
}))

for (const point of ['claimed', 'recorded', 'uncertain', 'submitted'] as const) test(`launch admission crash recovery at ${point} reopens durable state`, async () => {
  const home = mkdtempSync(join(tmpdir(), 'shep-crash-'))
  let f: ReturnType<typeof setup> | undefined
  try {
    const child = Bun.spawn([process.execPath, join(import.meta.dir, 'fixtures/core-launch-crash.ts'), home, point], { env: { PATH: process.env.PATH ?? '' }, stdout: 'pipe', stderr: 'pipe' })
    expect(await child.exited).toBe(81)
    expect(await new Response(child.stderr).text()).toBe('')
    f = setup(home)
    const attempts = f.source.store.all<LaunchAttempt>('launch-attempt')
    expect(attempts).toHaveLength(1)
    const attempt = attempts[0]!
    if (point === 'recorded' || point === 'claimed') {
      expect(f.source.agents.get('chat')?.launch).toBe(point === 'recorded' ? attempt.launch : undefined)
      if (point === 'claimed') {
        await expect(f.source.agents.launch(f.space, 'chat', 'claude', 'Wait')).rejects.toThrow('previous start still owns')
        expect(f.runs).toEqual([])
      }
      expect(attempt.state).toBe('never-submitted')
      f.source.agents.recoverUnsubmitted('chat', attempt.launch)
      expect(f.source.agents.get('chat')).toBeUndefined()
      const fresh = await f.source.agents.launch(f.space, 'chat', 'claude', 'Wait')
      expect(fresh.launch).not.toBe(attempt.launch); expect(f.runs).toHaveLength(1)
    } else {
      expect(attempt.state).toBe('submission-uncertain')
      expect(() => f!.source.agents.recoverUnsubmitted('chat', attempt.launch)).toThrow('authority')
      await expect(f.source.agents.launch(f.space, 'chat', 'claude', 'Wait')).rejects.toThrow('unconfirmed')
      expect(f.runs).toEqual([])
      if (point === 'submitted') {
        const receipt = JSON.parse(readFileSync(join(home, 'fake-core-receipt.json'), 'utf8')) as CoreTerminal
        ;(f.source.core.current.terminals as Map<string, CoreTerminal>).set(receipt.address, receipt)
        f.source.agents.reconcile(); f.source.agents.reconcile()
        expect(f.source.agents.get('chat')).toMatchObject({ launch: attempt.launch, terminal: receipt.address })
        expect(f.source.store.get<LaunchAttempt>('launch-attempt', attempt.launch)?.state).toBe('confirmed')
        expect(f.source.core.current.terminals.size).toBe(1)
      } else expect(existsSync(join(home, 'fake-core-receipt.json'))).toBe(false)
    }
  } finally { f?.close(); rmSync(home, { recursive: true, force: true }) }
})

test('launch admission refuses an incompatible worker before task side effects and keeps holds', () => fixture(async f => {
  const row = task(f), before = structuredClone(row)
  row.deployment = 'invalid deployment'; f.source.store.set('task', row.id, row)
  await expect(f.source.tasks.launch(row)).rejects.toThrow('deployment')
  expect(f.effects).toEqual([]); expect(f.runs).toEqual([])
  expect(f.source.tasks.get(row.id)).toMatchObject({ desc: before.desc, after: before.after, mergePolicy: 'ask', workflow: 'todo' })
}))

test('launch admission checks required coordinator before checkout creation', () => fixture(async f => {
  const row = task(f)
  f.source.settings.set('coordinator.agent', 'Codex')
  f.source.settings.set('azure.codexEndpoint', '')
  await expect(f.source.tasks.launch(row)).rejects.toThrow()
  expect(f.effects).toEqual([]); expect(f.runs).toEqual([])
}))

test('launch admission refuses a changed parent before task worktree effects', () => fixture(async f => {
  const row = task(f), parent = await f.source.agents.launch(f.space, f.space.id, 'claude', 'Wait')
  f.runs.length = 0
  const gate = barrier()
  f.source.route = async () => { gate.reached(); await gate.wait; return undefined }
  const pending = f.source.tasks.launch(row)
  try { await gate.ready; f.source.store.set('agent', parent.chat, { ...parent, launch: 'replacement' }) }
  finally { gate.release() }
  await expect(pending).rejects.toThrow('Parent identity changed')
  expect(f.effects).toEqual([]); expect(f.runs).toEqual([])
}))

test('launch admission protects the initial task-add path before addWorktree', () => fixture(async f => {
  await expect(f.source.tasks.addInSpace(f.space, { title: 'New held task', brief: 'Preserve me', later: true, deployment: 'invalid deployment' })).rejects.toThrow('saved but could not start')
  expect(f.effects).toEqual([]); expect(f.runs).toEqual([])
  expect(f.source.tasks.all()).toHaveLength(1)
  expect(f.source.tasks.all()[0]).toMatchObject({ desc: 'Preserve me', workflow: 'todo' })
}))


test('launch admission rejects parent replacement after recording', () => fixture(async f => {
  const parent = await f.source.agents.launch(f.space, f.space.id, 'claude', 'Wait')
  f.runs.length = 0
  const set = f.source.store.set.bind(f.source.store)
  let replaced = false
  f.source.store.set = (kind, key, value) => {
    set(kind, key, value)
    if (kind === 'agent-launch' && !replaced) { replaced = true; queueMicrotask(() => set('agent', parent.chat, { ...parent, launch: 'replacement' })) }
  }
  await expect(f.source.agents.launch(f.space, 'child', 'codex', 'Wait', { parent, readOnly: true })).rejects.toThrow('Parent identity changed')
  expect(f.runs).toEqual([])
  expect(f.source.agents.get('child')).toBeUndefined()
}))

test('launch admission keeps a lost reply uncertain and reconciles its existing identity', () => fixture(async f => {
  const call = f.source.core.call.bind(f.source.core)
  f.source.core.call = async <T>(method: string, params?: Record<string, unknown>, timeout?: number) => {
    const value = await call<T>(method, params, timeout)
    if (method === 'terminal.run') throw Error('Reply lost')
    return value
  }
  await expect(f.source.agents.launch(f.space, 'chat', 'claude', 'Wait')).rejects.toThrow('Reply lost')
  const launch = f.source.agents.get('chat')!.launch
  const reader = new CoreStore(f.source.config.home)
  try { expect(reader.get<LaunchAttempt>('launch-attempt', launch)?.state).toBe('submission-uncertain') }
  finally { reader.close() }
  // Even a missing inventory cannot authorize retry or cancellation.
  const inventory = f.source.core.current.terminals
  f.source.core.current.terminals = new Map()
  expect(() => f.source.agents.recoverUnsubmitted('chat', launch)).toThrow('authority')
  await expect(f.source.agents.launch(f.space, 'chat', 'claude', 'Wait')).rejects.toThrow('unconfirmed')
  f.source.core.current.terminals = inventory
  f.source.agents.reconcile(); f.source.agents.reconcile()
  expect(f.runs).toHaveLength(1)
  expect(f.source.agents.get('chat')?.launch).toBe(launch)
  expect(f.source.store.get<LaunchAttempt>('launch-attempt', launch)?.state).toBe('confirmed')
}))


test('launch admission detects a competing task identity while its coordinator validates', () => fixture(async f => {
  const row = task(f)
  const preflight = f.source.agents.preflight.bind(f.source.agents)
  f.source.agents.preflight = async (...args) => {
    const admitted = await preflight(...args)
    if (args[1] === f.space.id) f.source.store.set('agent', row.chat, {
      chat: row.chat, space: f.space.id, machine: f.space.machine, role: 'task', kind: row.kind,
      launch: 'competing', grant: 'other-grant', hook: '/unused', started: 1, state: 'starting',
    })
    return admitted
  }
  await expect(f.source.tasks.launch(row)).rejects.toThrow('Launch identity changed')
  expect(f.effects).toEqual([]); expect(f.runs).toEqual([])
  expect(f.source.agents.get(row.chat)?.launch).toBe('competing')
}))
