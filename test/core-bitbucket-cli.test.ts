import { expect, test } from 'bun:test'
import { withBitbucketCli, type CliFixture } from './bitbucket-cli-fixture.ts'

// Approved native CLI contract: pretty JSON plus newline on stdout/exit0;
// failures have empty stdout, safe message plus newline on stderr/exit1.
const success = '{\n  "provider": "bitbucket",\n  "host": "bitbucket.org",\n  "repository": "space/sample",\n  "number": 37,\n  "url": "https://bitbucket.org/space/sample/pull-requests/37"\n}\n'
const expectedPr = { provider: 'bitbucket', host: 'bitbucket.org', repository: 'space/sample', number: 37, url: 'https://bitbucket.org/space/sample/pull-requests/37' }
const preflight = 'Bitbucket publication payload failed preflight; correct the task title, brief or source/destination identity within the supported bounds. Nothing was pushed or submitted by this call'
const taskChanged = 'The task changed after an admitted operation was dispatched. Check the recorded push and original pull request outcome before continuing; no further forge action is permitted by this call'
const routeChanged = 'The task execution route changed after an admitted operation was dispatched. Check the recorded push and original pull request outcome before continuing; no further Bitbucket action is permitted by this call'
const uncertain = 'Bitbucket publication is uncertain; reconcile the original operation without another create'

function privateOutputs(c: CliFixture, publicValues: unknown[]) {
  const f = c.f, syntheticKey = c.grant.credential.key
  const data = JSON.stringify([...publicValues, f.outputs, f.source.store.all('task'), f.source.store.all('forge-publication'), f.source.store.all('message:space'), f.source.store.all('message:DEMO-2/Agent')])
  for (const value of ['SYNTHETIC_TOKEN_ALICE_123', 'SYNTHETIC_TOKEN_BOB_456', syntheticKey]) expect(data).not.toContain(value)
}

test('Bitbucket native CLI authenticated mailbox preflight refusal has no effects', () => withBitbucketCli(async c => {
  const { f } = c, refs = await f.git(f.repo, '--git-dir', f.bare, 'show-ref')
  f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id)!, desc: 'b'.repeat(33000) })
  const result = await c.run()
  expect(result).toEqual({ stdout: '', stderr: preflight + '\n', code: 1 })
  expect([...c.replies.values()]).toEqual([{ ok: false, error: preflight }])
  expect(c.dispatches).toHaveLength(1)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'show-ref')).toBe(refs)
  expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(0)
  expect(f.source.store.all('forge-publication')).toHaveLength(0)
  await c.reopen(); expect(f.tasks.get(f.task.id)?.pushedHead).toBeUndefined()
  privateOutputs(c, [result, [...c.replies.values()]])
}))

test('Bitbucket native CLI authenticated mailbox publication preserves approved output and exit', () => withBitbucketCli(async c => {
  const { f } = c
  f.update({ providerTitle: 'Review Bearer SYNTHETIC_TOKEN_ALICE_123' })
  const result = await c.run()
  expect(result).toEqual({ stdout: success, stderr: '', code: 0 })
  expect([...c.replies.values()]).toEqual([{ ok: true, value: { out: success, code: 0 } }])
  expect(c.dispatches).toHaveLength(1)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(1)
  await c.reopen()
  expect(f.tasks.get(f.task.id)).toMatchObject({ pr: expectedPr, pushedHead: f.head })
  expect(f.source.store.all('forge-publication')).toHaveLength(1)
  privateOutputs(c, [result, [...c.replies.values()]])
}))

test('Bitbucket native CLI reports route or task changes after actual push truthfully', async () => {
  for (const change of ['route', 'task']) await withBitbucketCli(async c => {
    const { f } = c
    f.route.after = async operation => {
      if (operation !== 'push') return
      if (change === 'route') f.route.epoch++
      else f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id)!, desc: 'Current binding', report: { msg: 'Current report', progress: 61 } })
    }
    const result = await c.run(), error = change === 'route' ? routeChanged : taskChanged
    expect(result).toEqual({ stdout: '', stderr: error + '\n', code: 1 })
    expect([...c.replies.values()]).toEqual([{ ok: false, error, uncertain: true }])
    expect(result.stderr).not.toContain('nothing was submitted')
    expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
    await c.reopen()
    expect(f.tasks.get(f.task.id)?.pushedHead).toBe(f.head)
    expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
    if (change === 'task') expect(f.tasks.get(f.task.id)).toMatchObject({ desc: 'Current binding', report: { msg: 'Current report', progress: 61 } })
    expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(0)
    expect(f.source.store.all('forge-publication')).toHaveLength(0)
    privateOutputs(c, [result, [...c.replies.values()]])
  })
}, 60000)

test('Bitbucket native CLI binding change after provider create retains typed uncertainty and metadata', () => withBitbucketCli(async c => {
  const { f } = c
  f.route.after = async operation => {
    if (operation === 'create') f.source.store.set('task', f.task.id, { ...f.tasks.get(f.task.id)!, desc: 'New create binding', report: { msg: 'Latest report', progress: 72 } })
  }
  const result = await c.run(), error = uncertain + '. ' + taskChanged
  expect(result).toEqual({ stdout: '', stderr: error + '\n', code: 1 })
  expect([...c.replies.values()]).toEqual([{ ok: false, error, uncertain: true }])
  expect(result.stderr).not.toContain('nothing was submitted')
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  const claims = f.source.store.all<Record<string, unknown>>('forge-publication')
  expect(claims).toHaveLength(1); expect(claims[0]).toMatchObject({ state: 'uncertain', head: f.head })
  await c.reopen()
  expect(f.tasks.get(f.task.id)).toMatchObject({ pushedHead: f.head, desc: 'New create binding', report: { msg: 'Latest report', progress: 72 } })
  expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
  expect(f.source.store.all<Record<string, unknown>>('forge-publication')[0].id).toBe(claims[0].id)
  expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(1)
  privateOutputs(c, [result, [...c.replies.values()]])
}))

test('Bitbucket native CLI unknown publication stays typed and original claim survives reopened empty lookup', () => withBitbucketCli(async c => {
  const { f } = c
  f.update({ loseCreateReply: true, hidePr: true })
  const first = await c.run()
  expect(first).toEqual({ stdout: '', stderr: uncertain + '. ' + uncertain + '\n', code: 1 })
  expect([...c.replies.values()]).toEqual([{ ok: false, error: uncertain + '. ' + uncertain, uncertain: true }])
  const original = f.source.store.all<Record<string, unknown>>('forge-publication')
  expect(original).toHaveLength(1); expect(original[0]).toMatchObject({ state: 'uncertain', head: f.head })
  expect(f.calls.filter(call => call.operation === 'push' || call.argv[0] === 'git' && call.argv[1] === 'push')).toHaveLength(1)
  await c.reopen()
  const second = await c.run()
  expect(second).toEqual({ stdout: '', stderr: uncertain + '\n', code: 1 })
  expect([...c.replies.values()]).toEqual([{ ok: false, error: uncertain + '. ' + uncertain, uncertain: true }, { ok: false, error: uncertain, uncertain: true }])
  expect(c.dispatches).toHaveLength(2)
  expect(f.source.store.all('forge-publication')).toEqual(original)
  expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(1)
  expect(f.calls.filter(call => call.operation === 'push' || call.argv[0] === 'git' && call.argv[1] === 'push')).toHaveLength(1)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  expect(f.tasks.get(f.task.id)?.pushedHead).toBe(f.head)
  f.update({ hidePr: false, loseCreateReply: false })
  const reconciled = await c.run()
  expect(reconciled).toEqual({ stdout: success, stderr: '', code: 0 })
  expect([...c.replies.values()]).toEqual([{ ok: false, error: uncertain + '. ' + uncertain, uncertain: true }, { ok: false, error: uncertain, uncertain: true }, { ok: true, value: { out: success, code: 0 } }])
  expect(c.dispatches).toHaveLength(3)
  expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(1)
  // Positive lookup admits the existing workflow's push; empty lookup did not.
  expect(f.calls.filter(call => call.operation === 'push' || call.argv[0] === 'git' && call.argv[1] === 'push')).toHaveLength(2)
  await c.reopen()
  expect(f.source.store.all('forge-publication')).toEqual([{ ...original[0], state: 'confirmed', pr: expectedPr }])
  expect(f.tasks.get(f.task.id)).toMatchObject({ pr: expectedPr, pushedHead: f.head })
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  privateOutputs(c, [first, second, reconciled, [...c.replies.values()]])
}), 30000)

test('Bitbucket native CLI recovers authenticated journal response without redispatch', () => withBitbucketCli(async c => {
  const { f } = c, result = await c.run()
  expect(result).toEqual({ stdout: success, stderr: '', code: 0 })
  expect([...c.replies.values()]).toEqual([{ ok: true, value: { out: success, code: 0 } }])
  expect(c.connections()).toBe(2)
  expect(c.requestIds.size).toBe(1)
  expect(c.dispatches).toHaveLength(1)
  expect(c.journal()).toHaveLength(1)
  expect(c.journal()[0].id).toBe(c.dispatches[0].id)
  expect(c.journal()[0].response).not.toBeNull()
  expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(1)
  const original = f.source.store.all<Record<string, unknown>>('forge-publication')
  expect(original).toHaveLength(1); expect(original[0]).toMatchObject({ state: 'confirmed', pr: expectedPr, head: f.head })
  await c.reopen()
  expect(f.source.store.all('forge-publication')).toEqual(original)
  expect(f.tasks.get(f.task.id)).toMatchObject({ pr: expectedPr, pushedHead: f.head })
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  privateOutputs(c, [result, [...c.replies.values()], c.journal()])
}, true), 30000)
