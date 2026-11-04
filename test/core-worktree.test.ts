import { expect, test } from 'bun:test'
import { mkdtempSync, rmSync, writeFileSync, symlinkSync, linkSync, unlinkSync, mkdirSync, chmodSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CoreWorktree } from '../server/core/worktree.ts'
import { CoreTasks, type CoreTask } from '../server/core/tasks.ts'
import type { CoreSource } from '../server/core/source.ts'
import { CoreStore } from '../server/core/store.ts'
import { runChild } from './child.ts'
import { readWorktree } from '../helper/core-worktree.ts'

// Real scratch Git repositories, run on GitHub only.
test('native worktree files, literal paths, rename diff and path isolation', async () => {
  const root = mkdtempSync(join(tmpdir(), 'shep-tree-'))
  const git = (...args: string[]) => {
    const result = Bun.spawnSync(['git', ...args], { cwd: root, stdin: 'ignore' })
    if (result.exitCode) throw Error(result.stderr.toString())
  }
  try {
    git('init', '-b', 'main'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
    writeFileSync(join(root, 'example.txt'), 'before\n'); writeFileSync(join(root, 'a\tb.txt'), 'before\n'); writeFileSync(join(root, 'original.txt'), 'rename\n'); writeFileSync(join(root, '.gitignore'), '.env\n')
    git('add', '.'); git('commit', '-m', 'baseline'); git('switch', '-c', 'work/example')
    writeFileSync(join(root, 'example.txt'), 'after\n'); writeFileSync(join(root, 'a\tb.txt'), 'after\n'); git('mv', 'original.txt', 'renamed.txt'); writeFileSync(join(root, '[literal].txt'), 'new\n')
    writeFileSync(join(root, '.env'), 'SYNTHETIC_PRIVATE_MATERIAL')
    symlinkSync('.env', join(root, 'alias.txt'))
    symlinkSync('/etc/passwd', join(root, 'outside.txt'))
    linkSync(join(root, '.env'), join(root, 'linked.txt'))
    const ask = { folder: root, base: 'main', branch: 'work/example' }
    expect(await readWorktree({ ...ask, what: 'files' })).toMatchObject({ files: expect.arrayContaining(['example.txt', '[literal].txt']) })
    expect(await readWorktree({ ...ask, what: 'file', path: '[literal].txt' })).toMatchObject({ text: 'new\n' })
    for (const path of ['../secret', '.git/config', '.env', 'alias.txt', 'outside.txt', 'linked.txt']) await expect(readWorktree({ ...ask, what: 'file', path })).rejects.toThrow()
    unlinkSync(join(root, 'linked.txt'))
    expect(await readWorktree({ ...ask, what: 'diff' })).toMatchObject({ files: expect.arrayContaining([expect.objectContaining({ path: 'example.txt', add: 1, del: 1 }), expect.objectContaining({ path: '[literal].txt', add: 1 }), expect.objectContaining({ path: 'a\tb.txt', add: 1, del: 1 }), expect.objectContaining({ path: 'renamed.txt', status: 'renamed', from: 'original.txt' })]) })
    expect(await readWorktree({ ...ask, what: 'patch', path: '[literal].txt' })).toMatchObject({ text: expect.stringContaining('+new') })
    await expect(readWorktree({ ...ask, what: 'pr' })).rejects.toThrow('forge module')
    await expect(readWorktree({ ...ask, what: 'patch', path: '.env' })).rejects.toThrow('no changes')
    unlinkSync(join(root, 'example.txt')); linkSync(join(root, '.env'), join(root, 'example.txt'))
    await expect(readWorktree({ ...ask, what: 'file', path: 'example.txt' })).rejects.toThrow()
    await expect(readWorktree({ ...ask, what: 'diff' })).rejects.toThrow('readable boundary')
    await expect(readWorktree({ ...ask, what: 'patch', path: 'example.txt' })).rejects.toThrow('readable boundary')
  } finally { rmSync(root, { recursive: true, force: true }) }
})


test('unreadable GitHub checks are not reported as no checks', async () => {
  const root = mkdtempSync(join(tmpdir(), 'shep-tree-gh-')), bin = join(root, 'bin')
  mkdirSync(bin)
  const git = (...args: string[]) => { const result = Bun.spawnSync(['git', ...args], { cwd: root, stdin: 'ignore' }); if (result.exitCode) throw Error(result.stderr.toString()) }
  try {
    git('init', '-b', 'main'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
    writeFileSync(join(root, 'example.txt'), 'example\n'); git('add', '.'); git('commit', '-m', 'baseline'); git('remote', 'add', 'origin', 'https://github.com/example/example.git')
    const gh = join(bin, 'gh')
    writeFileSync(gh, `#!${process.execPath}\nconst args=process.argv.slice(2);if(!args.some(word=>word.split(',').includes('statusCheckRollup'))){process.stdout.write(JSON.stringify({number:1,title:'Example',state:'OPEN',isDraft:false,url:'https://github.com/example/example/pull/1',headRefOid:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',headRefName:'main',baseRefName:'main'}))}else{process.stderr.write('not accessible by personal access token');process.exitCode=1}`)
    chmodSync(gh, 0o700)
    const store = new CoreStore(join(root, 'home'))
    const task = { id: 'DEMO-1', machine: 'machine', folder: root, branch: 'main' } as CoreTask
    const source = { store, files: { exec: async (_machine: string, argv: string[], cwd?: string, input?: Uint8Array) => runChild(argv, { cwd, input, env: { ...process.env, PATH: bin + ':' + process.env.PATH } }) } } as unknown as CoreSource
    const tasks = new CoreTasks(source); Object.assign(source, { tasks }); tasks.get = () => task
    try { expect(await new CoreWorktree(source).ask({ task: 'DEMO-1', what: 'pr' })).toMatchObject({ pr: { number: 1, title: 'Example', checks: [], checksError: 'Could not read GitHub checks.' } }) }
    finally { store.close() }
  } finally { rmSync(root, { recursive: true, force: true }) }
})

test('contained file and diff panels use checked Git without executing host callbacks', async () => {
  const root = mkdtempSync(join(tmpdir(), 'shep-tree-checked-'))
  const git = (...args: string[]) => { const p = Bun.spawnSync(['git', ...args], { cwd: root }); if (p.exitCode) throw Error(p.stderr.toString()) }
  try {
    git('init', '-b', 'main'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
    writeFileSync(join(root, '[literal].txt'), 'before\n'); git('add', '.'); git('commit', '-m', 'Base')
    writeFileSync(join(root, '[literal].txt'), 'after\n')
    const marker = join(root, 'executed'), callback = join(root, 'callback')
    writeFileSync(callback, `#!/bin/sh\nprintf executed > '${marker}'\n`, { mode: 0o700 })
    git('config', 'core.fsmonitor', callback)
    const checked = { repo: root, writableRoots: [root], bun: process.execPath, helper: join(import.meta.dir, '../helper/core-pilot-git.ts') }
    const ask = { folder: root, base: 'main', branch: 'main', checked }
    expect(await readWorktree({ ...ask, what: 'file', path: '[literal].txt' })).toMatchObject({ text: 'after\n' })
    expect(await readWorktree({ ...ask, what: 'patch', path: '[literal].txt' })).toMatchObject({ text: expect.stringContaining('+after') })
    expect(await Bun.file(marker).exists()).toBe(false)
    git('config', 'include.path', '../not-created.cfg')
    await expect(readWorktree({ ...ask, what: 'files' })).rejects.toThrow('no longer available')
  } finally { rmSync(root, { recursive: true, force: true }) }
})

async function withGitHubPanel(origin: string, canonicalHost: string, run: (context: { root: string; tasks: CoreTasks; source: CoreSource; calls: string[][]; git: (...args: string[]) => Promise<Buffer> }) => Promise<void>) {
  const root = mkdtempSync(join(tmpdir(), 'shep-tree-enterprise-')), store = new CoreStore(join(root, 'home'))
  const env = { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_SYSTEM: '/dev/null' }
  const calls: string[][] = []
  const task = { id: 'DEMO-1', machine: 'machine', folder: root, branch: 'work/one' } as CoreTask
  try {
    await runChild(['git', 'init', '-b', 'main'], { cwd: root, env })
    await runChild(['git', 'remote', 'add', 'origin', origin], { cwd: root, env })
    const source = { store, files: { exec: async (_machine: string, argv: string[], cwd?: string, input?: Uint8Array) => {
      calls.push([...argv])
      if (argv[0] === 'gh') return Buffer.from(JSON.stringify({
        number: 7, title: 'Enterprise candidate', state: 'OPEN', isDraft: false,
        url: `https://${canonicalHost}/owner/repo/pull/7`, headRefOid: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        headRefName: 'work/one', baseRefName: 'main', mergeCommit: null,
        statusCheckRollup: [{ name: 'Build', conclusion: 'SUCCESS', detailsUrl: `https://${canonicalHost}/owner/repo/actions/runs/9` }],
      }))
      return runChild(argv, { cwd, input, env })
    } } } as unknown as CoreSource
    const tasks = new CoreTasks(source); Object.assign(source, { tasks }); tasks.get = () => task
    await run({ root, tasks, source, calls, git: (...args) => runChild(['git', ...args], { cwd: root, env }) })
  } finally { store.close(); rmSync(root, { recursive: true, force: true }) }
}

test('public PR panel retains arbitrary GitHub Enterprise hosts and canonical links after SSH rewrites', () => withGitHubPanel('git@ghe.example.com:owner/repo.git', 'ghe.example.com', async ({ root, tasks, source, calls, git }) => {
    expect(await new CoreWorktree(source).ask({ task: 'DEMO-1', what: 'pr' })).toEqual({ pr: {
      number: 7, title: 'Enterprise candidate', state: 'open', url: 'https://ghe.example.com/owner/repo/pull/7',
      checks: [{ name: 'Build', state: 'pass', url: 'https://ghe.example.com/owner/repo/actions/runs/9' }],
    } })
    await git('config', 'url.git@ssh-alias:.insteadOf', 'git@ghe.example.com:')
    expect(await new CoreWorktree(source).ask({ task: 'DEMO-1', what: 'pr' })).toEqual({ pr: {
      number: 7, title: 'Enterprise candidate', state: 'open', url: 'https://ghe.example.com/owner/repo/pull/7',
      checks: [{ name: 'Build', state: 'pass', url: 'https://ghe.example.com/owner/repo/actions/runs/9' }],
    } })
    expect(calls.filter(argv => argv[0] === 'gh')).toEqual([
      ['gh', 'pr', 'view', 'work/one', '--repo', 'ghe.example.com/owner/repo', '--json',
        'number,url,title,state,isDraft,headRefOid,headRefName,baseRefName,mergeCommit,statusCheckRollup'],
      ['gh', 'pr', 'view', 'work/one', '--repo', 'ssh-alias/owner/repo', '--json',
        'number,url,title,state,isDraft,headRefOid,headRefName,baseRefName,mergeCommit,statusCheckRollup'],
    ])
    // Read-only legacy compatibility must not turn an unknown origin into task write authority.
    await expect(tasks.forge.require({ machine: 'machine', folder: root })).rejects.toThrow('unsupported forge')
    await git('remote', 'set-url', 'origin', 'git@bitbucket.org:owner/repo.git')
    expect(await new CoreWorktree(source).ask({ task: 'DEMO-1', what: 'pr' })).toMatchObject({ pr: null, why: expect.stringContaining('Bitbucket Cloud operations are not implemented') })
    expect(calls.filter(argv => argv[0] === 'gh')).toHaveLength(2)
}))

test('T1 compatibility: public PR panels route recognized GitHub origins through effective aliases', () => withGitHubPanel('git@github.com:owner/repo.git', 'github.com', async ({ root, tasks, source, calls, git }) => {
  await git('config', 'url.git@ssh-alias:.insteadOf', 'git@github.com:')
  expect(await new CoreWorktree(source).ask({ task: 'DEMO-1', what: 'pr' })).toEqual({ pr: {
    number: 7, title: 'Enterprise candidate', state: 'open', url: 'https://github.com/owner/repo/pull/7',
    checks: [{ name: 'Build', state: 'pass', url: 'https://github.com/owner/repo/actions/runs/9' }],
  } })
  expect(calls.filter(argv => argv[0] === 'gh')).toEqual([
    ['gh', 'pr', 'view', 'work/one', '--repo', 'ssh-alias/owner/repo', '--json', 'number,url,title,state,isDraft,headRefOid,headRefName,baseRefName,mergeCommit,statusCheckRollup'],
  ])
  // Presentation routing does not confer task authority on an otherwise unsupported host.
  const forge = await tasks.forge.require({ machine: 'machine', folder: root })
  expect(forge.identity).toEqual({ provider: 'github', host: 'github.com', repository: 'owner/repo' })
  await git('config', '--unset', 'url.git@ssh-alias:.insteadOf')
  await git('remote', 'set-url', 'origin', 'git@ssh-alias:owner/repo.git')
  await expect(tasks.forge.require({ machine: 'machine', folder: root })).rejects.toThrow('unsupported forge')
}))

test('T1 compatibility: public PR panels ignore fork pushurl while task operations retain write-target validation', () => withGitHubPanel('git@github.com:owner/repo.git', 'github.com', async ({ root, tasks, source, calls, git }) => {
  await git('config', 'remote.origin.pushurl', 'git@github.com:myfork/repo.git')
  calls.length = 0
  expect(await new CoreWorktree(source).ask({ task: 'DEMO-1', what: 'pr' })).toEqual({ pr: {
    number: 7, title: 'Enterprise candidate', state: 'open', url: 'https://github.com/owner/repo/pull/7',
    checks: [{ name: 'Build', state: 'pass', url: 'https://github.com/owner/repo/actions/runs/9' }],
  } })
  expect(calls.some(argv => argv[0] === 'git' && argv.includes('--push'))).toBe(false)
  expect(calls.filter(argv => argv[0] === 'gh')).toEqual([
    ['gh', 'pr', 'view', 'work/one', '--repo', 'github.com/owner/repo', '--json', 'number,url,title,state,isDraft,headRefOid,headRefName,baseRefName,mergeCommit,statusCheckRollup'],
  ])
  await expect(tasks.forge.require({ machine: 'machine', folder: root })).rejects.toThrow('different forge repositories')
  expect(calls.filter(argv => argv[0] === 'gh')).toHaveLength(1)
}))
