import { expect, test } from 'bun:test'
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createHash } from 'node:crypto'
import { CoreSource } from '../server/core/source.ts'
import { CorePilotRepositories } from '../server/core/pilot-repositories.ts'
import { runChild } from './child.ts'

test('cold CoreSource GitHub observer retains checked runtime without agent rows and refuses contained Bitbucket before effects', async () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'shep-cold-forge-'))), app = join(root, 'app'), user = join(root, 'user'), repo = join(root, 'repo'), bin = join(root, 'bin')
  mkdirSync(user); mkdirSync(bin)
  // Independent provider head and closed executable. No inherited credentials.
  const head = 'a'.repeat(40), provider = join(root, 'provider.json'), requests = join(root, 'requests.jsonl')
  writeFileSync(provider, JSON.stringify({ green: false })); writeFileSync(requests, '')
  const gh = join(root, 'gh.ts')
  writeFileSync(gh, `import{appendFileSync,readFileSync}from'node:fs';const a=process.argv.slice(2);appendFileSync(${JSON.stringify(requests)},JSON.stringify(a)+'\\n');const s=JSON.parse(readFileSync(${JSON.stringify(provider)},'utf8'));if(a[0]==='api'){if(a.some(x=>x.includes('/commits?')))console.log(JSON.stringify([${JSON.stringify(head)}]));else console.log(${JSON.stringify(head)})}else if(a[0]==='run'&&a[1]==='list')console.log(JSON.stringify([{headSha:${JSON.stringify(head)},status:'completed',conclusion:s.green?'success':'failure',url:'https://github.com/o/r/actions/runs/9',workflowName:'Build',databaseId:9}]));else process.exit(1)`)
  const quote = (text: string) => `'${text.replaceAll("'", "'\"'\"'")}'`
  writeFileSync(join(bin, 'gh'), `#!/bin/sh\ncd ${quote(user)} || exit 1\nexec ${quote(process.execPath)} --no-env-file ${quote(gh)} "$@"\n`, { mode: 0o700 })
  const env = { PATH: bin + ':' + process.env.PATH, HOME: user, XDG_CONFIG_HOME: user, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null', GIT_AUTHOR_NAME: 'Fixture', GIT_AUTHOR_EMAIL: 'fixture@example.invalid', GIT_COMMITTER_NAME: 'Fixture', GIT_COMMITTER_EMAIL: 'fixture@example.invalid' }
  const git = (...args: string[]) => runChild(['git', ...args], { cwd: root, env })
  await git('init', '--initial-branch=main', repo)
  await git('-C', repo, 'commit', '--allow-empty', '-m', 'Independent fixture')
  await git('-C', repo, 'remote', 'add', 'origin', 'https://github.com/o/r.git')
  const config = { home: app, port: 0, socket: '/unused', binary: 'hc', session: 'test', plugins: false }
  let source = new CoreSource(config)
  const installation = JSON.parse(readFileSync(join(app, 'installation.json'), 'utf8')).id
  const runtime = join(user, '.local/share/shepherdr-agents', installation, 'c'.repeat(24))
  mkdirSync(join(runtime, 'helper'), { recursive: true, mode: 0o700 })
  for (const name of ['core-pilot-git.ts', 'core-pilot-path.ts', 'core-pilot-sandbox.ts']) writeFileSync(join(runtime, 'helper', name), readFileSync(join(import.meta.dir, '../helper', name)), { mode: 0o600 })
  const calls: { argv: string[]; on?: string }[] = []
  const connect = async () => {
    source.core.current.connected = true; source.core.current.epoch++
    source.settings.probe = () => {}
    source.core.call = async <T>(method: string, params: Record<string, any>) => {
      if (method === 'server.status') return { core: { id: 'local', name: 'Fixture local' } } as T
      if (method === 'machine.list') return { machines: [{ id: 'remote', name: 'fixture-remote', state: 'connected' }] } as T
      if (method !== 'machine.exec' || params.on !== 'fixture-remote') throw Error('Fixture refuses unknown execution owner')
      calls.push({ argv: params.argv, on: params.on })
      if (params.argv[0] === 'sh') {
        if (params.argv[2].startsWith('command -v bun')) return { stdout: Buffer.from(process.execPath).toString('base64'), stderr: '', code: 0 } as T
        throw Error('Fixture refuses provisioning shell')
      }
      if (params.argv[0] !== process.execPath) throw Error('Observer bypassed checked Git broker')
      const input = params.input && Buffer.from(params.input, 'base64')
      if (params.argv.includes('-e') && (!input || !JSON.parse(input.toString()).expected)) throw Error('Fixture refuses runtime provisioning')
      const stdout = await runChild(params.argv, { cwd: user, input, env })
      return { stdout: stdout.toString('base64'), stderr: '', code: 0, truncated: false, timed_out: false } as T
    }
    for (const machine of ['local', 'remote']) source.store.set('space', `p:${machine}:~`, { id: `p:${machine}:~`, machine, name: 'home', folder: user, home: true, mode: 'regular', base: 'main', added: 1 })
    await source.refresh()
  }
  const close = async () => { source.stop(); await source.github.drain(); await Bun.sleep(0); source.mailbox.close(); source.store.close() }
  try {
    await connect()
    const space = { id: 'checked-space', machine: 'remote', folder: repo, name: 'Checked', prefix: 'DEMO', mode: 'regular' as const, base: 'main', added: 1 }
    source.store.set('space', space.id, space)
    new CorePilotRepositories(source.store).remember('remote', repo, [])
    const key = createHash('sha256').update(JSON.stringify(['remote', repo, 'main'])).digest('hex')
    source.store.set('github-main', key, { id: key, red: head, checked: 1 })
    // Discover an existing application-owned bundle; the production owner writes
    // the retained record after its real read-only permission/source checks.
    expect(await source.agents.browserRuntime('remote', false)).toMatchObject({ root: runtime })
    expect(source.store.all('agent')).toEqual([])
    expect(source.store.get('checked-runtime', 'remote')).toEqual({ machine: 'remote', installation, root: runtime })
    await close(); source = new CoreSource(config); await connect()
    expect(source.store.all('agent')).toEqual([])
    await source.github.watchMain(space, 120001)
    expect(source.store.get('github-main', key)).toEqual({ id: key, red: head, checked: 120001 })
    const observed = readFileSync(requests, 'utf8').trim().split('\n').map(line => JSON.parse(line))
    expect(observed.filter(argv => argv[0] === 'api')).toHaveLength(3)
    expect(observed.filter(argv => argv[0] === 'run')).toHaveLength(2)
    expect(calls.filter(call => call.argv.at(-1)?.endsWith('core-pilot-git.ts')).length).toBeGreaterThan(5)
    writeFileSync(provider, JSON.stringify({ green: true }))
    await source.github.watchMain(space, 180002)
    expect(source.store.get('github-main', key)).toEqual({ id: key, green: head, checked: 180002 })
    const before = readFileSync(requests, 'utf8')
    await git('-C', repo, 'remote', 'set-url', 'origin', 'https://bitbucket.org/o/r.git')
    source.store.set('github-main', key, { id: key, red: head, checked: 1 })
    await source.github.watchMain(space, 240003)
    expect(source.store.get<{ error: string }>('github-main', key)?.error).toContain('Contained Bitbucket')
    expect(readFileSync(requests, 'utf8')).toBe(before)
    expect(calls.some(call => call.argv.at(-1)?.endsWith('core-bitbucket.ts') || call.argv[0] === 'git' || call.argv[0] === 'gh')).toBe(false)
    // Reopen again and corrupt the retained bundle. A record is not validation.
    await close(); source = new CoreSource(config); await connect()
    writeFileSync(join(runtime, 'helper/core-pilot-git.ts'), '// foreign bytes\n')
    await expect(source.agents.browserRuntime('remote', false)).rejects.toThrow('bundle differs')
    writeFileSync(join(runtime, 'helper/core-pilot-git.ts'), readFileSync(join(import.meta.dir, '../helper/core-pilot-git.ts')))
    source.store.set('checked-runtime', 'remote', { machine: 'foreign', installation, root: runtime })
    const beforeForeignOwner = calls.length
    await expect(source.agents.browserRuntime('remote', false)).rejects.toThrow('ownership differs')
    expect(calls).toHaveLength(beforeForeignOwner)
  } finally { await close(); rmSync(root, { recursive: true, force: true }) }
}, 30000)
