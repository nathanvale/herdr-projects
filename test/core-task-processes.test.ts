import { expect, test } from 'bun:test'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CoreSource } from '../server/core/source.ts'
import { prepareHome } from '../server/core/home.ts'
import { CoreTaskProcesses } from '../server/core/task-processes.ts'
import type { CoreTask } from '../server/core/tasks.ts'
import type { CoreAgent } from '../server/core/model.ts'
import type { LaunchAttempt } from '../server/core/launches.ts'
import type { LaunchRecovery } from '../server/core/launch-recovery.ts'
import type { CoreTerminal } from '../server/core/protocol.ts'

function fixture() {
  const home = mkdtempSync(join(tmpdir(), 'shep-task-stop-')), source = new CoreSource({ home, socket: '/unused', binary: 'hc', session: 'test', port: 0 })
  const installation = prepareHome(home).id, machine = source.localMachineId(), chat = 'EX-1/Agent'
  const grant = source.mailbox.issue(chat, 'worker', machine, ['cli', 'secret'])
  const task = { id: 'EX-1', chat, machine } as CoreTask
  const terminal = (address: string, pid: number, parent?: string, labels: Record<string, string> = {}) => ({ address, pid, parent, labels, created_ms: pid, state: 'live' }) as CoreTerminal
  source.store.set('agent', chat, { chat, launch: 'worker', grant: grant.id, machine, space: 'space', kind: 'claude', role: 'task', state: 'working', terminal: 't1', pid: 11, hook: '/unused', started: 1 })
  source.core.current.connected = true
  ;(source.core.current.terminals as Map<string, CoreTerminal>).set('t1', terminal('t1', 11, undefined, { 'shepherdr.installation': installation, 'shepherdr.launch': 'worker', 'shepherdr.task': task.id }))
  ;(source.core.current.terminals as Map<string, CoreTerminal>).set('t2', terminal('t2', 22, 't1'))
  ;(source.core.current.terminals as Map<string, CoreTerminal>).set('t3', terminal('t3', 33, 't2'))
  ;(source.core.current.terminals as Map<string, CoreTerminal>).set('t9', terminal('t9', 99, undefined, { 'shepherdr.installation': installation, 'shepherdr.task': task.id }))
  return { source, task, grant, terminal, close() { source.stop(); source.mailbox.close(); source.store.close(); rmSync(home, { recursive: true, force: true }) } }
}

test('task stop awaits roots and outliving core descendants while preserving unrelated agents', async () => {
  const f = fixture(), killed: string[] = []
  try {
    f.source.core.call = async (_method, args) => { const address = String(args?.terminal); killed.push(address); setTimeout(() => { f.source.core.current.terminals.get(address)!.state = 'finished' }, 10); return {} as never }
    let closed = false
    f.source.browsers.close = async () => { expect(['t1', 't2', 't3'].every(id => f.source.core.current.terminals.get(id)?.state === 'finished')).toBe(true); closed = true }
    await new CoreTaskProcesses(f.source).stop(f.task)
    expect(new Set(killed)).toEqual(new Set(['t1', 't2', 't3']))
    expect(f.source.core.current.terminals.get('t9')?.state).toBe('live')
    expect(closed).toBe(true)
    expect(f.source.mailbox.permits(f.grant.id, { chat: f.grant.chat, session: f.grant.session, machine: f.grant.machine }, 'secret')).toBe(false)
  } finally { f.close() }
})

test('disconnect and PID replacement refuse completed cleanup instead of authorizing deletion', async () => {
  const f = fixture()
  try {
    f.source.core.current.connected = false
    await expect(new CoreTaskProcesses(f.source).stop(f.task)).rejects.toThrow('unconfirmed')
    f.source.core.current.connected = true
    f.source.core.call = async (_method, args) => { f.source.core.current.terminals.get(String(args?.terminal))!.state = 'finished'; f.source.core.current.terminals.get('t2')!.pid = 222; return {} as never }
    await expect(new CoreTaskProcesses(f.source).stop(f.task)).rejects.toThrow('identity or exit')
    expect(f.source.core.current.terminals.get('t9')?.state).toBe('live')
  } finally { f.close() }
})


test('stop cancels capacity-held sends even when the task has never had an agent', async () => {
  const f = fixture()
  try {
    f.source.store.delete('agent', f.task.chat)
    f.task.place = 'space'; f.task.workflow = 'queued'
    f.source.store.set('task', f.task.id, f.task)
    const grant = f.source.mailbox.issue('space', 'coord', f.task.machine, ['cli'])
    f.source.store.set('agent', 'space', { chat: 'space', space: 'space', machine: f.task.machine, role: 'coordinator', kind: 'claude', launch: grant.session, grant: grant.id, hook: '/unused', started: 1, state: 'idle' })
    f.source.store.set('pending-send', 'held-go', { id: 'held-go', chat: f.task.chat, text: 'Go', state: 'queued', quiet: true })
    f.source.browsers.close = async () => {}
    await f.source.tasks.stop(grant, f.task.id)
    expect(f.source.store.get<{ state: string }>('pending-send', 'held-go')?.state).toBe('cancelled')
    expect(f.source.tasks.get(f.task.id)?.workflow).toBe('todo')
    let retries = 0; f.source.retry = () => { retries++ }
    f.source.retryPending()
    expect(retries).toBe(0)
  } finally { f.close() }
})

test('stop follows children of a retired ordinary root after the chat has restarted', async () => {
  const f = fixture(), killed: string[] = []
  try {
    const old = f.source.agents.get(f.task.chat)!
    f.source.store.set('agent-launch', old.launch, old)
    f.source.core.current.terminals.get('t1')!.state = 'finished'
    const grant = f.source.mailbox.issue(f.task.chat, 'replacement', f.task.machine, ['cli'])
    f.source.store.set('agent', old.chat, { ...old, launch: 'replacement', grant: grant.id, terminal: 't4', pid: 44 })
    ;(f.source.core.current.terminals as Map<string, CoreTerminal>).set('t4', f.terminal('t4', 44, undefined, { 'shepherdr.installation': prepareHome(f.source.config.home).id, 'shepherdr.launch': 'replacement' }))
    f.source.core.call = async (_method, args) => { const id = String(args?.terminal); killed.push(id); f.source.core.current.terminals.get(id)!.state = 'finished'; return {} as never }
    f.source.browsers.close = async () => {}
    await new CoreTaskProcesses(f.source).stop(f.task)
    expect(new Set(killed)).toEqual(new Set(['t4', 't2', 't3']))
    expect(f.source.core.current.terminals.get('t9')?.state).toBe('live')
  } finally { f.close() }
})


function recoveredHistoricalRoot(f: ReturnType<typeof fixture>) {
  const old = f.source.agents.get(f.task.chat)!
  f.source.store.set('agent-launch', old.launch, old)
  const attempt: LaunchAttempt = { launch: old.launch, chat: old.chat, at: 1, state: 'execution-ended-after-host-reboot' }
  const recovery: LaunchRecovery = { launch: old.launch, chat: old.chat, machine: old.machine, phase: 'resumed', installation: prepareHome(f.source.config.home).id,
    host: 'a'.repeat(64), boot: '11111111-1111-4111-8111-111111111111', settledBoot: '22222222-2222-4222-8222-222222222222', identity: 'retained-binding', at: 1, settledAt: 2, resumedAt: 3 }
  f.source.store.set('launch-attempt', old.launch, attempt); f.source.store.set('launch-recovery', old.launch, recovery)
  for (const address of ['t1', 't2', 't3']) (f.source.core.current.terminals as Map<string, CoreTerminal>).delete(address)
  const grant = f.source.mailbox.issue(f.task.chat, 'replacement', f.task.machine, ['cli'])
  const replacement: CoreAgent = { ...old, launch: 'replacement', grant: grant.id, terminal: 't4', pid: 44 }
  f.source.store.set('agent', old.chat, replacement)
  ;(f.source.core.current.terminals as Map<string, CoreTerminal>).set('t4', f.terminal('t4', 44, undefined, { 'shepherdr.installation': recovery.installation, 'shepherdr.launch': replacement.launch }))
  return { old, attempt, recovery }
}

test('boot recovery cleanup recognizes exact historical proof without treating the current worker as a child', async () => {
  const f = fixture(), killed: string[] = []
  try {
    recoveredHistoricalRoot(f)
    const processes = new CoreTaskProcesses(f.source)
    expect(processes.runningChildren(f.task)).toBe(false)
    f.source.core.call = async (_method, args) => { const address = String(args?.terminal); killed.push(address); f.source.core.current.terminals.get(address)!.state = 'finished'; return {} as never }
    f.source.browsers.close = async () => {}
    await processes.stop(f.task)
    expect(killed).toEqual(['t4']); expect(f.source.core.current.terminals.get('t4')?.state).toBe('finished')
    expect(f.source.core.current.terminals.get('t9')?.state).toBe('live')
  } finally { f.close() }
})

for (const mismatch of ['attempt-launch', 'attempt-chat', 'attempt-state', 'recovery-launch', 'recovery-chat', 'recovery-machine', 'recovery-phase', 'missing-recovery', 'disconnected'] as const) test(`boot recovery cleanup refuses historical ${mismatch} proof`, async () => {
  const f = fixture(), killed: string[] = []
  try {
    const { old, attempt, recovery } = recoveredHistoricalRoot(f)
    if (mismatch === 'attempt-launch') f.source.store.set('launch-attempt', old.launch, { ...attempt, launch: 'other-launch' })
    if (mismatch === 'attempt-chat') f.source.store.set('launch-attempt', old.launch, { ...attempt, chat: 'other-chat' })
    if (mismatch === 'attempt-state') f.source.store.set('launch-attempt', old.launch, { ...attempt, state: 'submission-uncertain' })
    if (mismatch === 'recovery-launch') f.source.store.set('launch-recovery', old.launch, { ...recovery, launch: 'other-launch' })
    if (mismatch === 'recovery-chat') f.source.store.set('launch-recovery', old.launch, { ...recovery, chat: 'other-chat' })
    if (mismatch === 'recovery-machine') f.source.store.set('launch-recovery', old.launch, { ...recovery, machine: 'other-machine' })
    if (mismatch === 'recovery-phase') f.source.store.set('launch-recovery', old.launch, { ...recovery, phase: 'settled' })
    if (mismatch === 'missing-recovery') f.source.store.delete('launch-recovery', old.launch)
    if (mismatch === 'disconnected') f.source.core.current.connected = false
    const processes = new CoreTaskProcesses(f.source)
    expect(processes.runningChildren(f.task)).toBe(true)
    f.source.core.call = async (_method, args) => { killed.push(String(args?.terminal)); return {} as never }
    await expect(processes.stop(f.task)).rejects.toThrow('unconfirmed')
    expect(killed).toEqual([]); expect(f.source.core.current.terminals.get('t4')?.state).toBe('live')
  } finally { f.close() }
})

test('boot recovery cleanup still follows a live historical root and its children despite journal proof', async () => {
  const f = fixture(), killed: string[] = []
  try {
    const { old, recovery } = recoveredHistoricalRoot(f)
    ;(f.source.core.current.terminals as Map<string, CoreTerminal>).set('t1', f.terminal('t1', 11, undefined, { 'shepherdr.installation': recovery.installation, 'shepherdr.launch': old.launch }))
    ;(f.source.core.current.terminals as Map<string, CoreTerminal>).set('t2', f.terminal('t2', 22, 't1'))
    const processes = new CoreTaskProcesses(f.source)
    expect(processes.runningChildren(f.task)).toBe(true)
    f.source.core.call = async (_method, args) => { const address = String(args?.terminal); killed.push(address); f.source.core.current.terminals.get(address)!.state = 'finished'; return {} as never }
    f.source.browsers.close = async () => {}
    await processes.stop(f.task)
    expect(new Set(killed)).toEqual(new Set(['t1', 't2', 't4']))
    expect(f.source.core.current.terminals.get('t9')?.state).toBe('live')
  } finally { f.close() }
})
