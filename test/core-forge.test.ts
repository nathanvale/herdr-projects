import { expect, test } from 'bun:test'
import { CoreForge, repositoryOf, resolveOrigins, samePr } from '../server/core/forge/index.ts'
import { CoreGit } from '../server/core/git.ts'
import type { CoreFiles } from '../server/core/files.ts'

const head = 'a'.repeat(40), merged = 'b'.repeat(40)
const repo = { machine: 'machine', folder: '/task' }
/** Literal provider fixtures are independent of the adapter's DTO conversion. */
const raw = { number: 7, url: 'https://github.test/o/r/pull/7', title: 'Example', state: 'OPEN', isDraft: true, headRefOid: head, headRefName: 'work/one', baseRefName: 'main', mergeCommit: null, statusCheckRollup: [{ name: 'Check', conclusion: 'SUCCESS' }] }
function fixture(options: { used?: string; written?: string; push?: string; origin?: boolean; contained?: boolean } = {}) {
  const calls: { argv: string[]; dispatch: string[]; input?: Record<string, unknown>; body?: string }[] = []
  const used = options.used ?? 'https://github.test/o/r.git', written = options.written ?? used
  let rows: unknown[] = [], response: Record<string, unknown> = { ...raw }, lostCreate = false, denial = false, failOrigin = false
  let pages: Record<string, unknown> = {}
  const files = { exec: async (_machine: string, argv: string[], _cwd?: string, input?: Buffer) => {
    const dispatch = [...argv]
    let body: string | undefined, envelope: Record<string, unknown> | undefined
    if (options.contained) { envelope = JSON.parse(input!.toString()); argv = [String(envelope!.tool), ...envelope!.args as string[]]; body = envelope!.stdin as string | undefined }
    else body = input?.toString()
    calls.push({ argv, dispatch, input: envelope, body })
    if (argv[0] === 'git') {
      if (failOrigin) throw Error('Core machine disconnected')
      if (argv.length === 2 && argv[1] === 'remote') return Buffer.from(options.origin === false ? '' : 'origin')
      if (argv[1] === 'remote') return Buffer.from(argv.includes('--push') ? options.push ?? used : used)
      if (argv[1] === 'config') return Buffer.from(written)
    }
    if (argv[0] === 'gh') {
      if (denial) throw Error('HTTP 403: authentication denied')
      if (argv[1] === 'pr') {
        if (argv[2] === 'list') return Buffer.from(JSON.stringify(rows))
        if (argv[2] === 'view') return Buffer.from(JSON.stringify(response))
        if (argv[2] === 'create') { rows = [{ number: 7, headRefName: 'work/one', baseRefName: 'main' }]; if (lostCreate) throw Error('Create reply lost'); return Buffer.from(raw.url) }
        if (argv[2] === 'merge') { response = { ...response, state: 'MERGED', mergeCommit: { oid: merged } }; return Buffer.alloc(0) }
        if (argv[2] === 'ready') response = { ...response, isDraft: false }
        if (['edit', 'ready'].includes(argv[2])) return Buffer.alloc(0)
      }
      if (argv[1] === 'api') return Buffer.from(JSON.stringify(pages[argv.at(-1)!] ?? []))
    }
    throw Error('Unexpected controlled forge command')
  } } as unknown as CoreFiles
  const git = new CoreGit(files, options.contained ? () => ({ repo: '/repo', writableRoots: ['/repo', '/task'] }) : undefined, async () => ({ root: '/immutable', bun: '/native/bun' }))
  return { forge: new CoreForge(git), calls, setRaw(value: object) { response = { ...response, ...value } }, setRows(value: unknown[]) { rows = value }, setPages(value: Record<string, unknown>) { pages = value }, loseCreate() { lostCreate = true }, deny() { denial = true }, disconnect() { failOrigin = true } }
}

test('forge resolution preserves GitHub URL forms and aliases and identifies Bitbucket without reinterpreting legacy PRs', () => {
  for (const url of ['git@github.company.test:owner/repo.git', 'ssh://git@github.company.test:2222/owner/repo.git', 'https://github.company.test/owner/repo.git/']) expect(repositoryOf(url)).toEqual({ provider: 'github', host: 'github.company.test', repository: 'owner/repo' })
  expect(resolveOrigins(['git@ssh-alias:owner/repo.git'], ['https://github.com/owner/repo.git'])).toEqual({ provider: 'github', host: 'github.com', repository: 'owner/repo' })
  expect(repositoryOf('git@bitbucket.org:workspace/repo.git')).toEqual({ provider: 'bitbucket', host: 'bitbucket.org', repository: 'workspace/repo' })
  const identity = { provider: 'github' as const, host: 'github.test', repository: 'o/r', number: 7, url: raw.url }
  expect(samePr({ number: 7, url: raw.url }, identity)).toBe(true)
  expect(samePr({ number: 7, url: raw.url, provider: 'bitbucket' }, identity)).toBe(false)
  expect(samePr({ number: 7, url: raw.url, repository: 'other/r' }, identity)).toBe(false)
})

test('absent/local origins stay distinct from unsupported, multiple, contradictory and unavailable forge targets', async () => {
  for (const options of [{ origin: false }, { used: '/tmp/local.git' }]) expect(await fixture(options).forge.repository(repo)).toBeUndefined()
  for (const options of [{ used: 'https://gitlab.com/o/r.git' }, { used: 'https://bitbucket.org/o/r.git' }, { used: 'https://github.test/other/r.git', written: 'https://github.test/o/r.git' }, { used: 'https://github.test/o/r.git\nhttps://github.test/other/r.git' }, { push: 'https://github.test/other/r.git' }]) {
    const f = fixture(options)
    await expect(f.forge.require(repo)).rejects.toThrow()
    expect(f.calls.filter(call => call.argv[0] === 'gh')).toEqual([])
  }
  const disconnected = fixture(); disconnected.disconnect()
  await expect(disconnected.forge.repository(repo)).rejects.toThrow('Core machine disconnected')
})

test('publication reconciles a lost create reply into one qualified exact-head PR through the checked broker', async () => {
  const f = fixture({ contained: true }); f.loseCreate()
  const forge = await f.forge.require(repo)
  const input = { branch: 'work/one', base: 'main', title: 'Example', body: 'Description', head }
  const pr = await forge.publish(input)
  expect(pr.identity).toEqual({ provider: 'github', host: 'github.test', repository: 'o/r', number: 7, url: 'https://github.test/o/r/pull/7' })
  expect(pr).toMatchObject({ head, base: 'main', source: 'work/one', state: 'OPEN', draft: true })
  expect((await forge.publish({ ...input, saved: pr.identity })).identity).toEqual(pr.identity)
  expect(f.calls.filter(call => call.argv[2] === 'create')).toHaveLength(1)
  expect(f.calls.find(call => call.argv[2] === 'create')?.input).toMatchObject({ tool: 'gh', cwd: '/task', repo: '/repo', stdin: 'Description', timeout: 60000 })
  expect(f.calls.every(call => call.input?.tool === call.argv[0])).toBe(true)
  expect(f.calls.every(call => call.dispatch.join(' ') === '/native/bun /immutable/helper/core-pilot-git.ts')).toBe(true)
})

test('ambiguous lookups and authentication failures refuse publication without another create', async () => {
  const f = fixture(), forge = await f.forge.require(repo)
  f.setRows([{ number: 7, headRefName: 'work/one', baseRefName: 'main' }, { number: 8, headRefName: 'work/one', baseRefName: 'main' }])
  await expect(forge.publish({ branch: 'work/one', base: 'main', title: 'Example', body: 'Description', head })).rejects.toThrow('unambiguous')
  f.deny()
  await expect(forge.read('work/one')).rejects.toThrow('authentication denied')
  expect(f.calls.filter(call => call.argv[2] === 'create')).toEqual([])
})

test('checks retain candidate identity and distinguish absent, pending, cancelled and incomplete observations', async () => {
  const f = fixture(), forge = await f.forge.require(repo)
  const cases = [
    { rows: [], state: 'none', green: true, complete: true },
    { rows: [{ conclusion: 'SUCCESS' }, { state: 'PENDING' }], state: 'running', green: false, complete: true },
    { rows: [{ conclusion: 'CANCELLED' }], state: 'failed', green: false, complete: true },
    { rows: Array.from({ length: 100 }, () => ({ conclusion: 'SUCCESS' })), state: 'unknown', green: false, complete: false },
  ]
  for (const row of cases) {
    f.setRaw({ statusCheckRollup: row.rows })
    const pr = await forge.read('work/one')
    expect(pr.checks).toMatchObject({ head: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', complete: row.complete, green: row.green, summary: { state: row.state } })
    expect(pr.checks?.items).toHaveLength(row.rows.length)
  }
  f.setRaw({ statusCheckRollup: undefined })
  await expect(forge.read('work/one')).rejects.toThrow('Incomplete GitHub checks')
})

test('integration retains the source branch and exact source-head server precondition and confirms only observed merges', async () => {
  const f = fixture(), forge = await f.forge.require(repo), pr = await forge.read('work/one')
  expect(await forge.integrate(pr, head)).toEqual({ state: 'accepted' })
  expect(f.calls.find(call => call.argv[2] === 'merge')?.argv).toEqual(['gh', 'pr', 'merge', '7', '--squash', '--match-head-commit', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '--repo', 'github.test/o/r'])
  expect(await forge.read('7', false, pr.identity)).toMatchObject({ state: 'MERGED', mergeCommit: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' })
  expect(f.calls.some(call => call.argv.includes('--delete-branch'))).toBe(false)
})

test('changed head, destination or repository refuses readiness and merge before a forge write', async () => {
  for (const change of [{ headRefOid: merged }, { baseRefName: 'other' }, { headRefName: 'other' }, { url: 'https://github.test/other/r/pull/7' }]) {
    const f = fixture(), forge = await f.forge.require(repo), pr = await forge.read('work/one')
    f.setRaw(change)
    await expect(forge.prepare(pr, 'Ready')).rejects.toThrow()
    await expect(forge.integrate(pr, head)).rejects.toThrow()
    expect(f.calls.filter(call => ['edit', 'ready', 'merge'].includes(call.argv[2]))).toEqual([])
  }
})

test('feedback includes later pages and hides pending review drafts through the same task-facing seam', async () => {
  const f = fixture(), forge = await f.forge.require(repo)
  const comment = (id: number, body: string) => ({ id, body, user: { login: 'reviewer' }, html_url: `https://github.test/o/r/pull/7#issuecomment-${id}`, created_at: '2026-11-04T00:00:00Z' })
  f.setPages({
    'repos/o/r/pulls/7/reviews?per_page=100': [[{ ...comment(1, 'Private'), state: 'PENDING' }]],
    'repos/o/r/pulls/7/comments?per_page=100': [[]],
    'repos/o/r/issues/7/comments?per_page=100': [[comment(2, 'First')], [comment(3, 'Later page')]],
  })
  const comments = await forge.comments({ number: 7, url: raw.url })
  expect(comments.map(row => ({ id: row.id, body: row.body }))).toEqual([{ id: 'i2', body: 'First' }, { id: 'i3', body: 'Later page' }])
  expect(f.calls.filter(call => call.argv[1] === 'api').every(call => call.argv.includes('--paginate') && call.argv.includes('--slurp'))).toBe(true)
})

test('an effective GitHub host rewrite retains a canonical saved GitHub link and routes to the effective host', async () => {
  const f = fixture({ used: 'http://github.localhost/o/r.git', written: 'https://github.com/o/r.git' })
  f.setRaw({ url: 'https://github.com/o/r/pull/7' })
  const forge = await f.forge.require(repo)
  const pr = await forge.read('work/one', false, { number: 7, url: 'https://github.com/o/r/pull/7' })
  expect(pr.identity).toEqual({ provider: 'github', host: 'github.localhost', repository: 'o/r', number: 7, url: 'https://github.com/o/r/pull/7' })
  expect(f.calls.at(-1)?.argv).toContain('github.localhost/o/r')
})

test('the PR panel discloses incomplete checks while retaining the provider link', async () => {
  const f = fixture(), forge = await f.forge.require(repo)
  f.setRaw({ statusCheckRollup: Array.from({ length: 100 }, () => ({ conclusion: 'SUCCESS' })) })
  expect(await forge.presentation('work/one')).toMatchObject({ pr: { number: 7, url: 'https://github.test/o/r/pull/7', state: 'draft', checksError: 'GitHub checks may be incomplete.' } })
})
