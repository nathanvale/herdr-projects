import { mkdtempSync, readdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { isAbsolute, join } from 'node:path'
import { tmpdir } from 'node:os'
import { bitbucketBranch, bitbucketCommit } from '../server/core/forge/bitbucket-protocol.ts'

export type BitbucketGitOperation = { kind: 'push'; branch: string; head: string; expected?: string } | { kind: 'observe'; branch: string }
export interface BitbucketGitRequest { folder: string; destination: string; operation: BitbucketGitOperation }

const CONFIG_LIMIT = 128 * 1024
function operation(value: unknown): BitbucketGitOperation {
  const op = value as BitbucketGitOperation
  if (!op || !['push', 'observe'].includes(op.kind) || !bitbucketBranch(op.branch)) throw Error('operation')
  const fields = op.kind === 'push' ? ['kind', 'branch', 'head', 'expected'] : ['kind', 'branch']
  if (Object.keys(op).some(key => !fields.includes(key))) throw Error('operation')
  if (op.kind === 'push' && (!bitbucketCommit(op.head) || op.expected !== undefined && !bitbucketCommit(op.expected))) throw Error('candidate')
  return op
}
function request(value: unknown): BitbucketGitRequest {
  if (!value || typeof value !== 'object') throw Error('request')
  const row = value as BitbucketGitRequest
  if (Object.keys(row).some(key => !['folder', 'destination', 'operation'].includes(key)) || typeof row.folder !== 'string' || !isAbsolute(row.folder) || /[\r\n\0]/.test(row.folder) || typeof row.destination !== 'string' || row.destination.length > 4096 || /[\s\0]/.test(row.destination) || row.destination.startsWith('-')) throw Error('request')
  // Only the adapter's admitted HTTPS or SSH Bitbucket transport is accepted.
  if (!/^(?:https:\/\/(?:[^/@:]+@)?bitbucket\.org(?::443)?\/|(?:ssh:\/\/)?(?:[^@/:]+@)?[A-Za-z0-9.-]+(?::\d+)?[:/])[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?$/.test(row.destination)) throw Error('destination')
  operation(row.operation)
  return row
}

async function bounded(stream: ReadableStream<Uint8Array>, limit: number) {
  const reader = stream.getReader(), parts: Uint8Array[] = []; let bytes = 0
  try {
    for (;;) {
      const part = await reader.read()
      if (part.done) return Buffer.concat(parts).toString('utf8')
      bytes += part.value.length
      if (bytes > limit) throw Error('bounded output')
      parts.push(part.value)
    }
  } finally { await reader.cancel().catch(() => {}) }
}

async function execute(args: string[], folder: string, env: Record<string, string | undefined>, limit: number, timeout: number) {
  const child = Bun.spawn(['git', ...args], { cwd: folder, env, stdin: 'ignore', stdout: 'pipe', stderr: 'ignore' })
  let timer: Timer | undefined
  try {
    const deadline = new Promise<never>((_, reject) => { timer = setTimeout(() => { child.kill('SIGKILL'); reject(Error('deadline')) }, timeout) })
    const [text, code] = await Promise.race([Promise.all([bounded(child.stdout, limit), child.exited]), deadline])
    if (code !== 0) throw Error('git refused')
    return text
  } finally { clearTimeout(timer); if (child.exitCode === null) child.kill('SIGKILL'); await child.exited }
}

function configuration(text: string) {
  const rows: [string, string][] = []
  for (const entry of text.split('\0').filter(Boolean)) {
    const split = entry.indexOf('\n'), key = split < 0 ? entry : entry.slice(0, split), value = split < 0 ? 'true' : entry.slice(split + 1)
    // Flatten active includes once. Replaying their declarations would reread
    // mutable files and reintroduce routing after the snapshot was filtered.
    if (/^url\..*\.(?:insteadof|pushinsteadof)$|^include\.path$|^includeif\..*\.path$|^extensions\.worktreeconfig$/i.test(key)) continue
    rows.push([key, value])
  }
  if (rows.length > 1024) throw Error('bounded configuration')
  return rows
}

async function frozen(input: BitbucketGitRequest) {
  const owned = { ...process.env, GIT_TERMINAL_PROMPT: '0', GIT_ASKPASS: '/usr/bin/false', SSH_ASKPASS: '/usr/bin/false', GCM_INTERACTIVE: '0' }
  const read = (args: string[], limit = 4096) => execute(args, input.folder, owned, limit, 5000)
  const gitDir = (await read(['rev-parse', '--absolute-git-dir'])).trimEnd()
  const common = (await read(['rev-parse', '--path-format=absolute', '--git-common-dir'])).trimEnd()
  if (!isAbsolute(gitDir) || !isAbsolute(common) || (await read(['rev-parse', '--show-object-format'])).trim() !== 'sha1') throw Error('repository')
  // Configuration values, including host-owned credential helper declarations,
  // remain private in memory. No credential configuration is written to disk.
  const pairs = configuration(await read(['config', '--null', '--list', '--includes'], CONFIG_LIMIT))
  const shadow = mkdtempSync(join(tmpdir(), 'shep-bb-git-route-'))
  try {
    // Keep the real HEAD, objects, refs, hooks and repository metadata. Only the
    // common config has an operation-local view without URL routing rules.
    for (const name of readdirSync(common)) if (!['config', 'config.worktree'].includes(name)) symlinkSync(join(common, name), join(shadow, name))
    writeFileSync(join(shadow, 'config'), '[core]\nrepositoryformatversion = 0\nbare = false\n', { mode: 0o600, flag: 'wx' })
    const env: Record<string, string | undefined> = { ...owned }
    for (const key of Object.keys(env)) if (/^GIT_CONFIG(?:$|_COUNT$|_PARAMETERS$|_KEY_\d+$|_VALUE_\d+$)/.test(key)) delete env[key]
    Object.assign(env, { GIT_DIR: gitDir, GIT_COMMON_DIR: shadow, GIT_WORK_TREE: input.folder, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_SYSTEM: '/dev/null', GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_COUNT: String(pairs.length) })
    pairs.forEach(([key, value], n) => { env[`GIT_CONFIG_KEY_${n}`] = key; env[`GIT_CONFIG_VALUE_${n}`] = value })
    const op = input.operation, ref = `refs/heads/${op.branch}`
    if (op.kind === 'push') {
      await execute(['push', `--force-with-lease=${ref}:${op.expected ?? ''}`, input.destination, `${op.head}:${ref}`], input.folder, env, 4096, 90000)
      return op.head
    }
    const observed = (await execute(['ls-remote', '--heads', input.destination, ref], input.folder, env, 4096, 60000)).trimEnd()
    if (observed && !new RegExp(`^[a-f0-9]{40}\\t${ref.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`).test(observed)) throw Error('remote identity')
    return observed
  } finally { rmSync(shadow, { recursive: true, force: true }) }
}

if (import.meta.main) {
  try {
    const observed = await frozen(request(JSON.parse(await bounded(Bun.stdin.stream(), 16384))))
    process.stdout.write(JSON.stringify({ ok: true, observed }))
  } catch { process.stdout.write(JSON.stringify({ ok: false })) }
}
