import { createHash, randomUUID } from 'node:crypto'
import { join } from 'node:path'
import { CoreNotSubmitted, Refusal } from '../client.ts'
import type { CoreFiles } from '../files.ts'
import type { RepoLocation } from '../git.ts'
import type { CoreStore } from '../store.ts'
import { bitbucketCredential, parseBitbucketRequest } from './bitbucket-protocol.ts'
import type { BitbucketContext, BitbucketOperation, BitbucketReply } from './bitbucket-protocol.ts'
import type { ForgePublication, ForgePullRequest, ForgePrRecord, ForgeRepository, RepositoryForge } from './types.ts'
import { samePr } from './identity.ts'

export interface BitbucketExecution {
  files: CoreFiles
  store: CoreStore
  contained: (repo: RepoLocation) => boolean
  runtime: (machine: string) => Promise<{ bun: string; root: string }>
  /** Synchronous core epoch/machine binding. Disconnected or unknown machines refuse. */
  binding: (machine: string) => string
  ownership: (machine: string) => string
}
interface Admission { binding: string; ownership: string; on?: string; validate?: (afterDispatch?: boolean) => void; dispatched?: boolean }
interface PublicationRecord {
  id: string; task: string; machine: string; repository: ForgeRepository; branch: string; base: string; head: string
  folder: string; origins: BitbucketContext['origins']; credential: BitbucketContext['credential']; saved?: ForgePrRecord; state: 'uncertain' | 'confirmed'; pr?: ForgePrRecord
  binding?: string; ownership?: string; on?: string
}
// Native older records captured [core id, epoch, machine]. Translate only
// that known representation; malformed or foreign legacy bindings stay held.
function legacyOwnership(binding: string) {
  try {
    const value = JSON.parse(binding)
    if (Array.isArray(value) && value.length === 3 && typeof value[0] === 'string' && Number.isSafeInteger(value[1])) {
      const remote = value[2]
      if (remote === null) return JSON.stringify([value[0], null])
      if (remote && typeof remote.id === 'string' && typeof remote.name === 'string') return JSON.stringify([value[0], { id: remote.id, name: remote.name, host: remote.host, session: remote.session }])
    }
  } catch {}
  return binding
}
const messages = {
  'invalid-request': 'Bitbucket refused an unsupported operation or credential context',
  'missing-credentials': 'Configure a noninteractive REST-capable token in this execution host’s Git credential helper',
  'permission-refused': 'The execution host’s credential lacks REST compatibility or permission for this Bitbucket operation',
  'rate-limited': 'Bitbucket rate limited this read; retry later',
  'malformed-response': 'Bitbucket returned an invalid bounded response',
  'incomplete-read': 'Bitbucket could not complete this bounded read',
  'uncertain-write': 'Bitbucket publication is uncertain; reconcile the original operation without another create',
  'identity-changed': 'The Bitbucket repository, candidate or destination changed; validate a fresh snapshot',
  unavailable: 'Bitbucket is unavailable on this execution host',
}

/** Provider interpretation and durable publication ownership behind the common task seam. */
export class BitbucketForge implements RepositoryForge {
  readonly name = 'Bitbucket'
  private readonly context: BitbucketContext
  private active?: Admission
  private input?: ForgePublication
  constructor(private readonly repo: RepoLocation, readonly identity: ForgeRepository, private readonly host: BitbucketExecution,
    origins: BitbucketContext['origins'], private readonly publishingKeys: Set<string>) {
    this.context = { repository: identity.repository, folder: repo.folder, origins, credential: bitbucketCredential(origins, identity.repository) }
    this.regular()
  }
  private regular(afterDispatch = false) { if (this.host.contained(this.repo)) throw new Refusal(afterDispatch
    ? 'Contained Bitbucket ownership now blocks further actions. Check previously dispatched operations before continuing'
    : 'Contained Bitbucket repositories, including retained ownership, are unsupported; nothing was provisioned, pushed or sent', afterDispatch) }
  private validate(admission: Admission, on = admission.on, afterDispatch = false) {
    admission.dispatched ||= afterDispatch
    this.regular(admission.dispatched); admission.validate?.(admission.dispatched)
    if (on !== admission.on || this.host.binding(this.repo.machine) !== admission.binding) throw new Refusal(admission.dispatched
      ? 'The task execution route changed after an admitted operation was dispatched. Check the recorded push and original pull request outcome before continuing; no further Bitbucket action is permitted by this call'
      : 'The task execution route changed before Bitbucket dispatch; nothing was submitted by this call', !!admission.dispatched)
  }
  private async admission(validate?: (afterDispatch?: boolean) => void): Promise<Admission> {
    this.regular(); validate?.()
    const binding = this.host.binding(this.repo.machine), ownership = this.host.ownership(this.repo.machine), on = await this.host.files.route(this.repo.machine)
    const admission = { binding, ownership, on, validate }; this.validate(admission)
    return admission
  }
  private async request(operation: BitbucketOperation, beforeDispatch?: () => void, validate?: (afterDispatch?: boolean) => void) {
    const admission = this.active ?? await this.admission(validate)
    this.validate(admission); validate?.(admission.dispatched)
    const runtime = await this.host.runtime(this.repo.machine)
    this.validate(admission); validate?.(admission.dispatched)
    let output: Buffer
    try {
      output = await this.host.files.exec(this.repo.machine, [runtime.bun, '--no-env-file', join(runtime.root, 'helper/core-bitbucket.ts')], join(runtime.root, 'helper'),
        Buffer.from(JSON.stringify({ version: 1, context: this.context, operation })), 55,
        on => { this.validate(admission, on); validate?.(admission.dispatched); beforeDispatch?.() })
    } catch (error) {
      if (error instanceof Refusal || error instanceof CoreNotSubmitted) throw error
      // Only sanitized helper output may cross CoreFiles. Never forward arbitrary core stderr.
      const write = operation.kind === 'create' || operation.kind === 'prepare'
      throw new Refusal(write ? messages['uncertain-write'] : messages.unavailable, write)
    }
    this.validate(admission, admission.on, true); validate?.(true)
    let reply: BitbucketReply
    try { reply = JSON.parse(output.toString('utf8')) } catch { throw new Refusal(messages['malformed-response']) }
    if (!reply || typeof reply.ok !== 'boolean') throw new Refusal(messages['malformed-response'])
    if (!reply.ok) throw new Refusal(messages[reply.category] ?? messages['malformed-response'], reply.category === 'uncertain-write')
    if (!reply.result || typeof reply.result !== 'object') throw new Refusal(messages['malformed-response'])
    return reply.result
  }
  private checked(pr: ForgePullRequest | undefined, saved?: ForgePrRecord) {
    if (!pr || pr.identity.provider !== 'bitbucket' || pr.identity.host !== this.identity.host || pr.identity.repository !== this.identity.repository || saved && !samePr(saved, pr.identity)) throw new Refusal('The saved pull request identity differs from the observed Bitbucket repository')
    return pr
  }
  private async find(branch: string, base?: string, checks = false) {
    const result = await this.request({ kind: 'find', branch, base, checks })
    if (!Array.isArray(result.matches) || result.matches.length > 1) throw new Refusal('Bitbucket did not return an unambiguous task pull request')
    return result.matches[0] && this.checked(result.matches[0])
  }
  async read(ref: string, checks = true, saved?: ForgePrRecord) {
    const pr = saved || /^\d+$/.test(ref)
      ? this.checked((await this.request({ kind: 'read', number: saved?.number ?? Number(ref), checks })).pr, saved)
      : await this.find(ref, undefined, checks)
    if (!pr) throw new Refusal('No Bitbucket pull request yet')
    if (saved && !/^\d+$/.test(ref) && pr.source !== ref) throw new Refusal('The Bitbucket source branch differs from this task')
    return pr
  }
  private key(input: ForgePublication) { return createHash('sha256').update(JSON.stringify([this.identity, input.branch, input.base])).digest('hex') }
  private record(input: ForgePublication) {
    // Older records used a machine-specific key. They retain their original
    // authority and uncertainty; changing the exclusion key must not release them.
    const records = this.host.store.all<PublicationRecord>('forge-publication').filter(record =>
      record.repository.provider === this.identity.provider && record.repository.host === this.identity.host && record.repository.repository === this.identity.repository && record.branch === input.branch && record.base === input.base)
    if (records.length > 1) throw new Refusal(messages['uncertain-write'], true)
    return records[0]
  }
  private recordKey(input: ForgePublication, record: PublicationRecord) {
    const key = this.key(input)
    if (this.host.store.get<PublicationRecord>('forge-publication', key)?.id === record.id) return key
    const legacy = createHash('sha256').update(JSON.stringify([record.machine, record.repository, record.branch, record.base])).digest('hex')
    if (this.host.store.get<PublicationRecord>('forge-publication', legacy)?.id === record.id) return legacy
    throw new Refusal(messages['uncertain-write'], true)
  }
  private owns(record: PublicationRecord, input: ForgePublication, admission: Admission) {
    const sameOwner = record.task === input.owner!.task && record.machine === this.repo.machine && record.folder === this.repo.folder
    const owner = record.ownership ?? (record.binding === undefined ? undefined : legacyOwnership(record.binding))
    const sameRoute = (owner === undefined || owner === admission.ownership) && (record.on === undefined || record.on === admission.on)
    const sameContext = JSON.stringify(record.origins) === JSON.stringify(this.context.origins) && JSON.stringify(record.credential) === JSON.stringify(this.context.credential)
    return sameOwner && sameRoute && sameContext
  }
  private matches(pr: ForgePullRequest, input: ForgePublication) {
    this.checked(pr, input.saved)
    if (pr.head !== input.head || pr.source !== input.branch || pr.base !== input.base || pr.state !== 'OPEN') throw new Refusal('Bitbucket did not confirm this exact task candidate and destination')
  }
  private confirm(input: ForgePublication, pr: ForgePullRequest) {
    this.matches(pr, input)
    const record = this.record(input)
    if (record) this.host.store.set('forge-publication', this.recordKey(input, record), { ...record, state: 'confirmed', pr: pr.identity })
  }
  private creation(input: ForgePublication): BitbucketOperation {
    return { kind: 'create', branch: input.branch, base: input.base, head: input.head, title: input.title, body: input.body }
  }
  private preflight(input: ForgePublication) {
    try { parseBitbucketRequest({ version: 1, context: this.context, operation: this.creation(input) }) }
    catch { throw new Refusal('Bitbucket publication payload failed preflight; correct the task title, brief or source/destination identity within the supported bounds. Nothing was pushed or submitted by this call') }
  }
  async publishing<T>(input: ForgePublication, perform: (admit: (afterDispatch?: boolean) => void, destination: string) => Promise<T>) {
    if (!input.owner) throw new Refusal('Bitbucket publication requires task-owned admission')
    this.regular(); this.preflight(input)
    const key = this.key(input)
    if (this.publishingKeys.has(key)) throw new Refusal('Another task is publishing this Bitbucket source and destination; retry after it finishes')
    this.publishingKeys.add(key)
    try {
      this.active = await this.admission(input.owner.validate); this.input = input
      const record = this.record(input)
      if (record && !this.owns(record, input, this.active)) throw new Refusal('This publication belongs to another task, execution route or credential context; no new create is permitted')
      const result = await this.request({ kind: 'probe', branch: input.branch, base: input.base })
      if (record?.state === 'uncertain') {
        if (record.head !== input.head || !result.matches?.[0]) throw new Refusal(messages['uncertain-write'], true)
        this.confirm(input, this.checked(result.matches[0], record.saved))
      }
      if (record?.state === 'confirmed' && (!result.matches?.[0] || !samePr(record.pr!, result.matches[0].identity))) throw new Refusal('The originally published Bitbucket pull request is no longer open; nothing was created')
      return await perform(afterDispatch => this.validate(this.active!, this.active!.on, afterDispatch), this.context.origins.push)
    } finally { this.active = undefined; this.input = undefined; this.publishingKeys.delete(key) }
  }
  async publish(input: ForgePublication) {
    if (!this.active || this.input !== input || !input.owner) throw new Refusal('Preflight this Bitbucket publication before pushing')
    let pr: ForgePullRequest | undefined = await this.find(input.branch, input.base)
    if (pr) { this.confirm(input, pr); return pr }
    if (input.saved || this.record(input)) throw new Refusal(messages['uncertain-write'], true)
    const record: PublicationRecord = { id: randomUUID(), task: input.owner.task, machine: this.repo.machine, binding: this.active.binding, ownership: this.active.ownership, on: this.active.on, repository: this.identity, branch: input.branch, base: input.base, head: input.head, folder: this.repo.folder, origins: this.context.origins, credential: this.context.credential, saved: input.saved, state: 'uncertain' }
    let dispatched = false
    try {
      const result = await this.request(this.creation(input), () => {
        this.host.store.db.transaction(() => {
          if (this.record(input)) throw new Refusal(messages['uncertain-write'], true)
          this.host.store.set('forge-publication', this.key(input), record); dispatched = true
        })()
      })
      pr = this.checked(result.pr)
    } catch (error) {
      if (error instanceof CoreNotSubmitted && dispatched) {
        this.host.store.db.transaction(() => { if (this.record(input)?.id === record.id) this.host.store.delete('forge-publication', this.key(input)) })()
        throw error
      }
      if (!dispatched) throw error
      // Positive evidence only; an empty lookup never releases the original sender.
      pr = await this.find(input.branch, input.base).catch(() => undefined)
      if (!pr) throw new Refusal(`${messages['uncertain-write']}${error instanceof Refusal ? `. ${error.message}` : ''}`, true)
    }
    this.confirm(input, pr)
    return pr
  }
  async prepare(pr: ForgePullRequest, body: string, validate?: (afterDispatch?: boolean) => void) {
    const current = await this.read(String(pr.identity.number), false, pr.identity)
    this.matches(current, { branch: pr.source, base: pr.base, head: pr.head, title: '', body, saved: pr.identity })
    const result = await this.request({ kind: 'prepare', number: pr.identity.number, head: pr.head, branch: pr.source, base: pr.base, body }, undefined, validate)
    this.matches(this.checked(result.pr, pr.identity), { branch: pr.source, base: pr.base, head: pr.head, title: '', body })
  }
  async integrate(): Promise<never> { throw new Refusal('Native Bitbucket merge lacks an expected-source-head guarantee and cannot enforce the approved source head; no merge request was sent') }
  async comments(): Promise<never> { throw new Refusal('Bitbucket feedback is outside this publication/checks increment') }
  async observeBase(): Promise<never> { throw new Refusal('Bitbucket base health is outside this publication/checks increment') }
  async presentation(branch: string, saved?: ForgePrRecord) {
    let pr: ForgePullRequest
    try { pr = await this.read(branch, true, saved) } catch (error) { if (error instanceof Refusal && error.message === 'No Bitbucket pull request yet') return { pr: null, why: 'No pull request yet.' }; throw error }
    const incomplete = !pr.checks?.complete
    return { pr: { number: pr.identity.number, title: pr.title, url: pr.identity.url, state: pr.state === 'MERGED' ? 'merged' as const : pr.state === 'CLOSED' ? 'closed' as const : pr.draft ? 'draft' as const : 'open' as const, checks: pr.checks?.items ?? [], ...(incomplete ? { checksError: 'Bitbucket checks are unavailable or incomplete.' } : {}) } }
  }
}
