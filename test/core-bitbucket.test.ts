import { expect, test } from 'bun:test'
import { existsSync, readFileSync, realpathSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import { CoreFiles } from '../server/core/files.ts'
import type { CoreSession } from '../server/core/session.ts'
import { Refusal } from '../server/core/client.ts'
import { CorePilotRepositories } from '../server/core/pilot-repositories.ts'
import type { CoreTask } from '../server/core/tasks.ts'
import type { Message, ForgePrRecord } from '../shared/types.ts'
import { withBitbucket } from './bitbucket-fixture.ts'

// Independent oracle: these provider-qualified identities are test-owned literals.
const expectedPr: ForgePrRecord = { provider: 'bitbucket', host: 'bitbucket.org', repository: 'space/sample', number: 37, url: 'https://bitbucket.org/space/sample/pull-requests/37' }

test('Bitbucket public real insteadOf rewrite after admission cannot redirect the frozen push', async () => {
  for (const remote of [false, true]) await withBitbucket(async f => {
    const foreignBefore = await f.git(f.repo, '--git-dir', f.foreignBare, 'show-ref')
    let changed = false
    f.route.before = async () => {
      if (!changed && f.calls.at(-1)?.argv.at(-1) === 'refs/heads/work/two^{commit}') {
        changed = true
        await f.git(f.repo, 'config', `url.${f.foreignBare}.insteadOf`, 'https://alice@bitbucket.org/space/sample.git')
        expect(await f.git(f.folder, 'remote', 'get-url', '--push', 'origin')).toBe(f.foreignBare)
      }
    }
    await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('changed')
    expect(changed).toBe(true)
    expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
    expect(await f.git(f.repo, '--git-dir', f.foreignBare, 'show-ref')).toBe(foreignBefore)
    expect(f.gitTransports()).toEqual([{ url: 'https://alice@bitbucket.org/space/sample.git', repository: f.bare, username: 'alice' }])
    expect(f.tasks.get(f.task.id)?.pushedHead).toBe(f.head)
    expect(f.state().creates).toBe(0)
    expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
  }, remote)
}, 30000)

test('Bitbucket public real pushInsteadOf rewrite after admission cannot redirect the frozen push', () => withBitbucket(async f => {
  const foreignBefore = await f.git(f.repo, '--git-dir', f.foreignBare, 'show-ref')
  let changed = false
  f.route.before = async () => {
    if (!changed && f.calls.at(-1)?.argv.at(-1) === 'refs/heads/work/two^{commit}') {
      changed = true
      await f.git(f.repo, 'config', `url.${f.foreignBare}.pushInsteadOf`, 'https://alice@bitbucket.org/space/sample.git')
      expect(await f.git(f.folder, 'remote', 'get-url', '--push', 'origin')).toBe(f.foreignBare)
      expect(await f.git(f.folder, 'remote', 'get-url', 'origin')).toBe('https://alice@bitbucket.org/space/sample.git')
    }
  }
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('changed')
  expect(changed).toBe(true)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  expect(await f.git(f.repo, '--git-dir', f.foreignBare, 'show-ref')).toBe(foreignBefore)
  expect(f.gitTransports()).toEqual([{ url: 'https://alice@bitbucket.org/space/sample.git', repository: f.bare, username: 'alice' }])
  expect(f.tasks.get(f.task.id)?.pushedHead).toBe(f.head)
  expect(f.state().creates).toBe(0)
}), 30000)

test('Bitbucket public real insteadOf rewrite after a lost push reply cannot redirect reconciliation', () => withBitbucket(async f => {
  const foreignBefore = await f.git(f.repo, '--git-dir', f.foreignBare, 'show-ref')
  f.update({ losePushReply: true, rewriteAfterPush: true })
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('changed')
  expect(await f.git(f.folder, 'remote', 'get-url', 'origin')).toBe(f.foreignBare)
  expect(f.tasks.get(f.task.id)?.pushedHead).toBe(f.head)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  expect(await f.git(f.repo, '--git-dir', f.foreignBare, 'show-ref')).toBe(foreignBefore)
  expect(f.gitTransports()).toEqual([
    { url: 'https://alice@bitbucket.org/space/sample.git', repository: f.bare, username: 'alice' },
    { url: 'https://alice@bitbucket.org/space/sample.git', repository: f.bare, username: 'alice' },
  ])
  expect(f.state().creates).toBe(0)
  expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
}), 30000)

test('Bitbucket public delayed pushurl change cannot redirect an admitted push to a foreign repository', () => withBitbucket(async f => {
  const foreignBefore = await f.git(f.repo, '--git-dir', f.foreignBare, 'show-ref')
  let changed = false
  f.route.before = async () => {
    // Hold the final CoreFiles route lookup after Git has read the candidate,
    // before the already-constructed push command is dispatched.
    if (!changed && f.calls.at(-1)?.argv.at(-1) === 'refs/heads/work/two^{commit}') {
      changed = true
      await f.git(f.repo, 'remote', 'set-url', '--push', 'origin', 'https://alice@bitbucket.org/other/foreign.git')
    }
  }
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('changed')
  expect(changed).toBe(true)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  expect(await f.git(f.repo, '--git-dir', f.foreignBare, 'show-ref')).toBe(foreignBefore)
  expect(f.tasks.get(f.task.id)?.pushedHead).toBe(f.head)
  expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
  expect(f.state().creates).toBe(0)
  expect(f.source.store.all('forge-publication')).toHaveLength(0)
}))

test('Bitbucket public lost Git push reply reconciles the admitted destination after origin changes', () => withBitbucket(async f => {
  const foreignBefore = await f.git(f.repo, '--git-dir', f.foreignBare, 'show-ref')
  f.update({ losePushReply: true })
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('changed')
  expect(f.tasks.get(f.task.id)?.pushedHead).toBe(f.head)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  expect(await f.git(f.repo, '--git-dir', f.foreignBare, 'show-ref')).toBe(foreignBefore)
  expect(f.calls.filter(call => call.operation === 'push' || call.argv[1] === 'push')).toHaveLength(1)
  expect(f.calls.filter(call => call.operation === 'observe' || call.argv[1] === 'ls-remote')).toHaveLength(1)
  expect(f.state().creates).toBe(0)
  expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
}))

test('Bitbucket public draft publication and readiness preserve independently expected payloads and provider state', () => withBitbucket(async f => {
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
  const posts = f.requests().filter(request => request.method === 'POST')
  expect(posts).toHaveLength(1)
  expect(posts[0].body).toEqual({ title: 'DEMO-2: Bitbucket candidate', description: 'Publish a candidate', draft: true, close_source_branch: false,
    source: { branch: { name: 'work/two' }, commit: { hash: f.head }, repository: { full_name: 'space/sample' } },
    destination: { branch: { name: 'main' }, repository: { full_name: 'space/sample' } } })
  expect(f.state().pr).toMatchObject({ draft: true, close_source_branch: false, description: 'Publish a candidate' })
  f.reopen()
  expect((await f.tasks.forge.presentation({ machine: f.task.machine, folder: f.folder }, 'work/two', expectedPr)).pr?.state).toBe('draft')
  await f.tasks.ready(f.grant, f.task.id, '  Ready candidate  ', 'Build passed')
  const puts = f.requests().filter(request => request.method === 'PUT')
  expect(puts).toHaveLength(1)
  expect(puts[0].body).toEqual({ description: 'Ready candidate\n\nFacts: Build passed', draft: false })
  expect(f.state().pr).toMatchObject({ draft: false, close_source_branch: false, description: 'Ready candidate\n\nFacts: Build passed' })
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  f.reopen()
  expect(f.tasks.get(f.task.id)).toMatchObject({ workflow: 'ready', readyHead: f.head, readyPr: expectedPr })
  expect((await f.tasks.forge.presentation({ machine: f.task.machine, folder: f.folder }, 'work/two', expectedPr)).pr?.state).toBe('open')
}))

test('Bitbucket public two-machine race keeps one repository source destination publication owner', () => withBitbucket(async f => {
  const second = await f.secondMachine()
  expect(second.task.machine).toBe('second-machine')
  expect(await f.git(second.task.folder, 'rev-parse', 'HEAD')).toBe(f.head)
  let release!: () => void, arrived!: () => void
  const held = new Promise<void>(resolve => { release = resolve }), entered = new Promise<void>(resolve => { arrived = resolve })
  const runtime = f.source.agents.browserRuntime.bind(f.source.agents)
  f.source.agents.browserRuntime = async machine => {
    // First owner has completed empty discovery, but not dispatched create.
    if (machine === f.task.machine && f.calls.at(-1)?.operation === 'find') { arrived(); await held }
    return runtime(machine)
  }
  const first = f.tasks.pr(f.grant, f.task.id)
  await entered
  try {
    await expect(f.tasks.pr(second.grant, second.task.id)).rejects.toThrow('Another task is publishing')
  } finally {
    release()
    // A RED assertion must not tear down the provider/store while the original
    // publisher is still using them. Settle it before propagating that failure.
    await first.catch(() => {})
  }
  expect(await first).toEqual(expectedPr)
  expect(f.state().creates).toBe(1)
  expect(f.requests().filter(request => request.method === 'POST')).toHaveLength(1)
  const original = f.source.store.all<Record<string, any>>('forge-publication')
  expect(original).toHaveLength(1)
  expect(original[0]).toMatchObject({ task: 'DEMO-2', machine: 'local-machine', binding: '[1,null]', state: 'confirmed', pr: expectedPr })
  f.reopen()
  await expect(f.tasks.pr(second.grant, second.task.id)).rejects.toThrow('another task')
  expect(f.source.store.all<Record<string, any>>('forge-publication')[0].id).toBe(original[0].id)
  expect(f.state().creates).toBe(1)
}), 30000)

test('Bitbucket public publication preserves a legacy uncertain machine-keyed record across another host and reopen', () => withBitbucket(async f => {
  const second = await f.secondMachine()
  f.update({ loseCreateReply: true, hidePr: true })
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
  const record = f.source.store.all<Record<string, any>>('forge-publication')[0]
  // Independent persisted-format fixtures: old key includes the host, new key does not.
  const identity = { provider: 'bitbucket', host: 'bitbucket.org', repository: 'space/sample' }
  const digest = (value: unknown) => createHash('sha256').update(JSON.stringify(value)).digest('hex')
  const legacy = digest(['local-machine', identity, 'work/two', 'main'])
  f.source.store.delete('forge-publication', digest([identity, 'work/two', 'main']))
  delete record.binding; delete record.on
  f.source.store.set('forge-publication', legacy, record)
  f.reopen()
  const requests = f.requests().length
  await expect(f.tasks.pr(second.grant, second.task.id)).rejects.toThrow('another task')
  expect(f.requests()).toHaveLength(requests)
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
  expect(f.source.store.get('forge-publication', legacy)).toEqual(record)
  expect(f.state().creates).toBe(1)
  f.update({ hidePr: false })
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
  expect(f.source.store.all('forge-publication')).toHaveLength(1)
  expect(f.source.store.get<Record<string, any>>('forge-publication', legacy)).toMatchObject({ id: record.id, state: 'confirmed', pr: expectedPr })
}))

test('Bitbucket public publication reconciles a lost reply into one qualified draft PR on regular local and remote routes', async () => {
  for (const remote of [false, true]) await withBitbucket(async f => {
    f.update({ loseCreateReply: true })
    expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
    expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
    f.reopen()
    expect(f.tasks.get(f.task.id)?.pr).toEqual(expectedPr)
    const publication = f.source.store.all<Record<string, any>>('forge-publication')
    expect(publication).toHaveLength(1)
    expect(publication[0]).toMatchObject({ task: 'DEMO-2', head: f.head, state: 'confirmed', pr: expectedPr })
    expect(f.state().creates).toBe(1)
    expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
    expect(await f.tasks.forge.presentation({ machine: f.task.machine, folder: f.folder }, 'work/two', f.tasks.get(f.task.id)?.pr)).toMatchObject({ pr: {
      number: 37, url: 'https://bitbucket.org/space/sample/pull-requests/37', state: 'draft', checks: [{ name: 'Build', state: 'pass', url: 'https://ci.example.invalid/build/9' }],
    } })
    const helpers = f.calls.filter(call => call.argv.at(-1)?.endsWith('/helper/core-bitbucket.ts'))
    expect(helpers.length).toBeGreaterThan(0)
    expect(helpers.every(call => call.on === (remote ? 'fixture-remote' : undefined) && call.cwd?.endsWith('/helper') && call.argv.includes('--no-env-file'))).toBe(true)
    expect(f.calls.some(call => ['bb', 'gh', 'hc'].includes(call.argv[0]))).toBe(false)
  }, remote)
}, 30000)

test('Bitbucket uncertain publication survives reopened state and never treats an empty lookup as permission to create again', () => withBitbucket(async f => {
  f.update({ loseCreateReply: true, hidePr: true })
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
  const before = f.source.store.all<Record<string, any>>('forge-publication')
  expect(before).toHaveLength(1); expect(before[0]).toMatchObject({ state: 'uncertain', head: f.head, task: 'DEMO-2' })
  expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
  f.reopen()
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
  expect(f.source.store.all<Record<string, any>>('forge-publication')[0].id).toBe(before[0].id)
  expect(f.state().creates).toBe(1)
  f.update({ hidePr: false })
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
  expect(f.state().creates).toBe(1)
}))

test('Bitbucket changed candidate cannot replace an uncertain publication operation', () => withBitbucket(async f => {
  f.update({ loseCreateReply: true, hidePr: true })
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
  const record = f.source.store.all<Record<string, any>>('forge-publication')[0]
  writeFileSync(join(f.folder, 'value.txt'), 'later\n'); await f.git(f.folder, 'commit', '-am', 'Later')
  const pushes = f.calls.filter(call => call.operation === 'push' || call.argv[1] === 'push').length
  f.reopen()
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
  expect(f.source.store.all<Record<string, any>>('forge-publication')[0].id).toBe(record.id)
  expect(f.calls.filter(call => call.operation === 'push' || call.argv[1] === 'push')).toHaveLength(pushes)
  expect(f.state().creates).toBe(1)
}))

test('Bitbucket concurrent task records share publication ownership for one repository source and destination', () => withBitbucket(async f => {
  const second: CoreTask = { ...f.task, id: 'DEMO-3', chat: 'DEMO-3/Agent' }; f.source.store.set('task', second.id, second)
  let release!: () => void, arrived!: () => void
  const held = new Promise<void>(resolve => { release = resolve }), entered = new Promise<void>(resolve => { arrived = resolve })
  const runtime = f.source.agents.browserRuntime.bind(f.source.agents)
  f.source.agents.browserRuntime = async machine => { arrived(); await held; return runtime(machine) }
  const first = f.tasks.pr(f.grant, f.task.id)
  await entered
  try { await expect(f.tasks.pr(f.grant, second.id)).rejects.toThrow('Another task is publishing') } finally { release() }
  expect(await first).toEqual(expectedPr)
  await expect(f.tasks.pr(f.grant, second.id)).rejects.toThrow('another task')
  expect(f.state().creates).toBe(1)
}))

test('Bitbucket missing malformed and rejected host credentials refuse before a branch push without an account fallback', async () => {
  for (const failure of ['missingCredential', 'malformedCredential', 'rejectCredential']) await withBitbucket(async f => {
    f.update({ [failure]: true })
    await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow(/credential|permission|REST/i)
    expect(f.calls.filter(call => call.operation === 'push' || call.argv[1] === 'push')).toHaveLength(0)
    expect(f.state().creates).toBe(0)
    expect(f.source.store.all('forge-publication')).toHaveLength(0)
    expect(f.outputs.join('')).not.toContain('SYNTHETIC_TOKEN_ALICE_123')
    expect(f.requests().every(request => request.authorization === 'Bearer SYNTHETIC_TOKEN_ALICE_123')).toBe(true)
  })
})

test('Bitbucket uses host Git account selection and keeps token and provider diagnostic text out of public records', () => withBitbucket(async f => {
  f.update({ providerTitle: 'Review Bearer SYNTHETIC_TOKEN_ALICE_123' })
  await f.tasks.pr(f.grant, f.task.id)
  const panel = await f.tasks.forge.presentation({ machine: f.task.machine, folder: f.folder }, 'work/two')
  expect(panel).toMatchObject({ pr: { title: 'Review [redacted]', url: 'https://bitbucket.org/space/sample/pull-requests/37' } })
  expect(readFileSync(join(f.root, 'credential-lookups'), 'utf8')).toContain('username=alice\n')
  expect(f.requests().length).toBeGreaterThan(0)
  expect(f.requests().every(request => request.authorization === 'Bearer SYNTHETIC_TOKEN_ALICE_123')).toBe(true)
  expect(JSON.stringify([f.source.store.all('task'), f.source.store.all('forge-publication'), panel, f.outputs])).not.toContain('SYNTHETIC_TOKEN_ALICE_123')
  await f.git(f.repo, 'remote', 'set-url', 'origin', 'https://bob@bitbucket.org/space/sample.git')
  f.update({ token: 'SYNTHETIC_TOKEN_BOB_456' })
  expect((await f.tasks.forge.presentation({ machine: f.task.machine, folder: f.folder }, 'work/two')).pr?.url).toBe('https://bitbucket.org/space/sample/pull-requests/37')
  expect(readFileSync(join(f.root, 'credential-lookups'), 'utf8')).toContain('username=bob\n')
  expect(f.requests().at(-1)?.authorization).toBe('Bearer SYNTHETIC_TOKEN_BOB_456')
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('credential context')
}))

test('Bitbucket checks retain an exact commit and distinguish missing pending failed passed and incomplete observations', () => withBitbucket(async f => {
  await f.tasks.pr(f.grant, f.task.id)
  const forge = await f.tasks.forge.require({ machine: f.task.machine, folder: f.folder })
  const cases = [
    { checks: [], state: 'none', complete: true, green: false, count: 0 },
    { checks: [{ type: 'build', key: 'build', name: 'Build', state: 'INPROGRESS', links: { commit: { href: `https://api.bitbucket.org/2.0/repositories/space/sample/commit/${f.head}` } } }], state: 'running', complete: true, green: false, count: 1 },
    { checks: [{ type: 'build', key: 'build', name: 'Build', state: 'FAILED', links: { commit: { href: `https://api.bitbucket.org/2.0/repositories/space/sample/commit/${f.head}` } } }], state: 'failed', complete: true, green: false, count: 1 },
    { checks: [{ type: 'build', key: 'build', name: 'Build', state: 'SUCCESSFUL', links: { commit: { href: `https://api.bitbucket.org/2.0/repositories/space/sample/commit/${f.head}` } } }], state: 'passed', complete: true, green: true, count: 1 },
    { checks: [{ type: 'build', key: 'build', name: 'Build', state: 'SUCCESSFUL', links: { commit: { href: `https://api.bitbucket.org/2.0/repositories/space/sample/commit/${'b'.repeat(40)}` } } }], state: 'unknown', complete: false, green: false, count: 0 },
  ]
  for (const row of cases) {
    f.update({ checks: row.checks })
    const pr = await forge.read('work/two', true, f.tasks.get(f.task.id)?.pr)
    expect(pr.checks).toMatchObject({ head: f.head, complete: row.complete, green: row.green, summary: { state: row.state } })
    expect(pr.checks?.items).toHaveLength(row.count)
  }
  f.update({ statusMissing: true })
  expect((await forge.read('work/two')).checks).toMatchObject({ complete: false, green: false, summary: { state: 'unknown' } })
}))

test('Bitbucket complete check pagination includes a later failed check; foreign redirects and repeated pages remain incomplete', async () => {
  await withBitbucket(async f => {
    await f.tasks.pr(f.grant, f.task.id)
    const forge = await f.tasks.forge.require({ machine: f.task.machine, folder: f.folder })
    f.update({ statusNext: 'second', checks: [{ type: 'build', key: 'build', name: 'Build', state: 'SUCCESSFUL', links: { commit: { href: `https://api.bitbucket.org/2.0/repositories/space/sample/commit/${f.head}` } } }], secondChecks: [{ type: 'build', key: 'lint', name: 'Lint', state: 'FAILED', links: { commit: { href: `https://api.bitbucket.org/2.0/repositories/space/sample/commit/${f.head}` } } }] })
    const complete = await forge.read('work/two')
    expect(complete.checks).toMatchObject({ complete: true, green: false, summary: { state: 'failed' } })
    expect(complete.checks?.items.map(item => ({ name: item.name, state: item.state }))).toEqual([{ name: 'Build', state: 'pass' }, { name: 'Lint', state: 'fail' }])
    for (const patch of [
      { statusNext: 'https://foreign.invalid/stolen' },
      { statusNext: 'https://api.bitbucket.org/2.0/repositories/foreign/repo/commit/' + f.head + '/statuses?page=2' },
      { statusNext: 'same' },
      { statusNext: undefined, statusRedirect: true },
    ]) {
      f.update(patch)
      const pr = await forge.read('work/two')
      expect(pr.checks).toMatchObject({ head: f.head, complete: false, green: false, summary: { state: 'unknown' } })
      expect(f.requests().every(request => new URL(request.url).origin === 'https://api.bitbucket.org')).toBe(true)
    }
  })
})

test('Bitbucket readiness rejects a changed PR identity or candidate before updating readiness', async () => {
  for (const change of [
    { head: 'b'.repeat(40) }, { source: 'work/foreign' }, { base: 'other' }, { url: 'https://bitbucket.org/foreign/repo/pull-requests/37' }, { repository: 'foreign/repo' },
  ]) await withBitbucket(async f => {
    await f.tasks.pr(f.grant, f.task.id)
    const pr = f.state().pr
    if (change.head) f.update({ overrideHead: change.head })
    if (change.source) pr.source.branch.name = change.source
    if (change.base) pr.destination.branch.name = change.base
    if (change.url) pr.links.html.href = change.url
    if (change.repository) pr.destination.repository.full_name = change.repository
    f.update({ pr })
    await expect(f.tasks.ready(f.grant, f.task.id, 'Ready candidate')).rejects.toThrow()
    expect(f.tasks.get(f.task.id)?.workflow).toBe('working')
    expect(f.state().prepares).toBe(0)
  })
}, 30000)

test('Bitbucket readiness evidence is candidate-bound and an advanced local candidate invalidates the existing merge card', () => withBitbucket(async f => {
  await f.tasks.pr(f.grant, f.task.id)
  await f.tasks.ready(f.grant, f.task.id, 'Ready candidate')
  const ready = f.tasks.get(f.task.id)!
  const message = f.source.store.get<Message>(`message:${f.task.chat}`, ready.mergeQuestion!)!
  expect(message.question?.evidence?.checks).toEqual({ state: 'passed', text: '0 failed, 0 running, 1 passed' })
  expect(ready).toMatchObject({ readyHead: f.head, readyBase: 'main', readyPr: expectedPr })
  writeFileSync(join(f.folder, 'value.txt'), 'later\n'); await f.git(f.folder, 'commit', '-am', 'Later candidate')
  await expect(f.tasks.answer(ready.mergeQuestion!, 0, f.task.chat)).rejects.toThrow('changed after')
  expect(f.tasks.get(f.task.id)?.approvedHead).toBeUndefined()
}))

test('Bitbucket incomplete checks refuse readiness and the panel preserves its qualified PR link', () => withBitbucket(async f => {
  await f.tasks.pr(f.grant, f.task.id)
  f.update({ statusMissing: true })
  await expect(f.tasks.ready(f.grant, f.task.id, 'Ready candidate')).rejects.toThrow('incomplete')
  expect(f.tasks.get(f.task.id)?.workflow).toBe('working')
  expect(await f.tasks.forge.presentation({ machine: f.task.machine, folder: f.folder }, 'work/two')).toMatchObject({ pr: { url: 'https://bitbucket.org/space/sample/pull-requests/37', checksError: 'Bitbucket checks are unavailable or incomplete.' } })
}))

test('Bitbucket refuses unsupported native merge and feedback capabilities without a helper or HTTP request', () => withBitbucket(async f => {
  const forge = await f.tasks.forge.require({ machine: f.task.machine, folder: f.folder })
  const before = f.calls.length
  await expect(forge.integrate({} as never, f.head)).rejects.toThrow('approved source head')
  await expect(forge.comments(expectedPr as never)).rejects.toThrow('outside')
  await expect(forge.observeBase('main', {})).rejects.toThrow('outside')
  expect(f.calls).toHaveLength(before)
  expect(f.requests()).toHaveLength(0)
}))

test('Bitbucket helper ignores hostile project dotenv and Bun preload configuration', () => withBitbucket(async f => {
  const marker = join(f.root, 'hostile-executed'), attack = join(f.folder, 'preload.ts')
  writeFileSync(attack, `import{writeFileSync}from'node:fs';writeFileSync(${JSON.stringify(marker)},'executed')`)
  writeFileSync(join(f.folder, 'bunfig.toml'), `preload = [${JSON.stringify(attack)}]\n`)
  writeFileSync(join(f.folder, '.env'), `BUN_OPTIONS=--preload=${attack}\nBITBUCKET_FIXTURE_STATE=/foreign\n`)
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
  expect(existsSync(marker)).toBe(false)
  expect(f.gitStartups()).toEqual([{ cwd: realpathSync(join(f.root, 'user')), gitCwd: realpathSync(f.folder) }])
  expect(f.state().creates).toBe(1)
}))

test('Bitbucket admission refuses task and route changes while preparation is awaited before push or HTTP dispatch', async () => {
  for (const change of ['task', 'epoch', 'disconnected']) await withBitbucket(async f => {
    const runtime = f.source.agents.browserRuntime.bind(f.source.agents)
    f.source.agents.browserRuntime = async machine => {
      if (change === 'task') f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id), base: 'foreign' })
      if (change === 'epoch') f.route.epoch++
      if (change === 'disconnected') f.route.disconnected = true
      return runtime(machine)
    }
    await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow()
    expect(f.requests()).toHaveLength(0)
    expect(f.calls.filter(call => call.operation === 'push' || call.argv[1] === 'push')).toHaveLength(0)
    expect(f.source.store.all('forge-publication')).toHaveLength(0)
  })
})

test('core final exec admission runs after delayed route resolution and before the synchronous core call', async () => {
  let release!: () => void, stale = false, calls = 0
  const route = new Promise<string>(resolve => { release = () => resolve('old-route') })
  const files = new CoreFiles({ call: async () => { calls++; return { stdout: '', stderr: '', code: 0 } } } as unknown as CoreSession, () => route)
  const pending = files.exec('machine', ['fixed-helper'], undefined, undefined, 30, () => { if (stale) throw new Refusal('stale admission') })
  stale = true; release()
  await expect(pending).rejects.toThrow('stale admission')
  expect(calls).toBe(0)
})

test('Bitbucket create admission rejects a changed task or replaced core route after awaited route resolution without recording a dispatch', async () => {
  for (const change of ['task', 'route']) await withBitbucket(async f => {
    let entered!: () => void, release!: () => void
    const arrived = new Promise<void>(resolve => { entered = resolve }), gate = new Promise<void>(resolve => { release = resolve })
    const runtime = f.source.agents.browserRuntime.bind(f.source.agents)
    f.source.agents.browserRuntime = async machine => {
      if (f.calls.at(-1)?.operation === 'find') f.route.before = async () => { entered(); await gate }
      return runtime(machine)
    }
    const pending = f.tasks.pr(f.grant, f.task.id)
    await arrived
    if (change === 'task') f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id), base: 'foreign' })
    else { f.route.on = 'replacement'; f.route.epoch++ }
    release()
    await expect(pending).rejects.toThrow('changed before')
    expect(f.state().creates).toBe(0)
    expect(f.requests().filter(request => request.method !== 'GET')).toHaveLength(0)
    expect(f.source.store.all('forge-publication')).toHaveLength(0)
  })
})

test('Bitbucket retained containment refuses its REST helper before publication or provider access', () => withBitbucket(async f => {
  new CorePilotRepositories(f.source.store).remember(f.task.machine, f.repo, [f.folder])
  // Origin admission uses an existing checked runtime without provisioning one.
  const runtime = f.source.agents.browserRuntime.bind(f.source.agents)
  let bitbucketRuntime = 0
  f.source.agents.browserRuntime = async (machine, provision) => { if (provision !== false) bitbucketRuntime++; return runtime(machine, provision) }
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('Contained Bitbucket')
  expect(f.calls.some(call => call.argv.at(-1)?.endsWith('core-bitbucket.ts') || call.operation === 'push' || call.argv[1] === 'push')).toBe(false)
  expect(f.requests()).toHaveLength(0)
  expect(f.state().creates).toBe(0)
  expect(bitbucketRuntime).toBe(0)
}))

test('Bitbucket REST read compatibility does not imply PR write permission or permit a blind create retry', () => withBitbucket(async f => {
  f.update({ rejectCreate: true })
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('permission')
  expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
  expect(f.state().creates).toBe(0)
  expect(f.requests().filter(request => request.method === 'POST')).toHaveLength(1)
  const operation = f.source.store.all<Record<string, any>>('forge-publication')[0]
  expect(operation).toMatchObject({ state: 'uncertain', head: f.head })
  f.reopen()
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
  expect(f.requests().filter(request => request.method === 'POST')).toHaveLength(1)
  expect(f.source.store.all<Record<string, any>>('forge-publication')[0].id).toBe(operation.id)
}))

test('Bitbucket response and page limits cannot become a complete check observation', async () => {
  for (const limit of ['statusOversize', 'statusEndless']) await withBitbucket(async f => {
    await f.tasks.pr(f.grant, f.task.id); f.update({ [limit]: true })
    const forge = await f.tasks.forge.require({ machine: f.task.machine, folder: f.folder })
    const pr = await forge.read('work/two')
    expect(pr.checks).toMatchObject({ head: f.head, complete: false, green: false, summary: { state: 'unknown' } })
    expect(f.requests().filter(request => request.url.includes('/statuses'))).toHaveLength(limit === 'statusEndless' ? 20 : 1)
  })
})

test('Bitbucket public native merge refusal preserves task readiness without a lifecycle or provider write', () => withBitbucket(async f => {
  await f.tasks.pr(f.grant, f.task.id); await f.tasks.ready(f.grant, f.task.id, 'Ready candidate')
  await f.tasks.answer(f.tasks.get(f.task.id)!.mergeQuestion!, 0, f.task.chat)
  const requests = f.requests().length
  const merge = f.tasks.merge(f.grant, f.task.id)
  await expect(merge).rejects.toThrow('expected-source-head guarantee')
  await expect(merge).rejects.toThrow('no merge or lifecycle transition')
  expect(f.tasks.get(f.task.id)?.workflow).toBe('ready')
  expect(f.requests()).toHaveLength(requests)
}))

test('Bitbucket public official real and minimal status responses bind checks and readiness to the requested commit', async () => {
  for (const shape of ['real', 'minimal', 'optional-links']) await withBitbucket(async f => {
    await f.tasks.pr(f.grant, f.task.id)
    // Independent literals from the combined official schema, not the parser.
    const status = shape === 'real'
      ? { type: 'build', key: 'vendor-build', state: 'SUCCESSFUL', name: 'Official build', description: 'Passed', refname: 'work/two', created_on: '2026-11-05T01:00:00Z', updated_on: '2026-11-05T01:00:01+00:00', url: 'https://ci.example.invalid/official/1', links: { commit: { href: `https://api.bitbucket.org/2.0/repositories/space/sample/commit/${f.head}` }, self: { href: `https://api.bitbucket.org/2.0/repositories/space/sample/commit/${f.head}/statuses/build/vendor-build` } } }
      : { type: 'build', key: 'vendor-minimal', state: 'SUCCESSFUL', ...(shape === 'optional-links' ? { links: { commit: { name: 'Commit' }, self: {} } } : {}) }
    f.update({ checks: [status], ...(shape === 'real' ? { statusPage: { size: 1, page: 1, pagelen: 100 } } : {}) })
    const pr = await (await f.tasks.forge.require({ machine: f.task.machine, folder: f.folder })).read('work/two', true, expectedPr)
    expect(pr.checks).toMatchObject({ head: f.head, complete: true, green: true, summary: { state: 'passed' } })
    expect(pr.checks?.items).toEqual(shape === 'real' ? [{ name: 'Official build', state: 'pass', url: 'https://ci.example.invalid/official/1' }] : [{ name: 'vendor-minimal', state: 'pass' }])
    expect(f.requests().filter(request => request.url.includes('/statuses')).map(request => new URL(request.url).pathname)).toEqual([`/2.0/repositories/space/sample/commit/${f.head}/statuses`])
    await f.tasks.ready(f.grant, f.task.id, 'Official candidate')
    expect(f.tasks.get(f.task.id)).toMatchObject({ workflow: 'ready', readyHead: f.head, readyPr: expectedPr })
    const ready = f.tasks.get(f.task.id)!
    expect(f.source.store.get<Message>(`message:${f.task.chat}`, ready.mergeQuestion!)?.question?.evidence?.checks).toMatchObject({ state: 'passed' })
    expect(f.state().prepares).toBe(1)
  })
})

test('Bitbucket public malformed status fields and mismatched or foreign commit links refuse readiness', async () => {
  const invalid = [
    { key: 'build', state: 'SUCCESSFUL' }, { type: 'build', state: 'SUCCESSFUL' }, { type: 'build', key: 'build' },
    { type: 7 }, { name: 7 }, { url: 7 }, { created_on: 'not-a-date' }, { links: null },
    { links: { commit: { href: 7 } } }, { links: { commit: { href: 'not-a-uri' } } },
    { links: { commit: { href: 'https://api.bitbucket.org/2.0/repositories/space/sample/commit/' + 'b'.repeat(40) } } },
    { links: { commit: { href: 'https://api.bitbucket.org/2.0/repositories/foreign/repo/commit/' + 'b'.repeat(40) } } },
    { links: { commit: { href: 'https://foreign.invalid/stolen' } } }, { links: { commit: { extra: 'not-in-schema' } } },
  ]
  for (const patch of invalid) await withBitbucket(async f => {
    await f.tasks.pr(f.grant, f.task.id)
    const status = Object.keys(patch).length > 1 ? patch : { type: 'build', key: 'build', state: 'SUCCESSFUL', ...patch }
    f.update({ checks: [status] })
    const pr = await (await f.tasks.forge.require({ machine: f.task.machine, folder: f.folder })).read('work/two', true, expectedPr)
    expect(pr.checks).toMatchObject({ head: f.head, complete: false, green: false, items: [], summary: { state: 'unknown' } })
    await expect(f.tasks.ready(f.grant, f.task.id, 'Invalid candidate')).rejects.toThrow('incomplete')
    expect(f.tasks.get(f.task.id)?.workflow).toBe('working')
    expect(f.state().prepares).toBe(0)
    expect(f.requests().every(request => new URL(request.url).origin === 'https://api.bitbucket.org')).toBe(true)
  })
}, 30000)

test('Bitbucket public wrong candidate and incomplete pagination refuse readiness while empty evidence stays nongreen', async () => {
  for (const mode of ['wrong-head', 'pagination', 'truncated', 'empty']) await withBitbucket(async f => {
    await f.tasks.pr(f.grant, f.task.id)
    f.update(mode === 'wrong-head' ? { overrideHead: 'b'.repeat(40) } : mode === 'pagination' ? { statusNext: `https://api.bitbucket.org/2.0/repositories/space/sample/commit/${'b'.repeat(40)}/statuses?page=2` } : mode === 'truncated' ? { statusPage: { size: 2, page: 1, pagelen: 100 } } : { checks: [] })
    if (mode !== 'empty') {
      await expect(f.tasks.ready(f.grant, f.task.id, 'Invalid evidence')).rejects.toThrow(mode === 'wrong-head' ? 'exact commit' : 'incomplete')
      expect(f.tasks.get(f.task.id)?.workflow).toBe('working'); expect(f.state().prepares).toBe(0)
    } else {
      const pr = await (await f.tasks.forge.require({ machine: f.task.machine, folder: f.folder })).read('work/two', true, expectedPr)
      expect(pr.checks).toMatchObject({ head: f.head, complete: true, green: false, items: [], summary: { state: 'none' } })
      await f.tasks.ready(f.grant, f.task.id, 'No checks yet')
      const ready = f.tasks.get(f.task.id)!
      expect(f.source.store.get<Message>(`message:${f.task.chat}`, ready.mergeQuestion!)?.question?.evidence?.checks).toMatchObject({ state: 'none' })
      await f.tasks.answer(ready.mergeQuestion!, 0, f.task.chat)
      await expect(f.tasks.merge(f.grant, f.task.id)).rejects.toThrow('expected-source-head guarantee')
    }
  })
})

test('Bitbucket public confirmed publication continues across reopened state and a fresh core connection epoch', async () => {
  for (const remote of [false, true]) await withBitbucket(async f => {
    expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
    const original = f.source.store.all<Record<string, any>>('forge-publication')[0]
    f.reopen(); f.route.epoch++
    expect(f.source.core.current.epoch).toBe(2)
    expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
    expect(f.source.store.all('forge-publication')).toEqual([original])
    expect(f.requests().filter(request => request.method === 'POST')).toHaveLength(1)
    expect(f.state().creates).toBe(1)
  }, remote)
})

test('Bitbucket public uncertain legacy publication remains held then reconciles the original UUID after reconnect', async () => {
  for (const legacy of [false, true]) await withBitbucket(async f => {
    f.update({ hidePr: true, loseCreateReply: true })
    await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
    const original = f.source.store.all<Record<string, any>>('forge-publication')[0]
    if (legacy) {
      delete original.ownership
      const key = createHash('sha256').update(JSON.stringify([{ provider: 'bitbucket', host: 'bitbucket.org', repository: 'space/sample' }, 'work/two', 'main'])).digest('hex')
      f.source.store.set('forge-publication', key, original)
    }
    f.reopen(); f.route.epoch++
    await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
    expect(f.source.store.all('forge-publication')).toEqual([original])
    f.update({ hidePr: false }); f.reopen(); f.route.epoch++
    expect(f.source.core.current.epoch).toBe(3)
    expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
    expect(f.source.store.all('forge-publication')).toEqual([{ ...original, state: 'confirmed', pr: expectedPr }])
    expect(f.requests().filter(request => request.method === 'POST')).toHaveLength(1)
    expect(f.state().creates).toBe(1)
  }, true)
})

test('Bitbucket public reopened publication rejects changed host route and credential context without releasing its claim', async () => {
  for (const change of ['host', 'route', 'account']) await withBitbucket(async f => {
    f.update({ hidePr: true, loseCreateReply: true })
    await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
    const original = f.source.store.all('forge-publication'), requests = f.requests().length
    f.reopen(); f.route.epoch++
    if (change === 'host') f.route.host = 'foreign-host'
    if (change === 'route') f.route.on = 'foreign-route'
    if (change === 'account') await f.git(f.repo, 'remote', 'set-url', 'origin', 'https://bob@bitbucket.org/space/sample.git')
    await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('credential context')
    expect(f.source.store.all('forge-publication')).toEqual(original)
    expect(f.requests()).toHaveLength(requests); expect(f.state().creates).toBe(1)
  }, true)
})
