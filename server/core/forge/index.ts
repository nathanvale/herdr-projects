import { Refusal } from '../client.ts'
import type { CoreGit, RepoLocation } from '../git.ts'
import { GitHubForge } from './github.ts'
import { BitbucketForge, type BitbucketExecution } from './bitbucket.ts'
import type { RepositoryForge } from './types.ts'
import { repositoryOf, resolveOrigins } from './identity.ts'
export type { ForgePullRequest, ForgePrRecord, RepositoryForge } from './types.ts'
export { repositoryOf, resolveOrigins, samePr, sameSavedPr } from './identity.ts'
export class CoreForge {
  private readonly publishingKeys = new Set<string>()
  constructor(private readonly git: CoreGit, private readonly bitbucket?: BitbucketExecution) {}
  async repository(repo: RepoLocation, observation = false): Promise<RepositoryForge | undefined> { return this.resolve(repo, false, observation ? this.git.observer() : this.git) }
  private async resolve(repo: RepoLocation, githubPresentation = false, git = this.git): Promise<RepositoryForge | undefined> {
    if (!(await git.origin(repo, ['remote'])).split('\n').includes('origin')) return undefined
    const [used, written] = await Promise.all([
      git.origin(repo, ['remote', 'get-url', '--all', 'origin']), git.origin(repo, ['config', '--get-all', 'remote.origin.url']),
    ])
    const isBitbucket = repositoryOf(written)?.provider === 'bitbucket' || repositoryOf(used)?.provider === 'bitbucket'
    const identity = resolveOrigins(used.split('\n').filter(Boolean), written.split('\n').filter(Boolean), githubPresentation && !isBitbucket)
    if (!identity) return undefined
    let push = used
    if (!githubPresentation || isBitbucket) {
      push = await git.origin(repo, ['remote', 'get-url', '--push', '--all', 'origin'])
      const pushed = resolveOrigins(push.split('\n').filter(Boolean), written.split('\n').filter(Boolean))
      if (!pushed || pushed.provider !== identity.provider || pushed.repository !== identity.repository || pushed.host !== identity.host && pushed.host !== repositoryOf(written)?.host) throw new Refusal('The push origin differs from the task forge repository; nothing was published')
    }
    if (identity.provider === 'bitbucket') {
      if (!this.bitbucket) throw new Refusal('Bitbucket execution is unavailable; native integration also requires an enforceable expected-source-head guarantee')
      return new BitbucketForge(repo, identity, this.bitbucket, { used, written, push }, this.publishingKeys)
    }
    return new GitHubForge(git, repo, identity, [identity.host, repositoryOf(written, githubPresentation)?.host].filter((host): host is string => !!host))
  }
  async presentation(repo: RepoLocation, branch: string, saved?: import('./types.ts').ForgePrRecord) {
    if (!branch) return { pr: null, why: 'No branch yet.' }
    const forge = await this.resolve(repo, true)
    return forge ? forge.presentation(branch, saved) : { pr: null, why: 'This space has no forge remote.' }
  }
  async require(repo: RepoLocation) {
    const forge = await this.repository(repo)
    if (!forge) throw new Refusal('This task has no forge origin')
    return forge
  }
}
