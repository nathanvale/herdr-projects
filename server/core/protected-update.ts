import { CoreClient } from './client.ts'
import { inspectHome } from './home.ts'
import type { CoreTerminal } from './protocol.ts'
import type { CoreSource } from './source.ts'

function refusal(reason: string): never { throw Error(`Protected update refused: ${reason}. No shutdown was requested; resolve this work before retrying.`) }

/** Conservative application-owned admission, not a lease over arbitrary core clients. */
export class ProtectedUpdate {
  constructor(private readonly source: CoreSource) {}
  private stored() {
    if (this.source.updateBusy()) refusal('an application action or delivery is still in progress')
    const store = this.source.store
    if (store.all<{ settled?: boolean }>('permission').some(row => !row.settled)) refusal('permission requests are still pending')
    if (store.all<{ state: string }>('pending-send').some(row => row.state !== 'cancelled')) refusal('message delivery is pending or unconfirmed')
    if (this.source.agents.all().some(agent => agent.state === 'starting') || store.all('resume-start').length) refusal('a native start or resume still needs reconciliation')
    if (store.all<{ state: string }>('launch-attempt').some(row => !['confirmed', 'cancelled'].includes(row.state))) refusal('a launch is still unconfirmed')
    if (store.db.query('SELECT id FROM commands WHERE result IS NULL AND error IS NULL LIMIT 1').get()) refusal('a command is still in progress')
    if (this.source.tasks.all().some(row => !['merged', 'closed'].includes(row.workflow))) refusal('unfinished tasks can schedule more work')
    if (this.source.automations.model.list.length || store.all<{ state: string }>('automation-run').some(row => row.state !== 'done')) refusal('automations are retained')
    if (store.all<{ state: string }>('pilot-run').some(row => row.state !== 'stopped')) refusal('an Autopilot run is retained')
    if (this.source.spaces().some(row => row.mode === 'autopilot')) refusal('an Autopilot space can wake')
  }
  private workers(terminals: CoreTerminal[], recorded = true) {
    if (!Array.isArray(terminals) || terminals.some(row => !row || typeof row.address !== 'string' || typeof row.state !== 'string')) refusal('core returned an invalid inventory')
    if (terminals.some(row => row.state !== 'finished')) refusal('core has live or unconfirmed terminals')
    const installation = inspectHome(this.source.config.home)
    if (typeof installation !== 'object') refusal('installation identity is unconfirmed')
    if (!recorded) return
    for (const agent of this.source.agents.all()) {
      const terminal = terminals.find(row => row.labels?.['shepherdr.installation'] === installation.id && row.labels?.['shepherdr.launch'] === agent.launch)
      if (!terminal || agent.pid !== undefined && terminal.pid !== agent.pid) refusal('a recorded worker has no confirmed matching exit')
    }
  }
  async beforeStart() {
    // No CoreSource.start, subscriptions, permission cleanup or delivery before admission.
    this.stored()
    const client = await CoreClient.open(this.source.config.socket)
    try {
      const result = await client.call<{ terminals: CoreTerminal[] }>('terminal.list', { all: true })
      this.stored(); this.workers(result.terminals)
    } finally { client.close() }
  }
  async prepareStop(signal: AbortSignal, expires: number, commit: () => void) {
    const checkRequest = () => {
      signal.throwIfAborted()
      if (performance.now() >= expires) refusal('operator request expired before admission')
    }
    checkRequest()
    if (this.source.quiescing) refusal('the application is already stopping')
    if (!this.source.connected()) refusal('core is disconnected')
    this.stored(); this.workers([...this.source.core.current.terminals.values()], false)
    // New application starts/sends refuse; existing queued work already refused above.
    const hold = this.source.holdForUpdate()
    const epoch = this.source.core.current.epoch
    let abort!: () => void, committed = false
    const interrupted = new Promise<never>((_, reject) => {
      abort = () => reject(signal.reason)
      signal.addEventListener('abort', abort, { once: true })
      if (signal.aborted) abort()
    })
    try {
      const result = await Promise.race([
        this.source.core.call<{ terminals: CoreTerminal[] }>('terminal.list', { all: true }, Math.min(3000, Math.max(1, expires - performance.now()))),
        interrupted,
      ])
      checkRequest()
      if (!hold.current()) refusal('another shutdown owns admission')
      if (!this.source.connected() || this.source.core.current.epoch !== epoch) refusal('core connection changed during admission')
      this.stored(); this.workers(result.terminals)
      checkRequest()
      // No await between final validation and this operator's synchronous shutdown.
      committed = true
      commit()
    } finally {
      signal.removeEventListener('abort', abort)
      if (!committed) hold.release()
    }
  }
}
