import type { CoreAgent } from './model.ts'
import type { CoreStore } from './store.ts'

export interface LaunchAttempt {
  launch: string; chat: string; at: number
  state: 'never-submitted' | 'submission-uncertain' | 'confirmed' | 'cancelled'
  previous?: CoreAgent
}

/** Application dispatch authority, not process liveness. Every sender must claim
 * and transition through this journal; legacy records confer no recovery proof. */
export class CoreLaunches {
  constructor(private readonly store: CoreStore) {}
  get(launch: string) { return this.store.get<LaunchAttempt>('launch-attempt', launch) }
  claim(chat: string, launch: string, previous?: CoreAgent) {
    const active = this.store.get<string>('launch-claim', chat)
    if (active && ['never-submitted', 'submission-uncertain'].includes(this.get(active)?.state ?? 'submission-uncertain')) throw Error('A previous start still owns this conversation; reconcile or recover its exact launch before retrying')
    const attempt: LaunchAttempt = { launch, chat, previous, at: Date.now(), state: 'never-submitted' }
    this.store.set('launch-attempt', launch, attempt)
    this.store.set('launch-claim', chat, launch)
  }
  owned(chat: string, launch: string) {
    const attempt = this.get(launch)
    if (attempt?.chat !== chat || attempt.state !== 'never-submitted' || this.store.get<string>('launch-claim', chat) !== launch) throw Error('Launch authority changed or submission already began; recovery requires proven non-submission')
    return attempt
  }
  submitting(chat: string, launch: string) {
    const attempt = this.owned(chat, launch)
    this.store.set('launch-attempt', launch, { ...attempt, state: 'submission-uncertain' })
  }
  confirm(chat: string, launch: string) {
    const attempt = this.get(launch)
    if (attempt?.chat === chat && attempt.state === 'submission-uncertain') this.store.set('launch-attempt', launch, { ...attempt, state: 'confirmed' })
  }
  /** Caller holds the store transaction, fencing a sender's final transition.
   * Never infer non-submission from absence in a core snapshot. */
  cancel(chat: string, launch: string) {
    const attempt = this.owned(chat, launch)
    const current = this.store.get<CoreAgent>('agent', chat)
    if (current?.launch !== launch && current?.launch !== attempt.previous?.launch) throw Error('Conversation identity changed; recovery refused')
    this.store.set('launch-attempt', launch, { ...attempt, state: 'cancelled' })
    this.store.delete('launch-claim', chat)
    if (current?.launch === launch) {
      if (attempt.previous) this.store.set('agent', chat, attempt.previous)
      else this.store.delete('agent', chat)
    }
    this.store.delete('agent-launch', launch)
    this.store.delete('resume-start', launch)
  }
}
