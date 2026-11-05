import { BITBUCKET_LIMITS as LIMIT, bitbucketBranch, bitbucketCommit, bitbucketCredential, bitbucketRepository } from './bitbucket-protocol.ts'
import type { BitbucketContext, BitbucketFailure, BitbucketOperation, BitbucketReply, BitbucketRequest } from './bitbucket-protocol.ts'
import type { ForgeChecks, ForgePullRequest } from './types.ts'

class TransportFailure extends Error {
  constructor(readonly category: BitbucketFailure) { super(category) }
}
const fail: (category: BitbucketFailure) => never = category => { throw new TransportFailure(category) }
const object = (value: unknown): Record<string, any> => { if (!value || typeof value !== 'object' || Array.isArray(value)) fail('malformed-response'); return value as Record<string, any> }
function fields(value: Record<string, unknown>, names: string[]) { if (Object.keys(value).some(key => !names.includes(key))) fail('invalid-request') }
function parseRequest(value: unknown): BitbucketRequest {
  const row = object(value); fields(row, ['version', 'context', 'operation'])
  const context = object(row.context), origins = object(context.origins), credential = object(context.credential), operation = object(row.operation)
  fields(context, ['repository', 'folder', 'origins', 'credential']); fields(origins, ['used', 'written', 'push']); fields(credential, ['host', 'path', 'username'])
  if (row.version !== 1 || !bitbucketRepository(context.repository) || typeof context.folder !== 'string' || !context.folder.startsWith('/') || context.folder.length > 4096 || /[\r\n\0]/.test(context.folder) || Object.values(origins).some(value => typeof value !== 'string' || value.length > 4096)) fail('invalid-request')
  let expected: unknown
  try { expected = bitbucketCredential(origins as BitbucketContext['origins'], context.repository) } catch { fail('invalid-request') }
  const lookup = expected as BitbucketContext['credential']
  if (lookup.host !== credential.host || lookup.path !== credential.path || lookup.username !== credential.username) fail('invalid-request')
  const names: Record<string, string[]> = { probe: ['branch', 'base'], read: ['number', 'checks'], find: ['branch', 'base', 'checks'], create: ['branch', 'base', 'head', 'title', 'body'], prepare: ['number', 'branch', 'base', 'head', 'body'] }
  if (!Object.hasOwn(names, operation.kind)) fail('invalid-request')
  fields(operation, ['kind', ...names[operation.kind]])
  for (const key of ['branch', 'base']) if (names[operation.kind].includes(key) && !(key === 'base' && operation.kind === 'find' && operation.base === undefined) && !bitbucketBranch(operation[key])) fail('invalid-request')
  if (names[operation.kind].includes('number') && (!Number.isSafeInteger(operation.number) || operation.number < 1)) fail('invalid-request')
  if (names[operation.kind].includes('head') && !bitbucketCommit(operation.head)) fail('invalid-request')
  if (names[operation.kind].includes('checks') && typeof operation.checks !== 'boolean') fail('invalid-request')
  for (const key of ['title', 'body']) if (names[operation.kind].includes(key) && (typeof operation[key] !== 'string' || operation[key].length > (key === 'title' ? 512 : 32000))) fail('invalid-request')
  return row as BitbucketRequest
}

async function bounded(stream: ReadableStream<Uint8Array> | null, limit: number): Promise<string> {
  if (!stream) return ''
  const reader = stream.getReader(), chunks: Uint8Array[] = []
  let bytes = 0
  try {
    for (;;) {
      const row = await reader.read()
      if (row.done) return Buffer.concat(chunks).toString('utf8')
      bytes += row.value.length
      if (bytes > limit) fail('incomplete-read')
      chunks.push(row.value)
    }
  } finally { await reader.cancel().catch(() => {}) }
}

async function git(context: BitbucketContext, args: string[], input?: string): Promise<string> {
  // Git's regular host config retains authority; stdout/stderr never leave this helper.
  const child = Bun.spawn(['git', ...args], { cwd: context.folder, env: { ...process.env, GIT_TERMINAL_PROMPT: '0', GIT_ASKPASS: '/usr/bin/false', SSH_ASKPASS: '/usr/bin/false', GCM_INTERACTIVE: '0' }, stdin: input === undefined ? 'ignore' : Buffer.from(input), stdout: 'pipe', stderr: 'ignore' })
  let timer: Timer | undefined
  try {
    const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => { child.kill('SIGKILL'); reject(new TransportFailure('missing-credentials')) }, LIMIT.credentialMs) })
    const [text, code] = await Promise.race([Promise.all([bounded(child.stdout, LIMIT.credentialBytes), child.exited]), timeout])
    if (code !== 0) fail('missing-credentials')
    return text.trimEnd()
  } finally { clearTimeout(timer); if (child.exitCode === null) child.kill('SIGKILL'); await child.exited }
}

async function credential(context: BitbucketContext) {
  const observed = { used: await git(context, ['remote', 'get-url', '--all', 'origin']), written: await git(context, ['config', '--get-all', 'remote.origin.url']), push: await git(context, ['remote', 'get-url', '--push', '--all', 'origin']) }
  if (JSON.stringify(observed) !== JSON.stringify(context.origins)) fail('identity-changed')
  const lookup = context.credential
  const description = `protocol=https\nhost=bitbucket.org\npath=${lookup.path}\n${lookup.username ? `username=${lookup.username}\n` : ''}\n`
  const text = await git(context, ['credential', 'fill'], description)
  const rows = text.split('\n'), values = new Map<string, string>()
  for (const row of rows) {
    const index = row.indexOf('=')
    if (index <= 0 || values.has(row.slice(0, index))) fail('missing-credentials')
    values.set(row.slice(0, index), row.slice(index + 1))
  }
  if ([...values.keys()].some(key => !['protocol', 'host', 'path', 'username', 'password'].includes(key))) fail('missing-credentials')
  const token = values.get('password'), user = values.get('username')
  if (!token || !/^[\x21-\x7e]{1,8192}$/.test(token) || !user || lookup.username && user !== lookup.username || values.get('protocol') !== 'https' || values.get('host') !== 'bitbucket.org' || values.has('path') && values.get('path') !== lookup.path) fail('missing-credentials')
  return token
}

class BitbucketHttp {
  private readonly root: string
  private readonly started = Date.now()
  constructor(private readonly context: BitbucketContext, private readonly token: string) { this.root = `https://api.bitbucket.org/2.0/repositories/${context.repository.split('/').map(encodeURIComponent).join('/')}` }
  private clean(value: string) { return value.replaceAll(`Bearer ${this.token}`, '[redacted]').replaceAll(this.token, '[redacted]').replaceAll(encodeURIComponent(this.token), '[redacted]').replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, '').slice(0, 32000) }
  private link(value: unknown, path: string) {
    if (typeof value !== 'string') fail('malformed-response')
    let url: URL
    try { url = new URL(value) } catch { return fail('malformed-response') }
    if (url.protocol !== 'https:' || url.hostname !== 'bitbucket.org' || url.port || url.username || url.password || url.search || url.hash || url.pathname !== path || value.includes(this.token)) fail('malformed-response')
    return url.href
  }
  private target(value: string, collection?: string) {
    let url: URL
    try { url = new URL(value) } catch { return fail('incomplete-read') }
    if (url.origin !== 'https://api.bitbucket.org' || url.username || url.password || url.hash || value.includes(this.token) || value.includes(encodeURIComponent(this.token)) || collection && url.pathname !== new URL(collection).pathname || !url.href.startsWith(this.root + '/')) fail('incomplete-read')
    return url.href
  }
  private async request(url: string, method: 'GET' | 'POST' | 'PUT' = 'GET', body?: object): Promise<unknown> {
    const write = method !== 'GET', remaining = LIMIT.totalMs - (Date.now() - this.started)
    if (remaining <= 0) fail(write ? 'uncertain-write' : 'incomplete-read')
    try {
      const response = await fetch(url, { method, headers: { Authorization: `Bearer ${this.token}`, Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body && JSON.stringify(body), redirect: 'manual', signal: AbortSignal.timeout(Math.min(LIMIT.requestMs, remaining)) })
      if (response.status === 401 || response.status === 403) fail('permission-refused')
      if (response.status === 429) fail(write ? 'uncertain-write' : 'rate-limited')
      if (response.status >= 300 && response.status < 400) fail(write ? 'uncertain-write' : 'incomplete-read')
      if (!response.ok) fail(write ? 'uncertain-write' : response.status === 404 ? 'identity-changed' : 'unavailable')
      const text = await bounded(response.body, LIMIT.body)
      try { return JSON.parse(text) } catch { fail(write ? 'uncertain-write' : 'malformed-response') }
    } catch (error) { if (error instanceof TransportFailure) { if (write && !['permission-refused', 'uncertain-write'].includes(error.category)) fail('uncertain-write'); throw error } fail(write ? 'uncertain-write' : 'incomplete-read') }
  }
  private repository(value: unknown) {
    const row = object(value)
    if (row.full_name !== this.context.repository) fail('identity-changed')
    this.link(object(object(row.links).html).href, `/${this.context.repository}`)
  }
  private pr(value: unknown): ForgePullRequest {
    const row = object(value), source = object(row.source), destination = object(row.destination)
    this.repository(source.repository); this.repository(destination.repository)
    if (!Number.isSafeInteger(row.id) || row.id < 1 || typeof row.title !== 'string' || !['OPEN', 'DECLINED', 'SUPERSEDED', 'MERGED'].includes(row.state) || typeof row.draft !== 'boolean' || !bitbucketCommit(object(source.commit).hash) || !bitbucketBranch(object(source.branch).name) || !bitbucketBranch(object(destination.branch).name)) fail('malformed-response')
    const url = this.link(object(object(row.links).html).href, `/${this.context.repository}/pull-requests/${row.id}`)
    return { identity: { provider: 'bitbucket', host: 'bitbucket.org', repository: this.context.repository, number: row.id, url }, title: this.clean(row.title), state: row.state === 'MERGED' ? 'MERGED' : row.state === 'OPEN' ? 'OPEN' : 'CLOSED', draft: row.draft, head: source.commit.hash, source: source.branch.name, base: destination.branch.name }
  }
  private async pages(url: string) {
    const rows: unknown[] = [], visited = new Set<string>()
    let next: string | undefined = url
    let size: number | undefined
    while (next) {
      const target = this.target(next, url)
      if (visited.has(target) || visited.size >= LIMIT.pages) fail('incomplete-read')
      visited.add(target)
      const page = object(await this.request(target))
      if (!Array.isArray(page.values) || page.values.length > 100 || page.next !== undefined && (typeof page.next !== 'string' || !page.next)) fail('malformed-response')
      for (const name of ['page', 'pagelen']) if (page[name] !== undefined && (!Number.isSafeInteger(page[name]) || page[name] < 1)) fail('incomplete-read')
      if (page.previous !== undefined) {
        if (typeof page.previous !== 'string') fail('malformed-response')
        this.target(page.previous, url)
      }
      if (page.size !== undefined) {
        if (!Number.isSafeInteger(page.size) || page.size < 0 || page.size > LIMIT.rows || size !== undefined && size !== page.size) fail('incomplete-read')
        size = page.size
      }
      rows.push(...page.values)
      if (rows.length > LIMIT.rows) fail('incomplete-read')
      next = page.next
    }
    if (size !== undefined && rows.length !== size) fail('incomplete-read')
    return rows
  }
  private async find(branch: string, base?: string) {
    const query = `state="OPEN" AND source.branch.name=${JSON.stringify(branch)}${base ? ` AND destination.branch.name=${JSON.stringify(base)}` : ''}`
    const rows = await this.pages(`${this.root}/pullrequests?pagelen=100&q=${encodeURIComponent(query)}`)
    const prs = rows.map(row => this.pr(row))
    if (prs.some(pr => pr.state !== 'OPEN' || pr.source !== branch || base && pr.base !== base) || prs.length > 1) fail('identity-changed')
    return prs
  }
  private async read(number: number) {
    const pr = this.pr(await this.request(`${this.root}/pullrequests/${number}`))
    if (pr.identity.number !== number) fail('identity-changed')
    return pr
  }
  private statusLink(value: unknown, resource: string) {
    const link = object(value)
    if (Object.keys(link).some(key => !['href', 'name'].includes(key)) || link.name !== undefined && typeof link.name !== 'string') fail('malformed-response')
    // Link fields are optional in the official schema. A supplied href must
    // agree with the exact commit resource; it is never followed for evidence.
    if (link.href !== undefined && (typeof link.href !== 'string' || this.target(link.href, resource) !== resource)) fail('malformed-response')
  }
  private optionalStatus(row: Record<string, any>, head: string) {
    for (const name of ['name', 'refname', 'url', 'description']) if (row[name] !== undefined && typeof row[name] !== 'string') fail('malformed-response')
    for (const name of ['created_on', 'updated_on']) if (row[name] !== undefined && (typeof row[name] !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(row[name]) || !Number.isFinite(Date.parse(row[name])))) fail('malformed-response')
    if (row.links !== undefined) {
      const links = object(row.links), commit = `${this.root}/commit/${head}`
      if (Object.keys(links).some(key => !['self', 'commit'].includes(key))) fail('malformed-response')
      if (links.commit !== undefined) this.statusLink(links.commit, commit)
      if (links.self !== undefined) this.statusLink(links.self, `${commit}/statuses/build/${encodeURIComponent(row.key)}`)
    }
  }
  private statusUrl(value: unknown) {
    // CI targets may belong to a vendor; expose only credential-free HTTPS.
    if (typeof value !== 'string' || value.includes(this.token) || value.includes(encodeURIComponent(this.token))) return
    try { const target = new URL(value); if (target.protocol === 'https:' && !target.username && !target.password) return target.href } catch {}
  }
  private status(value: unknown, head: string, keys: Set<string>) {
    const row = object(value)
    // commitstatus inherits required type from object through allOf. There is
    // no inline commit.hash, and name/links are optional in that contract.
    if (typeof row.type !== 'string' || typeof row.key !== 'string' || !row.key || keys.has(row.key) || !['SUCCESSFUL', 'FAILED', 'INPROGRESS', 'STOPPED'].includes(row.state)) fail('malformed-response')
    this.optionalStatus(row, head); keys.add(row.key)
    const url = this.statusUrl(row.url)
    return { name: this.clean(row.name ?? row.key), state: row.state === 'SUCCESSFUL' ? 'pass' as const : row.state === 'INPROGRESS' ? 'pending' as const : 'fail' as const, ...(url ? { url } : {}) }
  }
  private async checks(head: string): Promise<ForgeChecks> {
    try {
      const rows = await this.pages(`${this.root}/commit/${head}/statuses?pagelen=100`), keys = new Set<string>()
      const items = rows.map(value => this.status(value, head, keys))
      const failed = items.filter(item => item.state === 'fail'), running = items.filter(item => item.state === 'pending')
      return { head, complete: true, items, failures: failed, green: items.length > 0 && !failed.length && !running.length,
        summary: { state: !items.length ? 'none' : failed.length ? 'failed' : running.length ? 'running' : 'passed', text: !items.length ? 'None reported yet' : `${failed.length} failed, ${running.length} running, ${items.length - failed.length - running.length} passed` } }
    } catch (error) {
      if (!(error instanceof TransportFailure)) throw error
      return { head, complete: false, items: [], failures: [], green: false, summary: { state: 'unknown', text: 'Bitbucket checks are unavailable or incomplete' } }
    }
  }
  private matches(pr: ForgePullRequest, operation: { branch: string; base: string; head: string }) {
    if (pr.head !== operation.head || pr.source !== operation.branch || pr.base !== operation.base || pr.state !== 'OPEN') fail('identity-changed')
  }
  async perform(operation: BitbucketOperation) {
    // A REST repository read verifies token compatibility; it does not claim write scope.
    this.repository(await this.request(this.root))
    if (operation.kind === 'probe') {
      const branch = object(await this.request(`${this.root}/refs/branches/${encodeURIComponent(operation.base)}`))
      if (branch.name !== operation.base || !bitbucketCommit(object(branch.target).hash)) fail('identity-changed')
      return { matches: await this.find(operation.branch, operation.base) }
    }
    if (operation.kind === 'find') {
      const matches = await this.find(operation.branch, operation.base)
      if (operation.checks && matches[0]) {
        matches[0].checks = await this.checks(matches[0].head)
        const after = await this.read(matches[0].identity.number)
        if (after.head !== matches[0].head || after.source !== matches[0].source || after.base !== matches[0].base) fail('identity-changed')
      }
      return { matches }
    }
    if (operation.kind === 'read') {
      const pr = await this.read(operation.number)
      if (operation.checks) { pr.checks = await this.checks(pr.head); const after = await this.read(operation.number); if (after.head !== pr.head || after.source !== pr.source || after.base !== pr.base) fail('identity-changed') }
      return { pr }
    }
    if (operation.kind === 'create') {
      const matches = await this.find(operation.branch, operation.base)
      if (matches[0]) { this.matches(matches[0], operation); return { pr: matches[0] } }
      const source = object(await this.request(`${this.root}/refs/branches/${encodeURIComponent(operation.branch)}`))
      if (source.name !== operation.branch || object(source.target).hash !== operation.head) fail('identity-changed')
      const pr = this.pr(await this.request(`${this.root}/pullrequests`, 'POST', { title: operation.title, description: operation.body, draft: true, close_source_branch: false, source: { branch: { name: operation.branch }, commit: { hash: operation.head }, repository: { full_name: this.context.repository } }, destination: { branch: { name: operation.base }, repository: { full_name: this.context.repository } } }))
      this.matches(pr, operation)
      if (!pr.draft) fail('uncertain-write')
      return { pr }
    }
    const current = await this.read(operation.number); this.matches(current, operation)
    const pr = this.pr(await this.request(`${this.root}/pullrequests/${operation.number}`, 'PUT', { description: operation.body, draft: false }))
    this.matches(pr, operation)
    if (pr.draft || pr.identity.number !== operation.number) fail('uncertain-write')
    return { pr }
  }
}

/** Fixed-operation host seam. Failure categories contain no provider or credential text. */
export async function runBitbucket(value: unknown): Promise<BitbucketReply> {
  try {
    const request = parseRequest(value), token = await credential(request.context)
    const result = await new BitbucketHttp(request.context, token).perform(request.operation)
    if (JSON.stringify(result).includes(token)) fail('malformed-response')
    return { ok: true, result }
  } catch (error) { return { ok: false, category: error instanceof TransportFailure ? error.category : 'unavailable' } }
}
