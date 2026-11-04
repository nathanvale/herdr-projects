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

export const BITBUCKET_LIMITS = Object.freeze({ input: 128 * 1024, body: 1024 * 1024, pages: 20, rows: 1000, requestMs: 8000, totalMs: 45000, credentialMs: 5000, credentialBytes: 16384 })
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
