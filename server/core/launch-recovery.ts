import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { createHash } from 'node:crypto'
import { inspectHome } from './home.ts'
import type { LaunchAttempt } from './launches.ts'
import type { CoreSource } from './source.ts'

export interface HostBoot { host: string; boot: string }
export type HostBootReader = () => HostBoot | Promise<HostBoot>
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i
const digest = (value: string) => createHash('sha256').update(value).digest('hex')
const execute = promisify(execFile)

/** Evidence belongs to the execution host, never to arguments, environment or application run.json. */
export async function readHostBoot(): Promise<HostBoot> {
  if (process.platform !== 'darwin') throw Error('Host-reboot recovery requires macOS kernel boot and platform identity; this OS is unsupported')
  const read = async (bin: string, args: string[]) => (await execute(bin, args, { encoding: 'utf8', timeout: 1000, maxBuffer: 64 * 1024 })).stdout.trim()
  try {
    const boot = (await read('/usr/sbin/sysctl', ['-n', 'kern.bootsessionuuid'])).toLowerCase()
    const platform = (await read('/usr/sbin/ioreg', ['-rd1', '-c', 'IOPlatformExpertDevice'])).match(/"IOPlatformUUID"\s*=\s*"([a-f0-9-]+)"/i)?.[1]?.toLowerCase()
    if (!platform || !uuid.test(platform) || !uuid.test(boot)) throw Error('Invalid host identity')
    return { host: digest(platform), boot }
  } catch { throw Error('Could not verify this execution host and its kernel boot; recovery refused') }
}

export interface LaunchRecovery {
  chat: string; launch: string; installation: string; machine: string; host: string; boot: string; identity: string
  phase: 'armed' | 'settled' | 'resumed'; at: number; settledBoot?: string; settledAt?: number; resumedAt?: number
}

/** Human operator only. A reboot proves execution ended, never that its past effects did not happen. */
export class CoreLaunchRecovery {
  constructor(private readonly source: CoreSource, private readonly observe: HostBootReader = readHostBoot) {}
  held(chat: string) { return !!this.source.store.get('launch-recovery-hold', chat) }
  private identity(chat: string) {
    const agent = this.source.agents.get(chat), task = this.source.tasks.forChat(chat)
    if (!agent) throw Error('No retained agent for this exact conversation')
    return digest(JSON.stringify([agent.chat, agent.launch, agent.grant, agent.machine, agent.space, agent.role, agent.kind,
      agent.session, agent.model, agent.effort, agent.speed, agent.provider, agent.hook, agent.command,
      task && [task.id, task.folder, task.repo, task.branch, task.machine, task.kind, task.model, task.effort, task.speed, task.deployment]]))
  }
  private bound(chat: string, launch: string, boot: HostBoot) {
    const installation = inspectHome(this.source.config.home), agent = this.source.agents.get(chat), space = agent && this.source.space(agent.space)
    if (typeof installation !== 'object' || !agent || agent.launch !== launch || agent.machine !== this.source.localMachineId() || !space || space.machine !== agent.machine) throw Error('Recovery installation, local host or conversation identity changed')
    if (agent.pilot || space.mode !== 'regular' || !['coordinator', 'task'].includes(agent.role) || !agent.session) throw Error('Recovery requires a regular local conversation with its retained native session')
    const row = this.source.store.get<LaunchRecovery>('launch-recovery', launch)
    if (row && (row.chat !== chat || row.installation !== installation.id || row.machine !== agent.machine || row.host !== boot.host || row.identity !== this.identity(chat))) throw Error('Recovery host or native conversation binding changed')
    return { installation, agent, row }
  }
  /** After bounded observation, final validation and durable commit have no intervening await. */
  async operator(args: string[], signal: AbortSignal, expires: number) {
    const [verb, operation, chat, launch, disposition] = args
    if (verb !== 'recover-launch' || !['status', 'arm', 'settle', 'resume'].includes(operation ?? '') || !chat || !launch || !uuid.test(launch) ||
      args.length !== (operation === 'resume' ? 5 : 4) || operation === 'resume' && disposition !== '--cancel-queued') throw Error('Use recover-launch status|arm|settle CHAT LAUNCH, or recover-launch resume CHAT LAUNCH --cancel-queued')
    const currentRequest = () => {
      if (signal.aborted || performance.now() >= expires || this.source.quiescing) throw Error('Recovery operator request expired or application is stopping')
    }
    currentRequest()
    const boot = await this.observe()
    if (!uuid.test(boot.boot) || !/^[a-f0-9]{64}$/.test(boot.host)) throw Error('Unsupported or invalid execution host boot evidence')
    const valid = () => { currentRequest(); const bound = this.bound(chat, launch, boot); currentRequest(); return bound }
    const initial = valid()
    if (operation === 'status') return `${launch}: ${initial.row?.phase ?? 'not-armed'}\n`
    if (this.source.updateBusy() || this.source.agents.starting(chat) || this.source.pilots.lifecycle.busy(initial.agent.space) || this.source.tasks.forChat(chat) && this.source.tasks.busy(this.source.tasks.forChat(chat)!.id)) throw Error('An application sender or action is still in progress; wait before recovery')
    return this.source.store.db.transaction(() => {
      const { installation, agent, row } = valid(), store = this.source.store
      const attempt = store.get<LaunchAttempt>('launch-attempt', launch)
      if (!attempt || attempt.chat !== chat || store.get('launch-claim', chat) !== launch && row?.phase !== 'resumed') throw Error('Exact launch claim changed; recovery refused')
      if (operation === 'arm') {
        if (row) return `${launch}: ${row.phase}\n`
        if (attempt.state !== 'submission-uncertain' || this.source.agents.terminal(agent)) throw Error('Only an exact uncertain submission without a reconciled terminal can be armed')
        const recovery: LaunchRecovery = { chat, launch, installation: installation.id, machine: agent.machine, host: boot.host, boot: boot.boot, identity: this.identity(chat), phase: 'armed', at: Date.now() }
        currentRequest()
        store.set('launch-recovery', launch, recovery); store.set('launch-recovery-hold', chat, launch)
        return `${launch}: armed. A whole-host reboot needs separate operator authorization.\n`
      }
      if (!row) throw Error('Arm this exact launch before settling or resuming')
      if (operation === 'settle') {
        if (row.phase !== 'armed') return `${launch}: ${row.phase}\n`
        if (row.boot === boot.boot) throw Error('The execution host has not rebooted; no recovery state changed')
        if (!['submission-uncertain', 'confirmed'].includes(attempt.state) || this.source.agents.terminal(agent)?.state === 'live') throw Error('Launch outcome changed; reconcile its actual terminal instead')
        // Grants have their own SQLite store. Revoke first: a crash can leave an armed hold,
        // never a settled journal with a live grant. Exact retry safely repeats revocation.
        currentRequest()
        this.source.mailbox.revoke(chat, launch)
        store.set('launch-attempt', launch, { ...attempt, state: 'execution-ended-after-host-reboot' })
        store.set('agent', chat, { ...agent, state: 'idle' }); store.set('agent-launch', launch, { ...agent, state: 'idle' })
        store.delete('resume-start', launch)
        store.set('launch-recovery', launch, { ...row, phase: 'settled', settledBoot: boot.boot, settledAt: Date.now() })
        return `${launch}: settled; past effects and submitted messages remain unknown. Dispatch is held.\n`
      }
      if (row.phase === 'resumed') return `${launch}: resumed\n`
      if (row.phase !== 'settled' || attempt.state !== 'execution-ended-after-host-reboot' || row.boot === boot.boot) throw Error('Settle this exact launch after a host reboot before resuming')
      // Explicit disposition covers all queued work now, but never the uncertain submission.
      currentRequest()
      this.source.cancelQueued(chat)
      store.delete('launch-claim', chat); store.delete('launch-recovery-hold', chat)
      store.set('launch-recovery', launch, { ...row, phase: 'resumed', resumedAt: Date.now() })
      this.source.post(chat, { id: `recovery-${launch}`, who: 'agent', text: 'Host reboot ended the old execution. Earlier submitted work remains unconfirmed. Queued messages were cancelled; send a fresh instruction or restart explicitly.', at: Date.now() })
      return `${launch}: resumed; no process started and no saved message replayed.\n`
    })()
  }
}
