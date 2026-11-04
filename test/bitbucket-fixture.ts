import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CoreTasks, type CoreTask } from '../server/core/tasks.ts'
import { CoreStore } from '../server/core/store.ts'
import { CoreFiles } from '../server/core/files.ts'
import type { CoreSource } from '../server/core/source.ts'
import type { CoreSession } from '../server/core/session.ts'
import type { Grant } from '../server/core/mailbox.ts'
import type { Message } from '../shared/types.ts'
import { runChild } from './child.ts'

export interface BitbucketFixture {
  tasks: CoreTasks; source: CoreSource; task: CoreTask; grant: Grant; root: string; repo: string; folder: string; bare: string; head: string
  calls: { argv: string[]; on?: string; cwd?: string }[]
  outputs: string[]
  update: (patch: Record<string, unknown>) => void
  state: () => Record<string, any>
  requests: () => { url: string; method: string; authorization: string }[]
  git: (folder: string, ...args: string[]) => Promise<string>
  reopen: () => void
  route: { epoch: number; on?: string; disconnected: boolean; before?: () => Promise<void> }
}

/** One sealed fake provider and Git credential owner; all processes use synthetic authority. */
export async function withBitbucket(run: (fixture: BitbucketFixture) => Promise<void>, remote = false) {
  const root = mkdtempSync(join(tmpdir(), 'shep-bb-')), repo = join(root, 'repo'), folder = join(root, 'worktree'), bare = join(root, 'remote.git')
  const statePath = join(root, 'provider.json'), requestsPath = join(root, 'requests.jsonl')
  mkdirSync(join(root, 'user')); writeFileSync(requestsPath, '')
  // Deliberately do not inherit real mailbox, provider, Git or cloud credentials.
  const env = { PATH: process.env.PATH, HOME: join(root, 'user'), XDG_CONFIG_HOME: join(root, 'user'), GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null',
    GIT_AUTHOR_NAME: 'Fixture', GIT_AUTHOR_EMAIL: 'fixture@example.invalid', GIT_COMMITTER_NAME: 'Fixture', GIT_COMMITTER_EMAIL: 'fixture@example.invalid', BITBUCKET_FIXTURE_STATE: statePath }
  const git = async (cwd: string, ...args: string[]) => (await runChild(['git', ...args], { cwd, env })).toString().trim()
  await runChild(['git', 'init', '--initial-branch=main', repo], { env })
  await runChild(['git', 'init', '--bare', '--initial-branch=main', bare], { env })
  writeFileSync(join(repo, 'value.txt'), 'base\n'); await git(repo, 'add', 'value.txt'); await git(repo, 'commit', '-m', 'Base')
  await git(repo, 'push', bare, 'main')
  await git(repo, 'worktree', 'add', '-b', 'work/two', folder)
  writeFileSync(join(folder, 'value.txt'), 'candidate\n'); await git(folder, 'commit', '-am', 'Candidate')
  const head = await git(folder, 'rev-parse', 'HEAD')
  await git(repo, 'remote', 'add', 'origin', 'https://alice@bitbucket.org/space/sample.git')
  await git(repo, 'update-ref', 'refs/remotes/origin/main', 'main')
  writeFileSync(statePath, JSON.stringify({ bare, requests: requestsPath, token: 'SYNTHETIC_TOKEN_ALICE_123', creates: 0, prepares: 0 }))
  const credentialHelper = join(root, 'credential.ts')
  writeFileSync(credentialHelper, `import{readFileSync,appendFileSync}from'node:fs';const s=JSON.parse(readFileSync(process.env.BITBUCKET_FIXTURE_STATE,'utf8'));const t=await Bun.stdin.text();appendFileSync(${JSON.stringify(join(root, 'credential-lookups'))},t);if(s.missingCredential)process.exit(1);if(s.malformedCredential){console.log('authtype=basic\\ncredential=unsupported');process.exit(0)}const user=t.match(/^username=(.+)$/m)?.[1]||'alice';console.error('private diagnostic '+s.token);console.log('protocol=https\\nhost=bitbucket.org\\nusername='+user+'\\npassword='+(user==='alice'?s.token:'SYNTHETIC_TOKEN_BOB_456'))`)
  const quote = (text: string) => `'${text.replaceAll("'", "'\"'\"'")}'`
  await git(repo, 'config', 'credential.helper', '')
  await git(repo, 'config', '--add', 'credential.helper', `!cd ${quote(join(root, 'user'))} && ${quote(process.execPath)} --no-env-file ${quote(credentialHelper)}`)
  await git(repo, 'config', 'credential.useHttpPath', 'true')
  let store = new CoreStore(join(root, 'home'))
  const task: CoreTask = { id: 'DEMO-2', name: 'Bitbucket candidate', desc: 'Publish a candidate', place: 'space', machine: remote ? 'remote-machine' : 'local-machine', repo, folder,
    branch: 'work/two', base: 'main', chat: 'DEMO-2/Agent', kind: 'codex', workflow: 'working', status: 'work', mergePolicy: 'ask',
    review: { on: false, kind: 'codex', rounds: 3, mustFix: 'major' }, age: 'now', created: '2026-11-05T00:00:00Z', on: 'test', state: 'Working' }
  store.set('task', task.id, task)
  const grant = { id: 'fixture-grant', session: 'fixture-launch', chat: 'space', machine: task.machine, actions: [] } as unknown as Grant
  const route: BitbucketFixture['route'] = { epoch: 1, on: remote ? 'fixture-remote' : undefined, disconnected: false }
  const calls: BitbucketFixture['calls'] = [], outputs: string[] = []
  const core = { current: { connected: true, epoch: 1, terminals: new Map() }, call: async (method: string, params: Record<string, any>) => {
    if (method !== 'machine.exec') return {}
    const argv: string[] = params.argv
    calls.push({ argv: [...argv], on: params.on, cwd: params.cwd })
    let actual = [...argv]
    const input = params.input && Buffer.from(params.input, 'base64')
    let operation: { kind: string } | undefined
    if (argv.at(-1)?.endsWith('/helper/core-bitbucket.ts')) {
      operation = JSON.parse(input!.toString()).operation
      // Only the test's core protocol double injects the closed fake HTTP owner.
      actual = [argv[0], '--no-env-file', '--preload', join(import.meta.dir, 'fixtures/bitbucket-fetch.ts'), argv.at(-1)!]
    }
    if (argv[0] === 'git' && ['push', 'ls-remote'].includes(argv[1])) actual = argv.map(arg => arg === 'origin' ? bare : arg)
    const stdout = await runChild(actual, { cwd: params.cwd, input, env })
    if (operation) outputs.push(stdout.toString())
    const state = JSON.parse(readFileSync(statePath, 'utf8'))
    if (operation?.kind === 'create' && state.loseCreateReply) throw Error('Fixture lost the core reply')
    return { stdout: stdout.toString('base64'), stderr: '', code: 0, timed_out: false, truncated: false }
  } } as unknown as CoreSession
  const files = new CoreFiles(core, async () => { await route.before?.(); if (route.disconnected) throw Error('Fixture disconnected'); return route.on })
  const source = { store, files, core, config: { home: store.home }, connected: () => true, machineConnected: () => !route.disconnected,
    forgeExecutionBinding: () => { if (route.disconnected) throw Error('Fixture disconnected'); return JSON.stringify([route.epoch, route.on]) },
    agents: { all: () => [], get: (chat: string) => chat === grant.chat ? { chat, launch: grant.session, grant: grant.id, role: 'coordinator', machine: task.machine, space: task.place, kind: 'codex' } : undefined,
      terminal: () => undefined, browserRuntime: async () => ({ bun: process.execPath, root: join(import.meta.dir, '..') }) },
    settings: { get: () => 'off' }, space: () => ({ id: 'space', name: 'Fixture', machine: task.machine, folder: repo, mode: 'regular', base: 'main' }),
    browsers: { close: async () => {} }, status: () => 'idle', emit: () => {}, post: (chat: string, message: Message) => store.set(`message:${chat}`, message.id, message),
    taskRow: () => {}, saveAndDeliver: (_chat: string, _id: string, _text: string, save: () => void) => save() } as unknown as CoreSource
  let tasks = new CoreTasks(source)
  const fixture: BitbucketFixture = { get tasks() { return tasks }, source, task, grant, root, repo, folder, bare, head, calls, outputs, route, git,
    state: () => JSON.parse(readFileSync(statePath, 'utf8')), update: patch => writeFileSync(statePath, JSON.stringify({ ...fixture.state(), ...patch })),
    requests: () => readFileSync(requestsPath, 'utf8').split('\n').filter(Boolean).map(row => JSON.parse(row)),
    reopen: () => { store.close(); store = new CoreStore(join(root, 'home')); Object.assign(source, { store }); tasks = new CoreTasks(source) } }
  try { await run(fixture) }
  finally { store.close(); rmSync(root, { recursive: true, force: true }) }
}
