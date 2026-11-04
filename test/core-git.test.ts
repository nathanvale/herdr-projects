import { expect, test } from 'bun:test'
import { CoreGit } from '../server/core/git.ts'
import type { CoreFiles } from '../server/core/files.ts'

test('reopening a task checkout checks the saved branch/location and preserves occupied paths', async () => {
  let listing = 'worktree /tasks/one\nbranch refs/heads/work/one', branch = true
  const calls: string[][] = []
  const git = new CoreGit({ exec: async (_machine: string, argv: string[]) => {
    calls.push(argv)
    if (argv[1] === 'worktree' && argv[2] === 'list') return Buffer.from(listing)
    if (argv[1] === 'symbolic-ref') return Buffer.from('refs/heads/work/one')
    if (argv[1] === 'for-each-ref') return Buffer.from(branch ? 'refs/heads/work/one ' + 'a'.repeat(40) : '')
    if (argv[1] === 'rev-parse') return Buffer.from('a'.repeat(40))
    if (argv[1] === 'worktree' && argv[2] === 'add') return Buffer.alloc(0)
    throw Error('Unexpected command')
  } } as unknown as CoreFiles)
  const repo = { machine: 'remote', folder: '/repo' }
  await git.ensureWorktree(repo, '/tasks/one', 'work/one', 'main')
  expect(calls.some(args => args.includes('add'))).toBe(false)
  listing = 'worktree /tasks/one\nbranch refs/heads/other'
  await expect(git.ensureWorktree(repo, '/tasks/one', 'work/one', 'main')).rejects.toThrow('another branch')
  listing = 'worktree /tasks/elsewhere\nbranch refs/heads/work/one'
  await expect(git.ensureWorktree(repo, '/tasks/one', 'work/one', 'main')).rejects.toThrow('elsewhere')
  listing = ''
  await git.ensureWorktree(repo, '/tasks/one', 'work/one', 'main')
  expect(calls.at(-1)).toEqual(['git', 'worktree', 'add', '/tasks/one', 'work/one'])
  branch = false
  await git.ensureWorktree(repo, '/tasks/one', 'work/one', 'main')
  expect(calls.at(-1)).toEqual(['git', 'worktree', 'add', '-b', 'work/one', '/tasks/one', 'main'])
})

test('a lost push reply only settles when the remote confirms the exact captured task commit', async () => {
  const sha = 'a'.repeat(40), ref = 'refs/heads/work/one', calls: string[][] = [], git = new CoreGit({} as CoreFiles)
  let confirmed = true
  git.run = async (_repo, args) => { calls.push(args); if (args[0] === 'symbolic-ref') return ref; if (args[0] === 'rev-parse') return sha; if (args[0] === 'push') throw Error('Reply lost'); if (args[0] === 'ls-remote') return `${confirmed ? sha : 'b'.repeat(40)}\t${ref}`; throw Error('Unexpected command') }
  expect(await git.pushTaskBranch({ machine: 'machine', folder: '/work' }, 'work/one', 'c'.repeat(40))).toBe(sha)
  expect(calls.find(args => args[0] === 'push')).toEqual(['push', '--force-with-lease=refs/heads/work/one:' + 'c'.repeat(40), 'origin', `${sha}:${ref}`])
  confirmed = false
  await expect(git.pushTaskBranch({ machine: 'machine', folder: '/work' }, 'work/one', 'c'.repeat(40))).rejects.toThrow('Reply lost')
})

test('a checkout switch cannot change the task ref whose captured commit is pushed', async () => {
  const saved = 'a'.repeat(40), other = 'b'.repeat(40), ref = 'refs/heads/work/one', git = new CoreGit({} as CoreFiles), pushes: string[][] = []
  git.run = async (_repo, args) => {
    if (args[0] === 'symbolic-ref') return ref // Immediately afterward another caller switches HEAD.
    if (args[0] === 'rev-parse') return args.at(-1) === ref + '^{commit}' ? saved : other
    if (args[0] === 'push') { pushes.push(args); return '' }
    throw Error('Unexpected command')
  }
  expect(await git.pushTaskBranch({ machine: 'machine', folder: '/work' }, 'work/one')).toBe(saved)
  expect(pushes[0]).toEqual(['push', `--force-with-lease=${ref}:`, 'origin', `${saved}:${ref}`])
})
