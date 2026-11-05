import { expect, test } from 'bun:test'
import { parseBitbucketRequest } from '../server/core/forge/bitbucket-protocol.ts'
import type { CoreTask } from '../server/core/tasks.ts'
import type { ForgePrRecord } from '../shared/types.ts'
import { withBitbucket } from './bitbucket-fixture.ts'

// Independent boundary and provider identity literals, not protocol constants.
const expectedPr: ForgePrRecord = { provider: 'bitbucket', host: 'bitbucket.org', repository: 'space/sample', number: 37, url: 'https://bitbucket.org/space/sample/pull-requests/37' }

test('Bitbucket public complete payload preflight refuses oversized brief before effects and recovers after reopen', () => withBitbucket(async f => {
  const refs = await f.git(f.repo, '--git-dir', f.bare, 'show-ref')
  f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id)!, desc: 'b'.repeat(33000) })
  const failure = await f.tasks.pr(f.grant, f.task.id).then(() => undefined, (error: unknown) => error)
  // Actual remote history and independent persisted readers support no effects.
  expect(await f.git(f.repo, '--git-dir', f.bare, 'show-ref')).toBe(refs)
  expect(f.calls.filter(row => row.operation === 'push')).toHaveLength(0)
  expect(f.requests().filter(row => row.method !== 'GET')).toHaveLength(0)
  expect(f.source.store.all('forge-publication')).toHaveLength(0)
  expect(f.tasks.get(f.task.id)?.pushedHead).toBeUndefined()
  expect(String(failure)).toContain('payload failed preflight')
  f.reopen()
  expect(f.tasks.get(f.task.id)?.desc).toHaveLength(33000)
  expect(f.source.store.all('forge-publication')).toHaveLength(0)
  f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id)!, desc: 'Corrected brief' })
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
  expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(1)
  expect(f.requests().find(row => row.method === 'POST')?.body).toMatchObject({ title: 'DEMO-2: Bitbucket candidate', description: 'Corrected brief', draft: true, close_source_branch: false })
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  f.reopen()
  expect(f.tasks.get(f.task.id)).toMatchObject({ pr: expectedPr, pushedHead: f.head })
  expect(f.source.store.all('forge-publication')).toHaveLength(1)
  expect(f.state().creates).toBe(1)
}), 30000)

test('Bitbucket public complete payload preflight accepts exact title and brief boundaries', () => withBitbucket(async f => {
  // Eight-character task prefix plus504 name characters is exactly512.
  f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id)!, name: 'n'.repeat(504), desc: 'b'.repeat(32000) })
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
  const posts = f.requests().filter(row => row.method === 'POST')
  expect(posts).toHaveLength(1)
  expect(posts[0].body).toEqual({ title: 'DEMO-2: ' + 'n'.repeat(504), description: 'b'.repeat(32000), draft: true, close_source_branch: false,
    source: { branch: { name: 'work/two' }, commit: { hash: f.head }, repository: { full_name: 'space/sample' } },
    destination: { branch: { name: 'main' }, repository: { full_name: 'space/sample' } } })
  expect(f.state().pr.title).toHaveLength(512)
  expect(f.state().pr.description).toHaveLength(32000)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  f.reopen()
  expect(f.tasks.get(f.task.id)?.pr).toEqual(expectedPr)
  expect(f.state().creates).toBe(1)
}))

test('Bitbucket public complete payload preflight rejects all malformed create fields and encoded bounds', async () => {
  const invalid: { task: Partial<CoreTask>; malformedHeadReply?: boolean }[] = [
    { task: { desc: 'b'.repeat(32001) } }, { task: { name: 'n'.repeat(505) } },
    { task: { branch: 'bad..source' } }, { task: { base: 'bad..destination' } },
    { task: {}, malformedHeadReply: true },
    //32000 NUL characters fit the character bound but JSON needs over128KiB.
    { task: { desc: '\0'.repeat(32000) } },
  ]
  for (const row of invalid) await withBitbucket(async f => {
    const refs = await f.git(f.repo, '--git-dir', f.bare, 'show-ref')
    expect(await f.git(f.folder, 'rev-parse', 'HEAD')).toBe(f.head)
    f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id)!, ...row.task })
    f.update({ malformedHeadReply: row.malformedHeadReply })
    const failure = await f.tasks.pr(f.grant, f.task.id).then(() => undefined, (error: unknown) => error)
    expect(await f.git(f.repo, '--git-dir', f.bare, 'show-ref')).toBe(refs)
    expect(f.calls.filter(call => call.operation === 'push')).toHaveLength(0)
    expect(f.requests().filter(request => request.method !== 'GET')).toHaveLength(0)
    f.reopen()
    expect(f.source.store.all('forge-publication')).toHaveLength(0)
    expect(f.tasks.get(f.task.id)?.pushedHead).toBeUndefined()
    expect(String(failure)).toContain('payload failed preflight')
  })
}, 60000)

test('Bitbucket public complete payload preflight never releases an existing uncertain claim', () => withBitbucket(async f => {
  f.update({ loseCreateReply: true, hidePr: true })
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
  const claims = f.source.store.all<Record<string, unknown>>('forge-publication')
  expect(claims).toHaveLength(1)
  const original = claims[0]
  expect(original).toMatchObject({ state: 'uncertain', task: 'DEMO-2', head: f.head })
  expect(f.state().creates).toBe(1)
  const refs = await f.git(f.repo, '--git-dir', f.bare, 'show-ref'), calls = f.calls.length, requests = f.requests().length
  f.reopen()
  f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id)!, desc: 'b'.repeat(33000) })
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('payload failed preflight')
  expect(f.calls.slice(calls).filter(row => row.operation === 'push')).toHaveLength(0)
  expect(f.requests()).toHaveLength(requests)
  expect(f.source.store.all('forge-publication')).toEqual([original])
  f.reopen()
  f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id)!, desc: 'Corrected brief' })
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('uncertain')
  expect(f.source.store.all('forge-publication')).toEqual([original])
  expect(await f.git(f.repo, '--git-dir', f.bare, 'show-ref')).toBe(refs)
  expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(1)
  f.update({ hidePr: false, loseCreateReply: false }); f.reopen()
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(expectedPr)
  const confirmed = f.source.store.all<Record<string, unknown>>('forge-publication')
  expect(confirmed).toHaveLength(1)
  expect(confirmed[0]).toMatchObject({ id: original.id, state: 'confirmed', pr: expectedPr })
  expect(f.state().creates).toBe(1)
  expect(f.tasks.get(f.task.id)?.pr).toEqual(expectedPr)
}), 30000)

test('Bitbucket shared complete payload validator retains strict request context and operation shapes', () => {
  // Supporting pure protocol evidence; public no-effect proof lives above.
  const context = { repository: 'space/sample', folder: '/fixture/task', origins: { used: 'https://alice@bitbucket.org/space/sample.git', written: 'https://alice@bitbucket.org/space/sample.git', push: 'https://alice@bitbucket.org/space/sample.git' }, credential: { host: 'bitbucket.org', path: 'space/sample.git', username: 'alice' } }
  const operation = { kind: 'create', branch: 'work/two', base: 'main', head: 'a'.repeat(40), title: 'Candidate', body: 'Brief' }
  const valid = { version: 1, context, operation }
  expect(() => parseBitbucketRequest(valid)).not.toThrow()
  const invalid = [
    { ...valid, version: 2 }, { ...valid, extra: 'unsupported' },
    { ...valid, context: { ...context, repository: 'space/foreign' } },
    { ...valid, context: { ...context, folder: 'relative' } },
    { ...valid, context: { ...context, origins: { ...context.origins, extra: 'unsupported' } } },
    { ...valid, context: { ...context, origins: { ...context.origins, push: 'https://foreign.invalid/space/sample.git' } } },
    { ...valid, context: { ...context, credential: { ...context.credential, username: 'bob' } } },
    { ...valid, context: { ...context, credential: { ...context.credential, path: 'space/foreign.git' } } },
    { ...valid, operation: { ...operation, kind: 'arbitrary-http' } },
    { ...valid, operation: { ...operation, extra: 'unsupported' } },
    ...['branch', 'base', 'head', 'title', 'body'].map(field => ({ ...valid, operation: { ...operation, [field]: 42 } })),
  ]
  expect(invalid).toHaveLength(15)
  for (const request of invalid) expect(() => parseBitbucketRequest(request)).toThrow()
})
