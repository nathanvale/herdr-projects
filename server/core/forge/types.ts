import type { MergeEvidence, PrCheck, PullRequest, ForgePrRecord } from '../../../shared/types.ts'

export type ForgeProvider = 'github' | 'bitbucket'
export interface ForgeRepository { provider: ForgeProvider; host: string; repository: string }
export type { ForgePrRecord } from '../../../shared/types.ts'
export interface ForgeChecks {
  head: string
  complete: boolean
  items: PrCheck[]
  summary: MergeEvidence['checks']
  /** A cancelled run blocks integration but preserves GitHub's existing notification policy. */
  failures: { name: string; url?: string }[]
  green: boolean
}
export interface ForgePullRequest {
  identity: ForgePrRecord & ForgeRepository
  title: string
  state: 'OPEN' | 'CLOSED' | 'MERGED'
  draft: boolean
  head: string
  source: string
  base: string
  mergeCommit?: string
  checks?: ForgeChecks
}
export interface ForgeComment { id: string; at: number; who: string; body: string; url: string; state?: string; where?: string }
export interface ForgeBaseVerdict { state: 'fail' | 'pending' | 'pass'; failed: { name: string; url: string; run?: number }[] }
export interface ForgeBaseObservation {
  baseHead: string
  selected?: { head: string; verdict: ForgeBaseVerdict }
  context: { sinceGreen?: string; merged: { sha: string; title: string }[]; logTail?: string; unavailable?: boolean }
}
export interface ForgeIntegration { state: 'accepted' | 'pending' | 'uncertain' | 'merged'; location?: string }
export interface ForgePublication {
  branch: string; base: string; title: string; body: string; head: string; saved?: ForgePrRecord
  /** Internal task-owned admission. Never supplied by request text or a helper. */
  owner?: { task: string; validate: () => void }
}
/** Task-facing seam. Local Git, approvals, delivery and cleanup stay with their existing owners. */
export interface RepositoryForge {
  readonly identity: ForgeRepository
  readonly name: string
  read(ref: string, checks?: boolean, saved?: ForgePrRecord): Promise<ForgePullRequest>
  /** Holds shared publication ownership and preflights before the caller pushes. */
  publishing?<T>(input: ForgePublication, perform: (admit: () => void, destination: string) => Promise<T>): Promise<T>
  publish(input: ForgePublication): Promise<ForgePullRequest>
  prepare(pr: ForgePullRequest, body: string, admit?: () => void): Promise<void>
  integrate(pr: ForgePullRequest, head: string): Promise<ForgeIntegration>
  comments(saved: ForgePrRecord): Promise<ForgeComment[]>
  observeBase(branch: string, previous: { green?: string; red?: string }): Promise<ForgeBaseObservation>
  presentation(branch: string, saved?: ForgePrRecord): Promise<{ pr: PullRequest | null; why?: string }>
}
