import { readFileSync, writeFileSync, appendFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'

// CI-only HTTP fixture. It replaces fetch inside a real helper process and never
// opens a network connection. Production requests cannot choose this transport.
const statePath = process.env.BITBUCKET_FIXTURE_STATE!
globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
  const url = new URL(String(input)), state = JSON.parse(readFileSync(statePath, 'utf8'))
  const method = init?.method ?? 'GET', authorization = new Headers(init?.headers).get('Authorization')
  const body = init?.body ? JSON.parse(String(init.body)) : undefined
  appendFileSync(state.requests, JSON.stringify({ url: url.href, method, authorization, body }) + '\n')
  if (url.origin !== 'https://api.bitbucket.org') throw Error('Fixture refuses all other hosts')
  const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
  if (state.rejectCredential || authorization !== `Bearer ${state.token}`) return reply({ error: `private diagnostic ${state.token}` }, 403)
  const repo = { full_name: 'space/sample', links: { html: { href: 'https://bitbucket.org/space/sample' } } }
  const head = (branch: string) => execFileSync('git', ['--git-dir', state.bare, 'rev-parse', `refs/heads/${branch}`], { env: process.env }).toString().trim()
  const root = '/2.0/repositories/space/sample'
  if (url.pathname === root) return reply(repo)
  if (url.pathname.startsWith(root + '/refs/branches/')) {
    const name = decodeURIComponent(url.pathname.slice((root + '/refs/branches/').length))
    try { return reply({ name, target: { hash: head(name) } }) } catch { return reply({}, 404) }
  }
  if (url.pathname === root + '/pullrequests') {
    if (method === 'POST') {
      if (state.rejectCreate) return reply({ error: state.token }, 403)
      // Independent provider contract, with live Git evidence for the candidate.
      if (body?.source?.repository?.full_name !== 'space/sample' || body?.destination?.repository?.full_name !== 'space/sample' || body?.source?.branch?.name !== 'work/two' || body?.destination?.branch?.name !== 'main' || body?.source?.commit?.hash !== head('work/two')) return reply({}, 400)
      state.creates++
      state.pr = { id: 37, title: state.providerTitle ?? body.title, description: body.description, state: 'OPEN', draft: body.draft ?? false, close_source_branch: body.close_source_branch ?? true,
        source: { repository: repo, branch: { name: body.source.branch.name }, commit: { hash: head('work/two') } },
        destination: { repository: repo, branch: { name: 'main' } }, links: { html: { href: 'https://bitbucket.org/space/sample/pull-requests/37' } } }
      writeFileSync(statePath, JSON.stringify(state))
      return reply(state.pr, 201)
    }
    if (state.pr) state.pr.source.commit.hash = state.overrideHead ?? head('work/two')
    return reply({ values: state.hidePr ? [] : state.pr ? [state.pr] : [] })
  }
  if (url.pathname === root + '/pullrequests/37') {
    if (!state.pr) return reply({}, 404)
    // Mimic the provider's live source branch rather than echoing caller input.
    state.pr.source.commit.hash = state.overrideHead ?? head('work/two')
    if (method === 'PUT') {
      state.prepares++
      if (body && 'draft' in body) state.pr.draft = body.draft
      if (body && 'description' in body) state.pr.description = body.description
      writeFileSync(statePath, JSON.stringify(state))
    }
    return reply(state.pr)
  }
  if (/\/commit\/[a-f0-9]{40}\/statuses$/.test(url.pathname)) {
    if (state.statusRedirect) return new Response(null, { status: 302, headers: { Location: 'https://foreign.invalid/stolen' } })
    const commit = url.pathname.split('/').at(-2)!
    if (state.statusOversize) return reply({ values: [], padding: 'x'.repeat(1024 * 1024 + 1) })
    if (state.statusEndless) { const next = new URL(url); next.searchParams.set('page', String(Number(url.searchParams.get('page') ?? 1) + 1)); return reply({ values: [], next: next.href }) }
    if (state.statusNext && !url.searchParams.has('page')) return reply({ values: state.checks ?? [], next: state.statusNext === 'same' ? url.href : state.statusNext === 'second' ? url.href + '&page=2' : state.statusNext })
    if (state.statusMissing) return reply({ unrelated: [] })
    const rows = url.searchParams.has('page') ? state.secondChecks ?? [] : state.checks ?? [{ type: 'build', key: 'build', name: 'Build', state: 'SUCCESSFUL', url: 'https://ci.example.invalid/build/9', links: { commit: { href: `https://api.bitbucket.org${root}/commit/${commit}` } } }]
    return reply({ values: rows, ...state.statusPage })
  }
  throw Error('Unexpected fixture endpoint')
}) as typeof fetch
