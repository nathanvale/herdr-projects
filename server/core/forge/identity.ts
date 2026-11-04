import { Refusal } from '../client.ts'
import type { ForgeRepository, ForgePrRecord } from './types.ts'

/** Preserve GitHub's existing host convention, including enterprise hosts and named aliases. */
export function repositoryOf(url: string, githubPresentation = false): ForgeRepository | undefined {
  const match = url.trim().match(/^(?:[a-z+]+:\/\/)?(?:[^@/]+@)?([^/:]+)(?::\d+)?[:/]+([^/]+\/[^/]+?)(?:\.git)?\/?$/i)
  if (!match) return undefined
  const host = match[1].toLowerCase(), repository = match[2]
  const provider = host === 'bitbucket.org' ? 'bitbucket' : /github/i.test(host) || githubPresentation ? 'github' : undefined
  return provider ? { provider, host, repository } : undefined
}
/** URL rewrites may change the host, but cannot silently substitute a provider or repository. */
export function resolveOrigins(used: string[], written: string[], githubPresentation = false): ForgeRepository | undefined {
  if (used.length !== 1 || written.length !== 1) throw new Refusal('Multiple origin targets are unsupported; nothing was sent to a forge')
  const effective = repositoryOf(used[0]), original = repositoryOf(written[0])
  const rewrittenPath = used[0].match(/^(?:[a-z+]+:\/\/)?(?:[^@/]+@)?([^/:]+)(?::\d+)?[:/]+([^/]+\/[^/]+?)(?:\.git)?\/?$/i)?.[2]
  if (original && rewrittenPath && rewrittenPath !== original.repository) throw new Refusal('The written and effective origins name different forge repositories')
  if (effective && original && (effective.provider !== original.provider || effective.repository !== original.repository)) throw new Refusal('The written and effective origins name different forge repositories')
  const identity = effective ?? original
  if (identity) return identity
  // The legacy PR panel attempted gh on arbitrary Enterprise hosts. This fallback is
  // read-only presentation; task operations retain strict provider resolution.
  if (githubPresentation) {
    const enterprise = repositoryOf(used[0], true) ?? repositoryOf(written[0], true)
    if (enterprise) return enterprise
  }
  if (used[0].startsWith('/') || used[0].startsWith('./') || used[0].startsWith('../') || used[0].startsWith('file://')) return undefined
  throw new Refusal('The origin uses an unsupported forge; remote integration cannot fall back to a local merge')
}
/** A qualified record must match its repository; legacy records are checked against observed GitHub URLs. */
export function samePr(saved: ForgePrRecord, observed: ForgePrRecord & ForgeRepository) {
  return saved.number === observed.number && saved.url === observed.url && (saved.provider ?? 'github') === observed.provider &&
    (saved.host === undefined || saved.host === observed.host) && (saved.repository === undefined || saved.repository === observed.repository)
}

/** Compare saved snapshots without depending on property order or adding legacy qualification. */
export function sameSavedPr(left?: ForgePrRecord, right?: ForgePrRecord) {
  return !!left && !!right && left.number === right.number && left.url === right.url && left.provider === right.provider && left.host === right.host && left.repository === right.repository
}
