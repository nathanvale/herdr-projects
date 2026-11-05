import type { ForgePullRequest } from './types.ts'

export interface BitbucketCredentialContext { host: 'bitbucket.org'; path: string; username?: string }
export interface BitbucketContext {
  repository: string
  folder: string
  credential: BitbucketCredentialContext
  origins: { used: string; written: string; push: string }
}
export type BitbucketOperation =
  | { kind: 'probe'; branch: string; base: string }
  | { kind: 'read'; number: number; checks: boolean }
  | { kind: 'find'; branch: string; base?: string; checks: boolean }
  | { kind: 'create'; branch: string; base: string; head: string; title: string; body: string }
  | { kind: 'prepare'; number: number; branch: string; base: string; head: string; body: string }
export interface BitbucketRequest { version: 1; context: BitbucketContext; operation: BitbucketOperation }
export type BitbucketFailure = 'invalid-request' | 'missing-credentials' | 'permission-refused' | 'rate-limited' | 'malformed-response' | 'incomplete-read' | 'uncertain-write' | 'identity-changed' | 'unavailable'
export interface BitbucketResult { pr?: ForgePullRequest; matches?: ForgePullRequest[] }
export type BitbucketReply = { ok: true; result: BitbucketResult } | { ok: false; category: BitbucketFailure }

export const BITBUCKET_LIMITS = Object.freeze({ input: 128 * 1024, title: 512, description: 32000, body: 1024 * 1024, pages: 20, rows: 1000, requestMs: 8000, totalMs: 45000, credentialMs: 5000, credentialBytes: 16384 })
export const bitbucketCommit = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{40}$/.test(value)
export const bitbucketBranch = (value: unknown): value is string => typeof value === 'string' && value.length <= 255 && /^[A-Za-z0-9][A-Za-z0-9/_.-]*$/.test(value) && !value.includes('..') && !value.endsWith('/') && !value.endsWith('.lock')
export const bitbucketRepository = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-][A-Za-z0-9_.-]*\/[A-Za-z0-9_-][A-Za-z0-9_.-]*$/.test(value) && value.length <= 256

/** Credentials follow the admitted HTTPS origin; SSH's transport user is never an account. */
export function bitbucketCredential(origins: BitbucketContext['origins'], repository: string): BitbucketCredentialContext {
  let username: string | undefined, path = repository + '.git'
  for (const [index, origin] of [origins.written, origins.used, origins.push].entries()) {
    if (/^https:\/\//i.test(origin)) {
      const url = new URL(origin)
      if (url.hostname !== 'bitbucket.org' || url.port && url.port !== '443' || url.password || url.search || url.hash) throw Error('Invalid Bitbucket origin')
      const actual = decodeURIComponent(url.pathname.replace(/^\//, '').replace(/\/$/, ''))
      if (actual.replace(/\.git$/, '') !== repository) throw Error('Invalid Bitbucket repository')
      const user = decodeURIComponent(url.username) || undefined
      if (user && (!/^[^\r\n\0=]{1,128}$/.test(user) || username && username !== user)) throw Error('Invalid Bitbucket account context')
      username ??= user
      path = actual
    } else {
      const match = origin.match(/^(?:ssh:\/\/)?(?:[^@/:]+@)?([^/:]+)(?::\d+)?[:/]([^?#]+)$/)
      if (!match || match[2].replace(/\/$/, '').replace(/\.git$/, '') !== repository || index === 0 && match[1] !== 'bitbucket.org') throw Error('Invalid Bitbucket SSH origin')
    }
  }
  return { host: 'bitbucket.org', path, ...(username ? { username } : {}) }
}

function invalidRequest(): never { throw Error('Invalid Bitbucket request') }
function requestObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalidRequest()
  return value as Record<string, unknown>
}
function requestFields(value: Record<string, unknown>, names: readonly string[]) {
  if (Object.keys(value).some(key => !names.includes(key))) invalidRequest()
}
function requestContext(value: unknown): BitbucketContext {
  const context = requestObject(value), origins = requestObject(context.origins), credential = requestObject(context.credential)
  requestFields(context, ['repository', 'folder', 'origins', 'credential'])
  requestFields(origins, ['used', 'written', 'push']); requestFields(credential, ['host', 'path', 'username'])
  if (!bitbucketRepository(context.repository) || typeof context.folder !== 'string' || !context.folder.startsWith('/') || context.folder.length > 4096 || /[\r\n\0]/.test(context.folder) || [origins.used, origins.written, origins.push].some(value => typeof value !== 'string' || value.length > 4096)) invalidRequest()
  const lookup = bitbucketCredential(origins as BitbucketContext['origins'], context.repository)
  if (lookup.host !== credential.host || lookup.path !== credential.path || lookup.username !== credential.username) invalidRequest()
  return context as unknown as BitbucketContext
}
function requestOperation(value: unknown): BitbucketOperation {
  const op = requestObject(value)
  const names: Record<string, string[]> = { probe: ['branch', 'base'], read: ['number', 'checks'], find: ['branch', 'base', 'checks'], create: ['branch', 'base', 'head', 'title', 'body'], prepare: ['number', 'branch', 'base', 'head', 'body'] }
  if (typeof op.kind !== 'string' || !Object.hasOwn(names, op.kind)) invalidRequest()
  const fields = names[op.kind]; requestFields(op, ['kind', ...fields])
  for (const key of ['branch', 'base']) if (fields.includes(key) && !(key === 'base' && op.kind === 'find' && op.base === undefined) && !bitbucketBranch(op[key])) invalidRequest()
  if (fields.includes('number') && (typeof op.number !== 'number' || !Number.isSafeInteger(op.number) || op.number < 1)) invalidRequest()
  if (fields.includes('head') && !bitbucketCommit(op.head)) invalidRequest()
  if (fields.includes('checks') && typeof op.checks !== 'boolean') invalidRequest()
  for (const key of ['title', 'body']) if (fields.includes(key) && (typeof op[key] !== 'string' || op[key].length > (key === 'title' ? BITBUCKET_LIMITS.title : BITBUCKET_LIMITS.description))) invalidRequest()
  return op as unknown as BitbucketOperation
}

/** One bounded request contract for application preflight and host defense. */
export function parseBitbucketRequest(value: unknown): BitbucketRequest {
  const row = requestObject(value); requestFields(row, ['version', 'context', 'operation'])
  if (row.version !== 1) invalidRequest()
  requestContext(row.context); requestOperation(row.operation)
  if (new TextEncoder().encode(JSON.stringify(row)).length > BITBUCKET_LIMITS.input) invalidRequest()
  return row as unknown as BitbucketRequest
}
