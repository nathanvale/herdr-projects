import { Refusal } from '../client.ts'
import { failureLogTail } from './github-logs.ts'
import type { CoreGit, RepoLocation } from '../git.ts'
import type { MergeEvidence, PrCheck } from '../../../shared/types.ts'
import type { ForgeRepository, ForgePullRequest, ForgePrRecord, ForgeChecks, ForgeComment, ForgeBaseObservation, ForgeBaseVerdict, ForgePublication, RepositoryForge } from './types.ts'
import { samePr } from './identity.ts'

interface Raw { id: number; user?: { login?: string }; body?: string | null; html_url: string; created_at?: string; submitted_at?: string | null; state?: string; path?: string; line?: number | null; original_line?: number | null; pull_request_review_id?: number | null }
const FAILED = new Set(['FAILURE', 'ERROR', 'TIMED_OUT', 'ACTION_REQUIRED', 'STARTUP_FAILURE', 'STALE'])
const PASSED = new Set(['SUCCESS', 'NEUTRAL', 'SKIPPED'])
/** GitHub's checks in a few words for a merge card. Whatever hasn't passed or failed yet is running. */
export function checkWords(checks: { conclusion?: string; state?: string }[]): MergeEvidence['checks'] {
  if (!checks.length) return { state: 'none', text: 'None reported yet' }
  const states = checks.map(check => (check.conclusion || check.state || '').toUpperCase())
  const failed = states.filter(state => FAILED.has(state) || state === 'CANCELLED').length, passed = states.filter(state => PASSED.has(state)).length, running = checks.length - failed - passed
  return { state: failed ? 'failed' : running ? 'running' : 'passed', text: [failed && `${failed} failed`, running && `${running} running`, passed && `${passed} passed`].filter(Boolean).join(', ') }
}
export function prComments(pages: unknown[], kind: 'r' | 'c' | 'i', reviews: unknown[] = []): ForgeComment[] {
  const rows = pages.flat()
  if (rows.length > 10000) throw Error('Too many GitHub comments for one bounded snapshot')
  return rows.flatMap((item: unknown) => {
    const row = item as Raw
    if (!row || !Number.isSafeInteger(row.id) || typeof row.html_url !== 'string' || row.body != null && typeof row.body !== 'string' || row.state != null && typeof row.state !== 'string' || row.path != null && typeof row.path !== 'string') throw Error('Invalid GitHub comment response')
    const review = kind === 'c' && row.pull_request_review_id != null ? (reviews as Raw[]).find(review => review.id === row.pull_request_review_id) : undefined
    if (kind === 'c' && row.pull_request_review_id != null && (!review || review.state === 'PENDING' || !review.submitted_at)) return []
    if (row.state === 'PENDING' || review?.state === 'PENDING') return []
    const at = Date.parse(review?.submitted_at || row.submitted_at || row.created_at || '')
    if (!Number.isFinite(at)) throw Error('GitHub comment has no confirmed publication time')
    return [{ id: `${kind}${row.id}`, at, who: typeof row.user?.login === 'string' ? row.user.login.slice(0, 128) : 'someone', body: (row.body || '').trim(), url: row.html_url.slice(0, 2000),
      ...(row.state ? { state: row.state.slice(0, 64) } : {}), ...(row.path ? { where: `${row.path.slice(0, 512)}${row.line ?? row.original_line ? ':' + (row.line ?? row.original_line) : ''}` } : {}) }]
  })
}

interface WorkflowRun { headSha: string; status: string; conclusion: string | null; url: string; workflowName: string; databaseId?: number }
const GREEN = new Set(['success', 'neutral', 'skipped'])
const RED = new Set(['failure', 'timed_out', 'action_required', 'startup_failure', 'stale'])

/** A pending or unknown result cannot clear an existing red incident. */
export function mainVerdict(value: unknown, head: string): ForgeBaseVerdict {
  if (!Array.isArray(value) || value.length > 100) throw Error('Invalid GitHub workflow response')
  const rows = value.filter((run): run is WorkflowRun => {
    if (!run || typeof run !== 'object' || typeof run.headSha !== 'string' || typeof run.status !== 'string' || !(run.conclusion === null || typeof run.conclusion === 'string') || typeof run.url !== 'string' || typeof run.workflowName !== 'string') throw Error('Incomplete GitHub workflow result')
    return run.headSha === head
  })
  const failed = rows.filter(run => run.status === 'completed' && RED.has(run.conclusion ?? ''))
  return { state: failed.length ? 'fail' : value.length === 100 || !rows.length || rows.some(run => run.status !== 'completed' || !GREEN.has(run.conclusion ?? '')) ? 'pending' : 'pass', failed: failed.map(run => ({ name: run.workflowName, url: run.url, run: run.databaseId })) }
}

/** Recent branch history orders commits; pending heads must not hide older verdicts. */
export function mainCandidates(value: unknown, history: unknown) {
  mainVerdict(value, '') // Validate every row, including rows outside this branch's history.
  if (!Array.isArray(history) || !history.length || history.length > 100 || history.some(head => typeof head !== 'string' || !/^[a-f0-9]{40,64}$/.test(head)) || new Set(history).size !== history.length) throw Error('Invalid GitHub base history')
  return history.flatMap((head: string) => {
    const rows = (value as WorkflowRun[]).filter(run => run.headSha === head), verdict = mainVerdict(rows, head)
    return verdict.state === 'pending' ? [] : [{ head, verdict }]
  })
}


interface RawPullRequest {
  number: number; url: string; title?: string; state: 'OPEN' | 'CLOSED' | 'MERGED'; isDraft?: boolean
  headRefOid: string; headRefName: string; baseRefName: string; mergeCommit?: { oid: string } | null
  statusCheckRollup?: { conclusion?: string; status?: string; state?: string; name?: string; context?: string; targetUrl?: string; detailsUrl?: string }[]
}
const commit = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{40,64}$/.test(value)
function checksFor(rows: RawPullRequest['statusCheckRollup'], head: string): ForgeChecks {
  if (!Array.isArray(rows) || rows.some(row => !row || ['conclusion', 'status', 'state', 'name', 'context', 'targetUrl', 'detailsUrl'].some(key => (row as Record<string, unknown>)[key] != null && typeof (row as Record<string, unknown>)[key] !== 'string'))) throw Error('Incomplete GitHub checks')
  // gh may cap the GraphQL rollup. A full-sized bounded page cannot prove completeness.
  const complete = rows.length < 100
  const items: PrCheck[] = rows.map(row => {
    const state = (row.conclusion || row.state || '').toUpperCase(), pending = row.status && row.status !== 'COMPLETED'
    return { name: row.name || row.context || 'Check', state: pending ? 'pending' : PASSED.has(state) ? state === 'SKIPPED' ? 'skip' : 'pass' : FAILED.has(state) || state === 'CANCELLED' ? 'fail' : 'pending', url: row.detailsUrl || row.targetUrl || undefined }
  })
  const settled = items.every(item => item.state === 'pass' || item.state === 'skip')
  const summary = complete ? checkWords(rows.map((row, i) => items[i].state === 'pending' ? {} : row)) : { state: 'unknown' as const, text: 'GitHub checks may be incomplete' }
  return { head, complete, items, summary, failures: rows.filter(row => FAILED.has((row.conclusion || row.state || '').toUpperCase()) && (!row.status || row.status === 'COMPLETED')).map(row => ({ name: row.name || row.context || 'Check', url: row.detailsUrl || row.targetUrl || undefined })), green: complete && settled }
}

/** GitHub transport and interpretation. CoreGit retains the existing narrow checked git/gh broker. */
export class GitHubForge implements RepositoryForge {
  readonly name = 'GitHub'
  private readonly target: string
  constructor(private readonly git: CoreGit, private readonly repo: RepoLocation, readonly identity: ForgeRepository, private readonly hosts = [identity.host]) {
    this.target = `${identity.host}/${identity.repository}`
  }
  private json<T>(args: string[], timeout = 60) { return this.git.gh<T>(this.repo, args, timeout) }
  async read(ref: string, checks = true, saved?: ForgePrRecord): Promise<ForgePullRequest> {
    const raw = await this.json<RawPullRequest>(['pr', 'view', ref, '--repo', this.target, '--json', `number,url,title,state,isDraft,headRefOid,headRefName,baseRefName,mergeCommit${checks ? ',statusCheckRollup' : ''}`])
    if (!raw || !Number.isSafeInteger(raw.number) || raw.number < 1 || typeof raw.url !== 'string' || !['OPEN', 'CLOSED', 'MERGED'].includes(raw.state) || typeof raw.isDraft !== 'boolean' || !commit(raw.headRefOid) || typeof raw.headRefName !== 'string' || !raw.headRefName || typeof raw.baseRefName !== 'string' || !raw.baseRefName || raw.mergeCommit != null && !commit(raw.mergeCommit.oid)) throw Error('Incomplete GitHub pull request identity')
    const url = new URL(raw.url)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || !this.hosts.includes(url.hostname.toLowerCase()) || url.pathname.toLowerCase() !== `/${this.identity.repository}/pull/${raw.number}`.toLowerCase()) throw new Refusal('GitHub returned a pull request from another repository')
    const identity = { ...this.identity, host: url.hostname.toLowerCase(), number: raw.number, url: raw.url }
    if (saved && !samePr(saved, identity)) throw new Refusal('The saved pull request identity differs from the observed forge repository')
    return { identity, title: raw.title || '', state: raw.state, draft: raw.isDraft === true, head: raw.headRefOid, source: raw.headRefName, base: raw.baseRefName, mergeCommit: raw.mergeCommit?.oid,
      ...(checks ? { checks: checksFor(raw.statusCheckRollup, raw.headRefOid) } : {}) }
  }
  private async find(branch: string, base: string) {
    const rows = await this.json<{ number: number; headRefName: string; baseRefName: string }[]>(['pr', 'list', '--repo', this.target, '--state', 'open', '--head', branch, '--base', base, '--limit', '100', '--json', 'number,headRefName,baseRefName'])
    if (!Array.isArray(rows) || rows.length > 1 || rows.some(pr => !pr || !Number.isSafeInteger(pr.number) || pr.number < 1 || pr.headRefName !== branch || pr.baseRefName !== base)) throw Error('GitHub did not return an unambiguous task pull request')
    return rows[0] ? this.read(String(rows[0].number), false) : undefined
  }
  async publish(input: ForgePublication) {
    let pr = await this.find(input.branch, input.base)
    if (!pr) {
      if (input.saved) throw new Refusal('The saved pull request is no longer open; nothing was created')
      try { await this.git.ghRun(this.repo, ['pr', 'create', '--repo', this.target, '--draft', '--base', input.base, '--head', input.branch, '--title', input.title, '--body-file', '-'], 60, input.body) }
      catch (error) {
        // A create may have succeeded before its reply was lost. Inspect once, never blindly create again.
        pr = await this.find(input.branch, input.base).catch(() => undefined)
        if (!pr) throw error
      }
      pr ??= await this.find(input.branch, input.base)
    }
    if (!pr || pr.head !== input.head || pr.source !== input.branch || pr.base !== input.base || pr.state !== 'OPEN' || input.saved && !samePr(input.saved, pr.identity)) throw new Refusal('GitHub did not confirm this exact task pull request')
    return pr
  }
  async prepare(pr: ForgePullRequest, body: string) {
    const current = await this.read(String(pr.identity.number), false, pr.identity)
    if (current.head !== pr.head || current.source !== pr.source || current.base !== pr.base || current.state !== 'OPEN') throw new Refusal('The pull request changed before readiness; report this exact commit again')
    await this.git.ghRun(this.repo, ['pr', 'edit', String(pr.identity.number), '--repo', this.target, '--body-file', '-'], 60, body)
    if (current.draft) await this.git.ghRun(this.repo, ['pr', 'ready', String(pr.identity.number), '--repo', this.target])
  }
  async integrate(pr: ForgePullRequest, head: string) {
    if (!commit(head) || pr.head !== head || !pr.checks?.complete || !pr.checks.green) throw new Refusal('GitHub checks are not green or complete for the approved commit')
    const current = await this.read(String(pr.identity.number), false, pr.identity)
    if (current.head !== head || current.source !== pr.source || current.base !== pr.base || current.state !== 'OPEN') throw new Refusal('The pull request head or base differs from the approved task')
    await this.git.ghRun(this.repo, ['pr', 'merge', String(pr.identity.number), '--squash', '--match-head-commit', head, '--repo', this.target], 90)
    return { state: 'accepted' as const }
  }
  async comments(saved: ForgePrRecord) {
    if (!Number.isSafeInteger(saved.number) || saved.number < 1) throw Error('This task has no confirmed GitHub pull request')
    // Verify saved repository context even when checks are inaccessible.
    await this.read(String(saved.number), false, saved)
    const root = `repos/${this.identity.repository}`, get = (path: string) => this.json<unknown[]>(['api', '--hostname', this.identity.host, '--paginate', '--slurp', path + '?per_page=100'])
    const [reviews, lines, notes] = await Promise.all([get(`${root}/pulls/${saved.number}/reviews`), get(`${root}/pulls/${saved.number}/comments`), get(`${root}/issues/${saved.number}/comments`)])
    if (![reviews, lines, notes].every(Array.isArray) || [...reviews, ...lines, ...notes].some(page => !Array.isArray(page))) throw Error('Invalid GitHub comment pages')
    const result = [...prComments(reviews, 'r'), ...prComments(lines, 'c', reviews.flat()), ...prComments(notes, 'i')]
    if (result.length > 10000) throw Error('Too many GitHub comments for one bounded snapshot')
    return result.sort((a, b) => a.at - b.at || a.id.localeCompare(b.id))
  }
  async observeBase(branch: string, old: { green?: string; red?: string }): Promise<ForgeBaseObservation> {
    const host = this.identity.host, name = this.identity.repository
    const readHead = () => this.git.ghRun(this.repo, ['api', '--hostname', host, `repos/${name}/commits/${encodeURIComponent(branch)}`, '--jq', '.sha'])
    const baseHead = await readHead()
    if (!commit(baseHead)) throw Error('GitHub did not confirm the base commit')
    const history = await this.json<unknown>(['api', '--hostname', host, `repos/${name}/commits?sha=${encodeURIComponent(branch)}&per_page=100`, '--jq', 'map(.sha)'])
    if (!Array.isArray(history) || history[0] !== baseHead) throw Error('The base changed while reading GitHub history')
    const args = ['run', 'list', '--repo', this.target, '--branch', branch, '--event', 'push', '--limit', '100', '--json', 'headSha,status,conclusion,url,workflowName,databaseId']
    const candidates = mainCandidates(await this.json<unknown>(args), history)
    let selected: { head: string; verdict: ReturnType<typeof mainVerdict> } | undefined
    for (const candidate of candidates.slice(0, 3)) {
      const verdict = mainVerdict(await this.json<unknown>([...args, '--commit', candidate.head]), candidate.head)
      if (verdict.state !== 'pending') { selected = { head: candidate.head, verdict }; break }
    }
    const context = selected?.verdict.state === 'fail' && !old.red
      ? await this.baseFailureContext(selected, candidates, history, args, old.green) : { merged: [] }
    if (await readHead() !== baseHead) throw Error('The base changed while checking GitHub; waiting for a fresh snapshot')
    return { baseHead, selected, context }
  }
  private async previousGreen(head: string, candidates: { head: string; verdict: ForgeBaseVerdict }[], history: string[], args: string[], saved?: string) {
    if (saved && history.indexOf(saved) > history.indexOf(head)) return saved
    const previous = candidates.find(candidate => history.indexOf(candidate.head) > history.indexOf(head) && candidate.verdict.state === 'pass')
    if (previous && mainVerdict(await this.json<unknown>([...args, '--commit', previous.head]), previous.head).state === 'pass') return previous.head
  }
  private async mergeContext(head: string, green?: string) {
    const root = `repos/${this.identity.repository}`
    const endpoint = green ? `${root}/compare/${green}...${head}` : `${root}/commits/${head}`
    const jq = green ? '[.commits[-20:][] | {sha, message: .commit.message}]' : '[{sha, message: .commit.message}]'
    const commits = await this.json<{ sha: string; message: string }[]>(['api', '--hostname', this.identity.host, endpoint, '--jq', jq], 20)
    if (!Array.isArray(commits) || commits.length > 20 || commits.some(row => !row || !commit(row.sha) || typeof row.message !== 'string')) throw Error('Invalid merge context')
    return commits.map(row => ({ sha: row.sha, title: row.message.split('\n')[0].slice(0, 500) }))
  }
  private async baseFailureContext(selected: { head: string; verdict: ForgeBaseVerdict }, candidates: { head: string; verdict: ForgeBaseVerdict }[], history: string[], args: string[], saved?: string) {
    let context: ForgeBaseObservation['context'] = { merged: [] }
    try {
      const green = await this.previousGreen(selected.head, candidates, history, args, saved)
      context = { sinceGreen: green, merged: await this.mergeContext(selected.head, green) }
    } catch { context.unavailable = true }
    const failed = selected.verdict.failed[0], run = failed?.run ?? Number(failed?.url.match(/\/actions\/runs\/(\d+)(?:\/|$)/)?.[1])
    if (Number.isSafeInteger(run) && run > 0) {
      try { context.logTail = await failureLogTail(this.git, this.repo, this.target, run) } catch { context.unavailable = true }
    }
    return context
  }
  async presentation(branch: string, saved?: ForgePrRecord) {
    let pr: ForgePullRequest, checksError: string | undefined
    try { pr = await this.read(branch, true, saved) }
    catch (error) {
      if (/no pull requests found/i.test(String((error as Error).message))) return { pr: null, why: 'No pull request yet.' }
      if (!/not accessible by personal access token/i.test(String((error as Error).message))) throw error
      pr = await this.read(branch, false, saved)
      // The existing panel can read Actions jobs when the token cannot read GraphQL checks.
      const items = await this.actionJobs(pr.head).catch(() => undefined)
      if (items) pr.checks = { head: pr.head, complete: true, items, summary: { state: 'unknown', text: 'Actions jobs' }, failures: [], green: false }
      else checksError = 'Could not read GitHub checks.'
    }
    if (pr.checks && !pr.checks.complete) checksError = 'GitHub checks may be incomplete.'
    return { pr: { number: pr.identity.number, title: pr.title, state: pr.state === 'MERGED' ? 'merged' as const : pr.state === 'CLOSED' ? 'closed' as const : pr.draft ? 'draft' as const : 'open' as const, url: pr.identity.url, checks: pr.checks?.items ?? [], ...(checksError ? { checksError } : {}) } }
  }
  private async actionJobs(head: string): Promise<PrCheck[]> {
    const root = `repos/${this.identity.repository}`, prefix = ['api', '--hostname', this.identity.host, '--paginate', '--slurp']
    const pages = await this.json<{ workflow_runs: { id: number }[] }[]>([...prefix, `${root}/actions/runs?head_sha=${head}&per_page=100`])
    if (!Array.isArray(pages) || pages.some(page => !Array.isArray(page.workflow_runs))) throw Error('Incomplete Actions runs')
    const runs = pages.flatMap(page => page.workflow_runs)
    if (runs.length > 20 || runs.some(run => !Number.isSafeInteger(run.id) || run.id < 1)) throw Error('Incomplete Actions runs')
    const items: PrCheck[] = []
    for (const run of runs) {
      const pages = await this.json<{ jobs: { name: string; status: string; conclusion: string | null; html_url: string }[] }[]>([...prefix, `${root}/actions/runs/${run.id}/jobs?per_page=100`])
      if (!Array.isArray(pages) || pages.some(page => !Array.isArray(page.jobs))) throw Error('Incomplete Actions jobs')
      for (const job of pages.flatMap(page => page.jobs)) {
        if (!job || typeof job.name !== 'string' || typeof job.status !== 'string' || typeof job.html_url !== 'string') throw Error('Incomplete Actions job')
        items.push({ name: job.name, url: job.html_url, state: job.status !== 'completed' ? 'pending' : job.conclusion === 'skipped' ? 'skip' : ['success', 'neutral'].includes(job.conclusion ?? '') ? 'pass' : 'fail' })
      }
    }
    return items
  }
}
