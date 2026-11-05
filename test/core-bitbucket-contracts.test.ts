import { expect, test } from 'bun:test'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { CoreTask } from '../server/core/tasks.ts'
import type { ForgePrRecord } from '../shared/types.ts'
import { withBitbucket } from './bitbucket-fixture.ts'

// Independent provider/task oracles; no production identity/payload helpers.
const pr: ForgePrRecord = { provider: 'bitbucket', host: 'bitbucket.org', repository: 'space/sample', number: 37, url: 'https://bitbucket.org/space/sample/pull-requests/37' }

test('Bitbucket public credential fill accepts private expiry refresh and unknown metadata', () => withBitbucket(async f => {
  f.update({ credentialMetadata: { password_expiry_utc: '4102444800', oauth_refresh_token: 'SYNTHETIC_REFRESH_SECRET_456', vendor_private: 'SYNTHETIC_EXTRA_SECRET_789' }, credentialReply: 'metadata' })
  // Actual Git retains its documented metadata; unknown output is decorated
  // only after real fill because Git itself discards unknown helper attributes.
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(pr)
  const fills = readFileSync(join(f.root, 'credential-fills.jsonl'), 'utf8').trim().split('\n').map(row => JSON.parse(row))
  expect(fills.length).toBeGreaterThan(0)
  expect(fills.every(row => row.expiry === '4102444800' && row.refresh === true && row.username === 'alice' && row.password === true && row.decoration === 'metadata')).toBe(true)
  expect(f.requests().length).toBeGreaterThan(0)
  expect(f.requests().every(row => row.authorization === 'Bearer SYNTHETIC_TOKEN_ALICE_123')).toBe(true)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  const panel = await f.tasks.forge.presentation({ machine: f.task.machine, folder: f.folder }, 'work/two', pr)
  f.reopen()
  const publicData = JSON.stringify([f.tasks.get(f.task.id), f.source.store.all('forge-publication'), panel, f.outputs, f.requests().map(row => row.body)])
  for (const secret of ['SYNTHETIC_TOKEN_ALICE_123', 'SYNTHETIC_REFRESH_SECRET_456', 'SYNTHETIC_EXTRA_SECRET_789', 'oauth_refresh_token', 'password_expiry_utc', 'vendor_private']) expect(publicData).not.toContain(secret)
}))

test('Bitbucket public real credential fill rejects duplicate malformed and negotiated replies', async () => {
  for (const credentialReply of ['duplicate', 'malformed', 'unsupported']) await withBitbucket(async f => {
    f.update({ credentialReply })
    await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow(/credential|REST/i)
    const fills = readFileSync(join(f.root, 'credential-fills.jsonl'), 'utf8').trim().split('\n').map(row => JSON.parse(row))
    expect(fills.some(row => row.username === 'alice' && row.password === true && row.decoration === credentialReply)).toBe(true)
    expect(f.calls.filter(row => row.operation === 'push')).toHaveLength(0)
    expect(f.requests().filter(row => row.method !== 'GET')).toHaveLength(0)
    expect(f.source.store.all('forge-publication')).toHaveLength(0)
    expect(JSON.stringify(f.outputs)).not.toContain('UNSUPPORTED_SYNTHETIC_SECRET')
  })
}, 30000)

test('Bitbucket public readiness retains edited title Cloud reviewers retention and release destination', () => withBitbucket(async f => {
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(pr)
  await f.git(f.repo, 'branch', 'release', 'main')
  const current = f.tasks.get(f.task.id)!
  f.source.store.set('task', f.task.id, { ...current, base: 'release' })
  const provider = f.state().pr
  f.update({ pr: { ...provider, title: 'Maintainer edited title', reviewers: [
    { type: 'user', uuid: '{12345678-1234-1234-1234-123456789abc}', account_id: '557058:first', display_name: 'Reviewer One', links: { html: { href: 'https://bitbucket.org/one/' } } },
    { type: 'user', account_id: '557058:second', display_name: 'Reviewer Two' },
  ], close_source_branch: true, destination: { ...provider.destination, branch: { name: 'release' } } } })
  f.reopen()
  await f.tasks.ready(f.grant, f.task.id, 'Ready release', 'Build passed')
  const expected = { title: 'Maintainer edited title', reviewers: [{ uuid: '{12345678-1234-1234-1234-123456789abc}' }, { account_id: '557058:second' }], close_source_branch: true,
    destination: { branch: { name: 'release' }, repository: { full_name: 'space/sample' } }, description: 'Ready release\n\nFacts: Build passed', draft: false }
  expect(f.requests().filter(row => row.method === 'PUT').map(row => row.body)).toEqual([expected])
  expect(f.state().pr).toMatchObject({ title: 'Maintainer edited title', reviewers: [{ uuid: '{12345678-1234-1234-1234-123456789abc}' }, { account_id: '557058:second' }], close_source_branch: true,
    destination: { branch: { name: 'release' }, repository: { full_name: 'space/sample' } }, description: 'Ready release\n\nFacts: Build passed', draft: false })
  f.reopen()
  expect(f.tasks.get(f.task.id)).toMatchObject({ readyHead: f.head, readyBase: 'release', readyPr: pr, workflow: 'ready' })
}))

test('Bitbucket public readiness refuses missing or malformed omission preservation before PUT', async () => {
  const invalid = [{ title: '' }, { title: undefined }, { reviewers: undefined }, { reviewers: null }, { reviewers: [{ username: 'legacy-only' }] }, { reviewers: [{ uuid: 'invalid' }] }, { reviewers: [{ account_id: 42 }] }, { close_source_branch: null }, { close_source_branch: undefined }]
  for (const patch of invalid) await withBitbucket(async f => {
    await f.tasks.pr(f.grant, f.task.id)
    f.update({ pr: { ...f.state().pr, ...patch } })
    f.reopen()
    await expect(f.tasks.ready(f.grant, f.task.id, 'Ready')).rejects.toThrow(/invalid|bounded/i)
    expect(f.requests().filter(row => row.method === 'PUT')).toHaveLength(0)
    expect(f.tasks.get(f.task.id)?.workflow).toBe('working')
  })
}, 60000)

test('Bitbucket public confirmed push survives epoch change and reopened next candidate lease', () => withBitbucket(async f => {
  f.route.after = async operation => { if (operation === 'push') f.route.epoch++ }
  await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('route changed')
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  expect(f.tasks.get(f.task.id)).toMatchObject({ pushedHead: f.head, workflow: 'working' })
  expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
  expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(0)
  f.route.after = undefined; f.reopen()
  expect(f.tasks.get(f.task.id)?.pushedHead).toBe(f.head)
  writeFileSync(join(f.folder, 'value.txt'), 'next candidate\n'); await f.git(f.folder, 'commit', '-am', 'Next candidate')
  const next = await f.git(f.folder, 'rev-parse', 'HEAD')
  expect(next).not.toBe(f.head)
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(pr)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(next)
  f.reopen()
  expect(f.tasks.get(f.task.id)).toMatchObject({ pushedHead: next, pr })
  expect(f.state().creates).toBe(1)
}), 30000)

test('Bitbucket public binding edits during push or create retain current metadata and confirmed push only', async () => {
  for (const phase of ['push', 'create']) await withBitbucket(async f => {
    f.route.after = async operation => {
      if (operation !== phase) return
      const current = f.tasks.get(f.task.id)!
      f.source.store.set('task', f.task.id, { ...current, desc: 'New binding description', report: { msg: 'Current report', progress: 63 }, reportedAt: 123456 })
    }
    await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('changed')
    f.reopen()
    expect(f.tasks.get(f.task.id)).toMatchObject({ desc: 'New binding description', report: { msg: 'Current report', progress: 63 }, reportedAt: 123456, pushedHead: f.head })
    expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
    expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
    expect(f.state().creates).toBe(phase === 'push' ? 0 : 1)
    if (phase === 'create') {
      const record = f.source.store.all<Record<string, unknown>>('forge-publication')[0]
      expect(record.state).toBe('uncertain')
      f.route.after = undefined
      expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(pr)
      expect(f.source.store.all<Record<string, unknown>>('forge-publication')[0].id).toBe(record.id)
      expect(f.state().creates).toBe(1)
    }
  })
}, 30000)

test('Bitbucket public harmless reports survive both awaited publication saves', () => withBitbucket(async f => {
  const observed: string[] = []
  f.route.after = async operation => {
    if (operation !== 'push' && operation !== 'create') return
    const current = f.tasks.get(f.task.id)!
    if (operation === 'create') expect(current.report).toEqual({ msg: 'After push', progress: 41 })
    observed.push(operation)
    f.source.store.set('task', f.task.id, { ...current, report: operation === 'push' ? { msg: 'After push', progress: 41 } : { msg: 'After create', progress: 73 }, reportedAt: operation === 'push' ? 111 : 222 })
  }
  expect(await f.tasks.pr(f.grant, f.task.id)).toEqual(pr)
  expect(observed).toEqual(['push', 'create'])
  f.reopen()
  expect(f.tasks.get(f.task.id)).toMatchObject({ report: { msg: 'After create', progress: 73 }, reportedAt: 222, pushedHead: f.head, pr })
  expect(f.state().creates).toBe(1)
}))

test('Bitbucket public push receipt never resurrects replaces or retargets current ownership', async () => {
  const changes: (Partial<CoreTask> | null)[] = [null, { created: '2026-11-06T00:00:00Z' }, { base: 'release' }, { machine: 'second-machine' }, { workflow: 'closed', state: 'Closed' }, { pushedHead: '1'.repeat(40) }, { pr }]
  for (const patch of changes) await withBitbucket(async f => {
    f.route.after = async operation => {
      if (operation !== 'push') return
      const current = f.tasks.get(f.task.id)!
      if (patch === null) f.source.store.delete('task', f.task.id)
      else f.source.store.set('task', f.task.id, { ...current, ...patch })
    }
    await expect(f.tasks.pr(f.grant, f.task.id)).rejects.toThrow('changed')
    expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
    f.reopen()
    if (patch === null) expect(f.tasks.get(f.task.id)).toBeUndefined()
    else { expect(f.tasks.get(f.task.id)).toMatchObject(patch); expect(f.tasks.get(f.task.id)?.pushedHead).toBe(patch.pushedHead) }
    expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(0)
  })
}, 60000)

test('Bitbucket public mismatched push receipt and stale observation stay unconfirmed', () => withBitbucket(async f => {
  f.update({ wrongPushReceipt: true })
  f.route.after = async operation => { if (operation === 'push') f.route.epoch++ }
  const failure = await f.tasks.pr(f.grant, f.task.id).then(() => undefined, (error: unknown) => error)
  expect(await f.git(f.repo, '--git-dir', f.bare, 'rev-parse', 'refs/heads/work/two')).toBe(f.head)
  f.reopen()
  expect(f.tasks.get(f.task.id)?.pushedHead).toBeUndefined()
  expect(f.tasks.get(f.task.id)?.pr).toBeUndefined()
  expect(f.requests().filter(row => row.method === 'POST')).toHaveLength(0)
  expect(String(failure)).toContain('candidate')
}))
