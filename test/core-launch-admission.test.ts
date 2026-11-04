import { expect, test } from 'bun:test'
import { mkdtempSync, rmSync, readFileSync, existsSync, writeFileSync, appendFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CoreSession } from '../server/core/session.ts'
import { CoreSource } from '../server/core/source.ts'
import { CoreStore } from '../server/core/store.ts'
import type { LaunchAttempt } from '../server/core/launches.ts'
import { CoreLogs } from '../server/core/logs.ts'
import { runChild } from './child.ts'
import type { CoreAgent, PendingSend, CoreSpace } from '../server/core/model.ts'
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

for (const route of ['Personal', 'Azure Foundry'] as const) for (const timing of ['before-restart', 'during-kill'] as const) test(`task restart replaces a finished coordinator without stale parent admission (${route}, ${timing})`, () => fixture(async f => {
  f.source.settings.set('provider.route', route)
  f.source.machineConnected = () => true
  const row = task(f)
  const parent = await f.source.agents.launch(f.space, f.space.id, 'claude', 'Wait')
  const worker = await f.source.agents.launch(f.space, row.chat, 'claude', 'Wait', { role: 'task', parent })
  if (timing === 'before-restart') f.source.agents.terminal(parent)!.state = 'finished'
  const oldTerminal = f.source.agents.terminal(worker)!, kills: string[] = []
  const call = f.source.core.call.bind(f.source.core)
  f.source.core.call = async <T>(method: string, params: Record<string, unknown> = {}, timeout?: number) => {
    if (method !== 'terminal.kill') return call<T>(method, params, timeout)
    kills.push(String(params.terminal)); oldTerminal.state = 'finished'
    if (timing === 'during-kill') f.source.agents.terminal(parent)!.state = 'finished'
    return {} as T
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

for (const explicit of [false, true]) test(`task selection reset restores brief overrides and current role defaults (${explicit ? 'explicit' : 'inherited'})`, () => fixture(async f => {
  const row = task(f)
  f.source.settings.set('task.agent', 'Codex')
  f.source.settings.set('task.azure.codexDeployment', 'team-codex')
  f.source.settings.set('task.model', 'gpt-6.1-sol')
  f.source.settings.set('task.effort', 'high')
  row.kind = 'codex'; row.model = 'gpt-6.1-sol'; row.effort = 'high'; row.deployment = 'team-codex'
  if (explicit) row.overrides = { 'task.agent': 'codex', 'task.model': 'gpt-6.1-sol', 'task.effort': 'high' }
  f.source.store.set('task', row.id, row)
  const select = (deployment: string) => f.source.act({ type: 'select-agent', chat: row.chat,
    token: f.source.agents.selectionToken(row.chat), kind: 'claude', deployment, effort: 'high' })
  await select('claude-sonnet-5-5')
  expect(f.source.tasks.get(row.id)).toMatchObject({ kind: 'claude', deployment: 'claude-sonnet-5-5', effort: 'high' })
  expect(f.source.tasks.get(row.id)?.model).toBeUndefined()
  // Defaults can change while a per-task selection is saved. Explicit brief
  // requirements win on reset; otherwise use the newly configured role.
  f.source.settings.set('task.agent', 'Claude Code')
  f.source.settings.set('task.model', 'claude-sonnet-5-5')
  f.source.settings.set('task.effort', 'low')
  f.source.settings.set('task.azure.claudeDeployment', 'team-claude')
  await select('')
  const reader = new CoreStore(f.source.config.home)
  try {
    expect(reader.get<CoreTask>('task', row.id)).toMatchObject({
      kind: explicit ? 'codex' : 'claude', model: explicit ? 'gpt-6.1-sol' : 'claude-sonnet-5-5',
      effort: explicit ? 'high' : 'low', deployment: explicit ? 'team-codex' : 'team-claude',
      desc: row.desc, after: ['EX-0'], mergePolicy: 'ask', workflow: 'todo',
    })
    expect(reader.get<CoreTask>('task', row.id)?.overrides).toEqual(row.overrides)
    expect(reader.get('agent-selection', row.chat)).toBeUndefined()
    expect(reader.all('agent')).toEqual([]); expect(reader.all('launch-attempt')).toEqual([])
  } finally { reader.close() }
  expect(f.runs).toEqual([]); expect(f.effects).toEqual([]); expect(f.source.mailbox.active()).toEqual([])
}))

for (const route of ['Personal', 'Azure Foundry'] as const) test(`task restart survives unrelated settings edits while awaiting worker exit (${route})`, () => fixture(async f => {
  f.source.settings.set('provider.route', route)
  f.source.machineConnected = () => true
  const row = task(f), parent = await f.source.agents.launch(f.space, f.space.id, 'claude', 'Wait')
  const worker = await f.source.agents.launch(f.space, row.chat, 'claude', 'Wait', { role: 'task', parent })
  const gate = barrier(), call = f.source.core.call.bind(f.source.core)
  f.source.core.call = async <T>(method: string, params: Record<string, unknown> = {}, timeout?: number) => {
    if (method !== 'terminal.kill') return call<T>(method, params, timeout)
    gate.reached(); await gate.wait; f.source.agents.terminal(worker)!.state = 'finished'; return {} as T
  }
  const pending = f.source.act({ type: 'restart', chat: row.chat, kind: 'claude' })
  await gate.ready
  try {
    f.source.settings.set('time.zone', 'UTC')
    f.source.store.set('space', 'other', { ...f.space, id: 'other' })
    f.source.settings.set('tasks.archiveAfter', '30 days', 'other')
    f.source.settings.set('azure.claudeResource', 'different-resource', 'other')
  } finally { gate.release() }
  await pending
  const reader = new CoreStore(f.source.config.home)
  try {
    expect(reader.get<import('../server/core/model.ts').CoreAgent>('agent', row.chat)?.launch).not.toBe(worker.launch)
    expect(reader.get<CoreTask>('task', row.id)).toMatchObject({ after: ['EX-0'], workflow: 'todo', mergePolicy: 'ask', desc: row.desc })
    expect(reader.get<CoreTask>('task', row.id)?.startError).toBeUndefined()
  } finally { reader.close() }
  expect(f.runs).toHaveLength(3); expect(f.runs[2]!.parent).toBe(parent.terminal)
}))

for (const scope of ['all', 'm:machine', 'space']) test(`launch admission detects inherited settings changed away and back at ${scope}`, () => fixture(async f => {
  f.source.settings.set('azure.claudeResource', 'example', scope)
  const prepared = await f.source.agents.preflight(f.space, 'chat', 'claude')
  f.source.settings.set('azure.claudeResource', 'changed', scope)
  f.source.settings.set('azure.claudeResource', 'example', scope)
  await expect(f.source.agents.launch(f.space, 'chat', 'claude', 'Wait', { prepared })).rejects.toThrow('Selection changed')
  expect(f.runs).toEqual([]); expect(f.source.mailbox.active()).toEqual([])
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

for (const previous of [false, true]) test(`local non-submission releases only its own launch (${previous ? 'resume' : 'new'})`, () => fixture(async f => {
  f.source.settings.set('provider.route', 'Personal')
  const old = previous ? await f.source.agents.launch(f.space, 'chat', 'claude', 'Wait') : undefined
  if (old) f.source.agents.terminal(old)!.state = 'finished'
  const call = f.source.core.call
  // Exercise the real disconnected CoreSession gate, not a made-up core error.
  f.source.core.call = CoreSession.prototype.call.bind(f.source.core)
  await expect(f.source.agents.launch(f.space, 'chat', 'claude', 'Wait')).rejects.toThrow('Core is reconnecting')
  const reader = new CoreStore(f.source.config.home)
  try {
    const attempts = reader.all<LaunchAttempt>('launch-attempt')
    expect(attempts.filter(attempt => attempt.state === 'cancelled')).toHaveLength(1)
    expect(attempts.filter(attempt => attempt.state === 'submission-uncertain')).toEqual([])
    expect(reader.get('launch-claim', 'chat')).toBeUndefined()
    expect(reader.get('agent', 'chat')).toEqual(old)
  } finally { reader.close() }
  expect(f.source.mailbox.active().filter(grant => grant.session !== old?.launch)).toEqual([])
  expect(f.runs).toHaveLength(previous ? 1 : 0)
  f.source.core.call = call
  const replacement = await f.source.agents.launch(f.space, 'chat', 'claude', 'Wait')
  expect(replacement.terminal).toBeDefined()
  expect(f.runs).toHaveLength(previous ? 2 : 1)
}))

for (const finished of [false, true]) test(`task restart validates required coordinator before interrupting worker (${finished ? 'finished' : 'missing'})`, () => fixture(async f => {
  f.source.machineConnected = () => true
  const row = task(f)
  const parent = finished ? await f.source.agents.launch(f.space, f.space.id, 'codex', 'Wait') : undefined
  if (parent) f.source.agents.terminal(parent)!.state = 'finished'
  const worker = await f.source.agents.launch(f.space, row.chat, 'claude', 'Wait', { role: 'task' })
  f.source.settings.set('coordinator.agent', 'Codex')
  f.source.settings.set('azure.codexEndpoint', '')
  const calls: string[] = [], call = f.source.core.call.bind(f.source.core)
  f.source.core.call = async <T>(method: string, params?: Record<string, unknown>, timeout?: number) => {
    calls.push(method); return call<T>(method, params, timeout)
  }
  await expect(f.source.act({ type: 'restart', chat: row.chat, kind: 'claude' })).rejects.toThrow('https://RESOURCE.openai.azure.com/openai/v1')
  expect(calls).not.toContain('terminal.kill')
  expect(f.source.agents.get(row.chat)).toEqual(worker)
  expect(f.source.agents.terminal(worker)?.state).toBe('live')
  expect(f.source.mailbox.active().some(grant => grant.session === worker.launch)).toBe(true)
  expect(f.effects).toEqual([])
  expect(f.runs).toHaveLength(finished ? 2 : 1)
}))

test('task start retains a finished Azure coordinator binding and native session after defaults change', () => fixture(async f => {
  const row = task(f), parent = await f.source.agents.launch(f.space, f.space.id, 'claude', 'Wait', { effort: 'high' })
  f.source.agents.update(parent, { session: 'retained-native-session' })
  f.source.agents.terminal(parent)!.state = 'finished'
  f.source.settings.set('coordinator.agent', 'Codex')
  f.source.settings.set('azure.claudeDeployment', 'claude-haiku-5-5')
  await f.source.tasks.launch(row)
  const reader = new CoreStore(f.source.config.home)
  try {
    const current = reader.get<import('../server/core/model.ts').CoreAgent>('agent', f.space.id)!
    expect(current).toMatchObject({ kind: 'claude', model: parent.model, effort: 'high', session: 'retained-native-session', provider: parent.provider })
    expect(current.launch).not.toBe(parent.launch)
    expect(f.runs[1]!.argv).toContain('--resume')
    expect(f.runs[1]!.argv).toContain('retained-native-session')
    expect(f.runs[2]!.parent).toBe(current.terminal)
  } finally { reader.close() }
  expect(f.runs).toHaveLength(3)
}))

for (const route of ['Personal', 'Azure Foundry'] as const) for (const timing of ['validation', 'checkout'] as const) test(`task start replaces a coordinator that finishes during ${timing} (${route})`, () => fixture(async f => {
  f.source.settings.set('provider.route', route)
  const row = task(f), parent = await f.source.agents.launch(f.space, f.space.id, 'claude', 'Wait')
  const finish = () => { f.source.agents.terminal(parent)!.state = 'finished' }
  if (timing === 'validation') f.source.route = async () => { finish(); return undefined }
  else f.source.tasks.git.ensureWorktree = async () => { finish(); return false }
  await f.source.tasks.launch(row)
  const reader = new CoreStore(f.source.config.home)
  try {
    const current = reader.get<import('../server/core/model.ts').CoreAgent>('agent', f.space.id)!
    expect(current.launch).not.toBe(parent.launch)
    expect(f.runs[2]!.parent).toBe(current.terminal)
    expect(reader.get<CoreTask>('task', row.id)).toMatchObject({ desc: row.desc, after: row.after, workflow: 'todo', mergePolicy: 'ask' })
  } finally { reader.close() }
  expect(f.runs).toHaveLength(3)
}))

test('worker final submission refuses a parent that finished after recording', () => fixture(async f => {
  const parent = await f.source.agents.launch(f.space, f.space.id, 'claude', 'Wait')
  const set = f.source.store.set.bind(f.source.store)
  f.source.store.set = (kind, key, value) => {
    set(kind, key, value)
    if (kind === 'agent-launch') queueMicrotask(() => { f.source.agents.terminal(parent)!.state = 'finished' })
  }
  await expect(f.source.agents.launch(f.space, 'child', 'codex', 'Wait', { parent, readOnly: true })).rejects.toThrow('Parent is no longer running')
  expect(f.runs).toHaveLength(1)
  expect(f.source.agents.get('child')).toBeUndefined()
}))

test('task selector supplies known model effort metadata without discovery', () => fixture(async f => {
  const row = task(f)
  const result = await f.source.act({ type: 'restart-info', chat: row.chat })
  expect(result).toMatchObject({ ok: true, info: { clis: expect.arrayContaining([
    expect.objectContaining({ kind: 'claude', models: expect.arrayContaining([expect.objectContaining({ id: 'claude-sonnet-5-5', efforts: expect.arrayContaining(['high']) })]) }),
    expect.objectContaining({ kind: 'codex', models: expect.arrayContaining([expect.objectContaining({ id: 'gpt-6.1-sol', efforts: expect.arrayContaining(['high']) })]) }),
  ]) } })
  expect(f.runs).toEqual([]); expect(f.effects).toEqual([])
}))


// Production send entry -> launch -> persisted receipt -> real native reader.
// Only the existing core/worktree adapters are fake; no coding CLI is executed.
async function deliveryStart(f: ReturnType<typeof setup>, kind: 'claude' | 'codex', role: 'coordinator' | 'task', resume: boolean) {
  f.source.machineConnected = () => true
  f.source.store.set('health-sample', f.space.machine, { at: Date.now(), cores: 8, load: 1, memTotal: 1000, memUsed: 400, disks: [], gpus: [] })
  const row = role === 'task' ? task(f) : undefined
  if (row) {
    row.kind = kind; row.deployment = kind === 'claude' ? 'claude-sonnet-5-5' : 'gpt-6.1-sol'; row.workflow = 'working'
    f.source.store.set('task', row.id, row)
    await f.source.agents.launch(f.space, f.space.id, kind, 'Wait')
  } else f.source.settings.set('coordinator.agent', kind === 'claude' ? 'Claude Code' : 'Codex')
  const chat = row?.chat ?? f.space.id
  if (resume) {
    const agent = await f.source.agents.launch(f.space, chat, kind, 'Earlier turn', { role })
    f.source.agents.update(agent, { session: 'retained-native-session', state: 'idle' })
    f.source.agents.terminal(agent)!.state = 'finished'
  }
  return { chat, row }
}
async function sendDelivery(f: ReturnType<typeof setup>, chat: string) {
  await f.source.act({ type: 'send', chat, text: 'Continue with the same choice', cid: 'delivery-proof' })
  // Task send releases its existing action lock before the queued flush can run.
  for (let n = 0; n < 200; n++) {
    const item = f.source.store.get<PendingSend>('pending-send', 'delivery-proof')
    if (item?.state === 'uncertain' || item?.submission && f.source.agents.get(chat)?.terminal) return
    await Bun.sleep(5)
  }
  throw Error('The production send did not reach submission: ' + JSON.stringify({ pending: f.source.store.get('pending-send', 'delivery-proof'), task: f.source.tasks.forChat(chat) }))
}
function deliveryLog(f: ReturnType<typeof setup>, chat: string) {
  const agent = f.source.agents.get(chat)!, path = join(f.source.config.home, 'delivery-native.jsonl')
  writeFileSync(path, '')
  f.source.agents.update(agent, { transcript: path })
  f.source.agents.bun = async () => process.execPath
  f.source.files.exec = (_machine, argv, cwd, input) => runChild(argv, { cwd, input })
  const faults: string[] = []
  const logs = new CoreLogs(f.source.agents, f.source.files, f.source.store, () => {}, (_chat, error) => faults.push(error))
  let sequence = 0
  const observe = async (text: string) => {
    const id = `native-${++sequence}`, timestamp = new Date().toISOString()
    appendFileSync(path, JSON.stringify(agent.kind === 'claude'
      ? { uuid: id, timestamp, type: 'user', message: { role: 'user', content: text } }
      : { timestamp, type: 'response_item', payload: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] } }) + '\n')
    await logs.poll()
    expect(faults).toEqual([])
  }
  return { logs, observe }
}
for (const kind of ['claude', 'codex'] as const) for (const role of ['coordinator', 'task'] as const) for (const resume of [false, true]) {
  test(`launch delivery acknowledges exact native prompt (${kind}, ${role}, ${resume ? 'resume' : 'fresh'})`, () => fixture(async f => {
    const { chat, row } = await deliveryStart(f, kind, role, resume)
    await sendDelivery(f, chat)
    const agent = f.source.agents.get(chat)!, argv = f.runs.at(-1)!.argv as string[], wire = argv.at(-1)!
    const reader = new CoreStore(f.source.config.home), log = deliveryLog(f, chat)
    try {
      expect(argv[0]).toBe(kind)
      expect(agent.session).toBe(resume ? 'retained-native-session' : undefined)
      expect(wire).toContain(agent.launch)
      expect(reader.get<PendingSend>('pending-send', 'delivery-proof')).toMatchObject({ state: 'sending', submission: { launch: agent.launch } })
      // Same human suffix, a changed envelope, or an old launch is not this dispatch.
      await log.observe('Continue with the same choice')
      await log.observe(wire.replace(agent.launch, 'old-launch'))
      await log.observe(wire + ' altered')
      expect(reader.get<PendingSend>('pending-send', 'delivery-proof')?.state).toBe('sending')
      await log.observe(wire)
      expect(reader.get('pending-send', 'delivery-proof')).toBeUndefined()
      expect(reader.get(`message:${chat}`, 'delivery-proof')).toMatchObject({ text: 'Continue with the same choice', waiting: false, source: expect.any(String) })
      expect(log.logs.messages(chat).filter(message => message.text === wire)).toEqual([])
      if (row) expect(reader.get<CoreTask>('task', row.id)).toMatchObject({ after: ['EX-0'], desc: 'Keep this brief and wait', mergePolicy: 'ask' })
      const count = f.runs.length
      await log.observe(wire); f.source.retryPending(); await Bun.sleep(0)
      expect(f.runs).toHaveLength(count)
    } finally { log.logs.stop(); reader.close() }
  }))
}
for (const kind of ['claude', 'codex'] as const) for (const role of ['coordinator', 'task'] as const) {
  test(`launch delivery reconciles lost reply after reopening (${kind}, ${role})`, async () => {
    const home = mkdtempSync(join(tmpdir(), 'shep-delivery-reopen-'))
    let f = setup(home)
    try {
      const { chat } = await deliveryStart(f, kind, role, true), count = f.runs.length
      const call = f.source.core.call.bind(f.source.core)
      f.source.core.call = async <T>(method: string, params: Record<string, unknown> = {}, timeout?: number) => {
        const result = await call<T>(method, params, timeout)
        if (method === 'terminal.run') throw Error('Lost reply after native submission')
        return result
      }
      await sendDelivery(f, chat)
      expect(f.runs).toHaveLength(count + 1)
      const wire = (f.runs.at(-1)!.argv as string[]).at(-1)!, launch = f.source.agents.get(chat)!.launch
      expect(f.source.store.get<PendingSend>('pending-send', 'delivery-proof')).toMatchObject({ state: 'uncertain', submission: { launch } })
      f.close(); f = setup(home)
      const log = deliveryLog(f, chat), reader = new CoreStore(home)
      try {
        f.source.retryPending(); await Bun.sleep(0)
        await log.observe('Continue with the same choice')
        expect(reader.get<PendingSend>('pending-send', 'delivery-proof')?.state).toBe('uncertain')
        await log.observe(wire)
        expect(reader.get('pending-send', 'delivery-proof')).toBeUndefined()
        expect(reader.get(`message:${chat}`, 'delivery-proof')).toMatchObject({ waiting: false, source: expect.any(String) })
        expect(reader.get<CoreAgent>('agent', chat)?.launch).toBe(launch)
        expect(f.runs).toEqual([])
      } finally { log.logs.stop(); reader.close() }
    } finally { f.close(); rmSync(home, { recursive: true, force: true }) }
  })
}

for (const kind of ['claude', 'codex'] as const) test(`launch delivery is not resurrected by a late lost reply (${kind})`, () => fixture(async f => {
  f.source.settings.set('provider.route', 'Personal')
  const { chat } = await deliveryStart(f, kind, 'coordinator', true)
  const call = f.source.core.call.bind(f.source.core), observed = barrier()
  f.source.core.call = async <T>(method: string, params: Record<string, unknown> = {}, timeout?: number) => {
    const result = await call<T>(method, params, timeout)
    if (method === 'terminal.run') {
      const log = deliveryLog(f, chat)
      try { await log.observe((params.argv as string[]).at(-1)!) } finally { log.logs.stop() }
      observed.reached(); await observed.wait
      throw Error('Reply lost after the native log acknowledged')
    }
    return result
  }
  const sending = f.source.act({ type: 'send', chat, text: 'Continue with the same choice', cid: 'delivery-proof' })
  await observed.ready
  const reader = new CoreStore(f.source.config.home)
  try {
    expect(reader.get('pending-send', 'delivery-proof')).toBeUndefined()
    observed.release(); await sending
    for (let n = 0; n < 200 && f.source.updateBusy(); n++) await Bun.sleep(5)
    expect(f.source.updateBusy()).toBe(false)
    expect(reader.get('pending-send', 'delivery-proof')).toBeUndefined()
    expect(reader.get(`message:${chat}`, 'delivery-proof')).toMatchObject({ waiting: false, source: expect.any(String) })
    expect(f.source.agents.get(chat)?.provider?.route).toBe('personal')
    expect(f.runs).toHaveLength(2)
  } finally { observed.release(); reader.close() }
}))

for (const reason of ['queued', 'cancelled', 'replacement-launch', 'legacy-without-receipt'] as const) {
  test(`launch delivery does not acknowledge ${reason}`, () => fixture(async f => {
    const { chat } = await deliveryStart(f, 'claude', 'coordinator', true)
    await sendDelivery(f, chat)
    const wire = (f.runs.at(-1)!.argv as string[]).at(-1)!
    const pending = f.source.store.get<PendingSend>('pending-send', 'delivery-proof')!
    if (reason === 'queued' || reason === 'cancelled') pending.state = reason
    if (reason === 'legacy-without-receipt') { pending.state = 'uncertain'; delete pending.submission }
    if (reason === 'replacement-launch') f.source.agents.update(f.source.agents.get(chat)!, { launch: 'replacement' })
    f.source.store.set('pending-send', pending.id, pending)
    const log = deliveryLog(f, chat), reader = new CoreStore(f.source.config.home)
    try {
      await log.observe(wire)
      await log.observe('Continue with the same choice')
      expect(reader.get('pending-send', pending.id)).toEqual(pending)
      expect(reader.get<{ source?: string }>(`message:${chat}`, pending.id)?.source).toBeUndefined()
    } finally { log.logs.stop(); reader.close() }
  }))
}
