import { join } from 'node:path'
import { createHash } from 'node:crypto'
import type { PilotRepositoryContext } from './pilot-repositories.ts'
import { Refusal } from './client.ts'
import type { CoreFiles } from './files.ts'
import type { ExecAdmission } from './files.ts'
import type { BitbucketGitOperation, BitbucketGitRequest } from '../../helper/core-bitbucket-git.ts'

export interface RepoLocation { machine: string; folder: string }
export class CoreGit {
  constructor(private readonly files: CoreFiles,
    private readonly guard?: (repo: RepoLocation, additional?: string[]) => PilotRepositoryContext | undefined,
    private readonly runtime?: (machine: string, provision?: boolean) => Promise<{ bun: string; root: string }>) {}
  /** Observation retains the checked broker, but can never provision helpers. */
  observer() { return new CoreGit(this.files, this.guard, this.runtime && (machine => this.runtime!(machine, false))) }
  private async execute(repo: RepoLocation, tool: 'git' | 'gh', args: string[], timeout: number, stdin?: string, additional?: string[], admit?: ExecAdmission, provision = true) {
    const context = this.guard?.(repo, additional)
    if (!context) return this.files.exec(repo.machine, [tool, ...args], repo.folder, stdin === undefined ? undefined : Buffer.from(stdin), timeout, admit)
    if (admit) throw new Refusal('Contained repository ownership changed before publication; nothing was provisioned or pushed')
    if (!this.runtime) throw Error('Checked repository runtime is unavailable')
    const runtime = await this.runtime(repo.machine, provision)
    return this.files.exec(repo.machine, [runtime.bun, join(runtime.root, 'helper/core-pilot-git.ts')], undefined,
      Buffer.from(JSON.stringify({ ...context, cwd: repo.folder, tool, args, stdin, timeout: timeout * 1000 })), timeout + 10)
  }
  async run(repo: RepoLocation, args: string[], timeout = 30, stdin?: string, additional?: string[]) { return (await this.execute(repo, 'git', args, timeout, stdin, additional)).toString('utf8').trim() }
  /** Origin admission must not provision a new checked runtime before provider selection. */
  async origin(repo: RepoLocation, args: string[]) {
    if (!this.guard?.(repo)) return this.run(repo, args)
    return (await this.execute(repo, 'git', args, 30, undefined, undefined, undefined, false)).toString('utf8').trim()
  }
  async ghRun(repo: RepoLocation, args: string[], timeout = 60, stdin?: string) { return (await this.execute(repo, 'gh', args, timeout, stdin)).toString('utf8').trim() }
  private async frozen(repo: RepoLocation, destination: string, operation: BitbucketGitOperation, admit: () => void) {
    const validate = () => {
      if (this.guard?.(repo)) throw new Refusal('Contained repository ownership changed before publication; nothing was provisioned or pushed')
      admit()
    }
    validate()
    if (!this.runtime) throw new Refusal('The admitted Git transport runtime is unavailable')
    const runtime = await this.runtime(repo.machine, false)
    validate()
    const input: BitbucketGitRequest = { folder: repo.folder, destination, operation }
    const output = await this.files.exec(repo.machine, [runtime.bun, '--no-env-file', join(runtime.root, 'helper/core-bitbucket-git.ts')], join(runtime.root, 'helper'),
      Buffer.from(JSON.stringify(input)), 120, validate)
    validate()
    let reply: { ok: boolean; observed?: string }
    try { reply = JSON.parse(output.toString('utf8')) } catch { throw new Refusal('The admitted Git transport did not return a complete response') }
    if (reply.ok !== true || typeof reply.observed !== 'string') throw new Refusal('Git did not confirm the operation on the admitted destination')
    return reply.observed
  }
  async head(repo: RepoLocation, ref = 'HEAD') { return this.run(repo, ['rev-parse', '--verify', '--end-of-options', `${ref}^{commit}`]) }
  async branchHead(repo: RepoLocation, branch: string) {
    const ref = `refs/heads/${branch}`
    const rows = (await this.run(repo, ['for-each-ref', '--format=%(refname) %(objectname)', ref])).split('\n')
    const row = rows.find(row => row.startsWith(ref + ' '))
    if (!row) return undefined
    const head = row.slice(ref.length + 1)
    if (!/^[a-f0-9]{40,64}$/.test(head)) throw Error('Git returned an invalid branch identity')
    return head
  }
  async clean(repo: RepoLocation) { return !(await this.run(repo, ['status', '--porcelain'])).length }
  async gh<T>(repo: RepoLocation, args: string[], timeout = 60): Promise<T> {
    const text = await this.ghRun(repo, args, timeout)
    return (text ? JSON.parse(text) : undefined) as T
  }
  async contains(repo: RepoLocation, base: string, head: string) {
    const common = await this.run(repo, ['merge-base', base, head])
    return common === await this.head(repo, head)
  }
  async addWorktree(repo: RepoLocation, folder: string, branch: string, base: string) {
    if (!/^[A-Za-z0-9][A-Za-z0-9/_.-]*$/.test(base) || base.includes('..')) throw new Error('Invalid base branch')
    await this.head(repo, base)
    await this.run(repo, ['worktree', 'add', '-b', branch, folder, base], 60, undefined, [folder])
  }
  /** Reopen only the saved branch at its saved location; Git refuses occupied paths without overwriting. */
  async ensureWorktree(repo: RepoLocation, folder: string, branch: string, base: string): Promise<boolean> {
    const blocks = (await this.run(repo, ['worktree', 'list', '--porcelain'])).split('\n\n').map(block => block.split('\n'))
    const ref = `branch refs/heads/${branch}`
    const here = blocks.find(lines => lines.includes(`worktree ${folder}`))
    if (here) {
      if (!here.includes(ref)) throw Error('The saved task folder now belongs to another branch; it was left untouched')
      if (await this.run({ machine: repo.machine, folder }, ['symbolic-ref', '--quiet', 'HEAD']) !== `refs/heads/${branch}`) throw Error('The saved task checkout changed; it was left untouched')
      return false
    }
    if (blocks.some(lines => lines.includes(ref))) throw Error('The saved task branch is checked out elsewhere; it was left untouched')
    if (await this.branchHead(repo, branch)) await this.run(repo, ['worktree', 'add', folder, branch], 60, undefined, [folder])
    else await this.addWorktree(repo, folder, branch, base)
    return true
  }
  async pushTaskBranch(repo: RepoLocation, branch: string, expected?: string, admit?: () => void, candidate?: string, destination = 'origin') {
    if (!/^[A-Za-z0-9][A-Za-z0-9/_.-]*$/.test(branch) || branch.includes('..') || expected !== undefined && !/^[a-f0-9]{40,64}$/.test(expected)) throw Error('Invalid saved task branch identity')
    const ref = `refs/heads/${branch}`
    if (await this.run(repo, ['symbolic-ref', '--quiet', 'HEAD']) !== ref) throw Error('The task branch is not checked out; nothing was pushed')
    const head = await this.head(repo, ref)
    if (!/^[a-f0-9]{40,64}$/.test(head)) throw Error('Git did not return a task commit identity')
    if (candidate && head !== candidate) throw new Refusal('The task candidate changed during publication preflight; nothing was pushed')
    try {
      const args = ['push', `--force-with-lease=${ref}:${expected ?? ''}`, destination, `${head}:${ref}`]
      if (admit) await this.frozen(repo, destination, { kind: 'push', branch, head, expected }, admit)
      else await this.run(repo, args, 90)
    } catch (error) {
      // A lost response is not a reason to blindly repeat a force push. Confirm the exact remote commit.
      let remote: string
      try {
        const args = ['ls-remote', '--heads', destination, ref]
        remote = admit ? await this.frozen(repo, destination, { kind: 'observe', branch }, admit) : await this.run(repo, args, 60)
      } catch { throw error }
      if (remote !== `${head}\t${ref}`) throw error
    }
    return head
  }
  async syncBase(repo: RepoLocation, base: string, merged: string) {
    if (!/^[A-Za-z0-9][A-Za-z0-9/_.-]*$/.test(base) || base.includes('..') || !/^[a-f0-9]{40,64}$/.test(merged)) throw Error('Invalid confirmed base identity')
    const ref = `refs/shepherdr/base-sync/${createHash('sha256').update(JSON.stringify([repo.machine, repo.folder, base])).digest('hex')}`
    await this.run(repo, ['fetch', '--no-tags', 'origin', `refs/heads/${base}:${ref}`], 90)
    const fetched = await this.head(repo, ref)
    if (!await this.contains(repo, fetched, merged)) throw Error('The fetched base does not contain GitHub’s confirmed merge')
    if (await this.contains(repo, base, merged)) return
    if (await this.run(repo, ['symbolic-ref', '--quiet', 'HEAD']) !== `refs/heads/${base}`) throw Error('The base branch is not checked out')
    await this.fastForward(repo, fetched)
  }
  /** Git alone judges what is at risk, so unrelated local work stays out of the way; a change to a file it ignores counts too. */
  async fastForward(repo: RepoLocation, target: string) {
    try { await this.run(repo, ['merge', '--ff-only', '--no-autostash', '--no-overwrite-ignore', target], 60) }
    catch (error) {
      const files = String((error as Error).message).split('\n').filter(row => row.startsWith('\t')).map(row => row.trim())
      if (!files.length) throw error
      throw new Refusal(`The base checkout's own copy of ${files.slice(0, 5).join(', ')}${files.length > 5 ? ` and ${files.length - 5} more` : ''} would be overwritten. Nothing was changed there. It needs committing, moving or removing first`)
    }
  }
}
