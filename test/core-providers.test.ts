import { expect, test } from 'bun:test'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync, readFileSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CoreStore } from '../server/core/store.ts'
import { CoreSettings } from '../server/core/settings.ts'
import { CoreAgents } from '../server/core/agents.ts'
import { providerPlan } from '../server/core/providers.ts'
import type { CoreFiles } from '../server/core/files.ts'
import type { CoreSession } from '../server/core/session.ts'
import type { Mailbox } from '../server/core/mailbox.ts'
import type { CoreAgent, CoreSpace } from '../server/core/model.ts'

const space: CoreSpace = { id: 'space', machine: 'local', name: 'Example', folder: '/unused', base: 'main', prefix: 'EX', mode: 'regular', added: 1 }
interface Request { argv: string[]; env?: Record<string, string>; [key: string]: unknown }
function fixture(remote = false) {
  const home = mkdtempSync(join(tmpdir(), 'shep-provider-')), store = new CoreStore(home)
  const settings = new CoreSettings(store, {} as CoreFiles, () => [space], id => id, () => {})
  const calls: { method: string; input: Request }[] = []
  let credentialAvailable = true, grants = 0
  const core = { current: { terminals: new Map() }, call: async (method: string, input: Request) => {
    calls.push({ method, input })
    if (method === 'machine.exec') return { code: credentialAvailable ? 0 : 1, stdout: '', stderr: '', timed_out: false, truncated: false }
    if (method === 'terminal.run') return { address: 't1', pid: 123 }
    throw Error(`Unexpected protocol call: ${method}`)
  } } as unknown as CoreSession
  const mailbox = { issue: () => ({ id: `grant-${++grants}`, credential: {} }) } as unknown as Mailbox
  const agents = new CoreAgents({ home, port: 0, session: 'test', socket: '/unused', binary: 'hc' }, { format: 'shepherdr-core', schema: 1, id: 'test' }, core, store, mailbox, async () => remote ? 'other' : undefined, () => {})
  agents.settings = settings
  const azure = () => {
    settings.set('provider.route', 'Azure Foundry')
    settings.set('azure.claudeResource', 'example-resource')
    settings.set('azure.claudeDeployment', 'example-opus-deployment')
    settings.set('azure.codexEndpoint', 'https://example.openai.azure.com/openai/v1')
    settings.set('azure.codexDeployment', 'example-codex')
  }
  return { home, store, settings, agents, calls, azure, missingCredential: () => { credentialAvailable = false }, grants: () => grants,
    close: () => { store.close(); rmSync(home, { recursive: true, force: true }) } }
}

test('provider and authentication choices persist with machine and space inheritance and reset', () => {
  const f = fixture()
  try {
    expect(f.settings.get('provider.route', space.id)).toBe('Personal')
    f.settings.set('provider.route', 'Azure Foundry', 'm:local')
    f.settings.set('azure.claudeAuth', 'Bearer token', 'm:local')
    expect(f.store.get('settings', 'm:local\0azure.claudeAuth')).toBe('Bearer token')
    const rows = f.settings.sections().find(section => section.name === 'Agents' && section.level === space.id)!.rows
    expect(rows.find(row => row.key === 'provider.route')).toMatchObject({ value: 'Azure Foundry', options: ['Personal', 'Azure Foundry'] })
    expect(rows.find(row => row.key === 'azure.claudeAuth')).toMatchObject({ value: 'Bearer token', options: ['Entra ID', 'API key', 'Bearer token'] })
    expect(rows.find(row => row.key === 'azure.codexAuth')).toMatchObject({ value: 'API key', options: ['API key'] })
    f.settings.set('provider.route', 'Personal', space.id)
    expect(f.settings.get('provider.route', space.id)).toBe('Personal')
    f.settings.set('provider.route', null, space.id)
    expect(f.settings.get('provider.route', space.id)).toBe('Azure Foundry')
    expect(() => f.settings.set('provider.route', 'unknown')).toThrow()
    expect(() => f.settings.set('azure.codexAuth', 'Entra ID')).toThrow()
  } finally { f.close() }
})

// Test-owned expectations from Anthropic's authentication precedence, not implementation constants.
for (const [auth, credential, cleared] of [
  ['Entra ID', undefined, ['ANTHROPIC_FOUNDRY_API_KEY', 'ANTHROPIC_FOUNDRY_AUTH_TOKEN']],
  ['API key', 'ANTHROPIC_FOUNDRY_API_KEY', ['ANTHROPIC_FOUNDRY_AUTH_TOKEN']],
  ['Bearer token', 'ANTHROPIC_FOUNDRY_AUTH_TOKEN', ['ANTHROPIC_FOUNDRY_API_KEY']],
] as const) test(`Azure Claude ${auth} composes native routing, credential references and lifecycle hooks`, async () => {
  const f = fixture()
  try {
    f.azure(); f.settings.set('azure.claudeAuth', auth)
    const record = await f.agents.launch(space, 'chat', 'claude', 'hello', { model: 'personal-model', effort: 'high' })
    const submitted = f.calls.find(call => call.method === 'terminal.run')!.input
    expect(f.calls.map(call => call.method)).toEqual(credential ? ['machine.exec', 'terminal.run'] : ['terminal.run'])
    if (credential) {
      expect(f.calls[0].input.argv.slice(-1)).toEqual([credential])
      expect(submitted.env).not.toHaveProperty(credential)
    }
    expect(submitted.argv[0]).toBe('claude')
    expect(submitted.argv[submitted.argv.indexOf('--model') + 1]).toBe('example-opus-deployment')
    expect(submitted.argv[submitted.argv.indexOf('--effort') + 1]).toBe('high')
    const config = JSON.parse(readFileSync(submitted.argv[submitted.argv.indexOf('--settings') + 1], 'utf8'))
    expect(config.env).toMatchObject({ CLAUDE_CODE_USE_FOUNDRY: '1', ANTHROPIC_FOUNDRY_RESOURCE: 'example-resource', ANTHROPIC_DEFAULT_HAIKU_MODEL: 'example-opus-deployment' })
    for (const key of cleared) { expect(config.env[key]).toBe(''); expect(submitted.env![key]).toBe('') }
    if (credential) expect(config.env).not.toHaveProperty(credential)
    expect(config.hooks.SessionStart[0].hooks[0].command).toContain('core-hook.ts')
    expect(config.hooks.PermissionRequest[0].hooks[0].timeout).toBe(3600)
    expect(f.store.get('agent', 'chat')).toEqual(record)
    expect(record).toMatchObject({ provider: { route: 'azure-foundry' }, model: 'example-opus-deployment' })
  } finally { f.close() }
})

test('Azure Codex launches Responses with only an environment key reference and preserves hooks', async () => {
  const f = fixture()
  try {
    f.azure()
    await f.agents.launch(space, 'chat', 'codex', 'hello')
    expect(f.calls.map(call => call.method)).toEqual(['machine.exec', 'terminal.run'])
    expect(f.calls[0].input.argv.slice(-1)).toEqual(['AZURE_OPENAI_API_KEY'])
    // Execute only the emitted environment probe, never the coding CLI. No ambient credentials.
    const [binary, ...probeArgs] = f.calls[0].input.argv
    for (const env of [{}, { AZURE_OPENAI_API_KEY: 'synthetic-probe-value' }]) {
      const result = spawnSync(binary, probeArgs, { env, encoding: 'utf8', timeout: 5000 })
      expect(result.status).toBe('AZURE_OPENAI_API_KEY' in env ? 0 : 1)
      expect(result.stdout).toBe('')
      expect(result.stderr).toBe('')
    }
    const { argv, env } = f.calls[1].input
    expect(argv[0]).toBe('codex')
    expect(argv).toContain('model_provider="shepherdr_azure_2249716cdb7b805ce15bd0495b3ccce31783989a92d36ec8d2dbcd2f650cc9a2"')
    expect(argv).toContain('model_providers.shepherdr_azure_2249716cdb7b805ce15bd0495b3ccce31783989a92d36ec8d2dbcd2f650cc9a2={name="Azure Foundry",base_url="https://example.openai.azure.com/openai/v1",env_key="AZURE_OPENAI_API_KEY",wire_api="responses",requires_openai_auth=false}')
    expect(argv[argv.indexOf('--model') + 1]).toBe('example-codex')
    expect(argv.some(word => word.startsWith('hooks.SessionStart='))).toBe(true)
    expect(env).not.toHaveProperty('AZURE_OPENAI_API_KEY')
    expect(env).not.toHaveProperty('CODEX_HOME')
  } finally { f.close() }
})

for (const kind of ['claude', 'codex'] as const) test(`Personal ${kind} launches preserve native defaults and legacy session resume`, async () => {
  const f = fixture()
  try {
    const legacy: CoreAgent = { chat: 'chat', space: space.id, machine: space.machine, role: 'coordinator', kind, launch: 'old', grant: 'old', hook: '/old', started: 1, state: 'idle', terminal: 't0', session: 'native-session' }
    f.store.set('agent', 'chat', legacy)
    const record = await f.agents.launch(space, 'chat', kind, 'hello', { resume: true })
    expect(f.calls.map(call => call.method)).toEqual(['terminal.run'])
    const { argv, env } = f.calls[0].input
    expect(argv).toContain('native-session')
    expect(record.session).toBe('native-session')
    expect(f.store.get('agent-launch', 'old')).toEqual(legacy)
    expect(providerPlan(kind, () => '')).toEqual({ binding: { route: 'personal', fingerprint: 'personal' }, env: {}, claudeEnv: {}, codexArgs: [] })
    expect(Object.keys(env!).filter(key => /^(ANTHROPIC|CLAUDE|OPENAI|AZURE)/.test(key))).toEqual([])
    expect(argv.some(word => word.startsWith('model_provider'))).toBe(false)
    if (kind === 'claude') expect(JSON.parse(readFileSync(argv[argv.indexOf('--settings') + 1], 'utf8'))).not.toHaveProperty('env')
  } finally { f.close() }
})

for (const [kind, auth, variable] of [
  ['claude', 'API key', 'ANTHROPIC_FOUNDRY_API_KEY'], ['claude', 'Bearer token', 'ANTHROPIC_FOUNDRY_AUTH_TOKEN'], ['codex', 'API key', 'AZURE_OPENAI_API_KEY'],
] as const) test(`missing ${variable} refuses before grant, files, launch records or terminal creation`, async () => {
  const f = fixture()
  try {
    f.azure(); f.settings.set(`azure.${kind}Auth`, auth); f.missingCredential()
    await expect(f.agents.launch(space, 'chat', kind, 'hello')).rejects.toThrow(variable)
    expect(f.calls.map(call => call.method)).toEqual(['machine.exec'])
    expect(f.grants()).toBe(0)
    expect(f.agents.get('chat')).toBeUndefined()
    expect(readdirSync(f.home)).not.toContain('sessions')
  } finally { f.close() }
})

for (const value of [
  'https://example.com/openai/v1', 'https://example.openai.azure.com.evil.test/openai/v1',
  'http://example.openai.azure.com/openai/v1', 'https://user:secret@example.openai.azure.com/openai/v1',
  'https://example.openai.azure.com/openai/v1?api-key=secret', 'https://example.openai.azure.com/openai/v1#secret',
  'https://example.openai.azure.com:8443/openai/v1', 'https://example.openai.azure.com/openai/deployments/test',
  'https://example.openai.azure.us/openai/v1', 'https://example.openai.azure.com/x/../openai/v1',
]) test(`unsupported endpoint refuses before persistence: ${value.replace('user:secret@', '[userinfo]@').replace('api-key=secret', '[query]').replace('#secret', '#[fragment]')}`, () => {
  const f = fixture()
  try {
    expect(() => f.settings.set('azure.codexEndpoint', value)).toThrow('without credentials')
    expect(f.store.get('settings', 'all\0azure.codexEndpoint')).toBeUndefined()
  } finally { f.close() }
})

test('saved invalid Azure combinations refuse before any execution', async () => {
  const f = fixture()
  try {
    f.azure()
    f.store.set('settings', 'all\0azure.codexAuth', 'Entra ID')
    await expect(f.agents.launch(space, 'chat', 'codex', 'hello')).rejects.toThrow('API key authentication only')
    f.store.set('settings', 'all\0azure.codexAuth', 'API key')
    f.store.set('settings', 'all\0azure.codexEndpoint', 'https://other.example/openai/v1')
    await expect(f.agents.launch(space, 'chat', 'codex', 'hello')).rejects.toThrow('without credentials')
    expect(f.calls).toEqual([])
    expect(f.grants()).toBe(0)
  } finally { f.close() }
})

test('route and authentication changes refuse relaunch while new defaults preserve the native deployment', async () => {
  const f = fixture()
  try {
    f.azure()
    const record = await f.agents.launch(space, 'chat', 'claude', 'hello')
    for (const [key, value, restore] of [
      ['provider.route', 'Personal', 'Azure Foundry'],
      ['azure.claudeAuth', 'API key', 'Entra ID'],
    ]) {
      f.settings.set(key, value); f.calls.length = 0
      await expect(f.agents.launch(space, 'chat', 'claude', 'hello', { resume: true })).rejects.toThrow('cannot be rerouted')
      expect(f.calls).toEqual([])
      expect(f.agents.get('chat')).toEqual(record)
      f.settings.set(key, restore)
    }
    f.settings.set('azure.claudeDeployment', 'another-deployment')
    await expect(f.agents.launch(space, 'chat', 'claude', 'hello', { deployment: 'another-deployment' })).rejects.toThrow('cannot be rerouted')
    f.store.set('agent', 'chat', { ...record, session: 'native-azure-session' })
    const resumed = await f.agents.launch(space, 'chat', 'claude', 'hello', { resume: true })
    expect(resumed.model).toBe('example-opus-deployment')
    expect(resumed.session).toBe('native-azure-session')
    expect(f.calls[0].input.argv).toContain('native-azure-session')
  } finally { f.close() }
})

test('Azure remote and Autopilot starts refuse before credentials, grants or terminal creation', async () => {
  const f = fixture(true), local = fixture()
  try {
    f.azure(); local.azure()
    await expect(f.agents.launch(space, 'chat', 'codex', 'hello')).rejects.toThrow('local execution machine')
    await expect(local.agents.launch(space, 'chat', 'claude', 'hello', { pilot: { run: 'run', hosts: [], repo: '/unused' } })).rejects.toThrow('Autopilot')
    expect(f.calls).toEqual([]); expect(local.calls).toEqual([])
    expect(f.grants()).toBe(0); expect(local.grants()).toBe(0)
  } finally { f.close(); local.close() }
})

test('child launches cannot change provider route', async () => {
  const f = fixture()
  try {
    const parent = await f.agents.launch(space, 'parent', 'claude', 'hello')
    f.azure(); f.calls.length = 0
    await expect(f.agents.launch(space, 'child', 'claude', 'hello', { parent })).rejects.toThrow('Child agents cannot switch')
    expect(f.calls).toEqual([])
    expect(f.agents.get('child')).toBeUndefined()
  } finally { f.close() }
})

for (const kind of ['claude', 'codex'] as const) test(`new ${kind} selection reaches native launch and cannot silently change connection`, async () => {
  const f = fixture()
  try {
    f.azure()
    const deployment = kind === 'claude' ? 'claude-sonnet-5-5' : 'gpt-6-sol'
    f.agents.saveSelection(space, 'new-chat', f.agents.selectionToken('new-chat'), { kind, deployment, effort: 'high' })
    expect(f.calls).toEqual([]); expect(f.grants()).toBe(0)
    const record = await f.agents.launch(space, 'new-chat', kind, 'Wait')
    const request = f.calls.find(call => call.method === 'terminal.run')!.input
    expect(request.argv[request.argv.indexOf('--model') + 1]).toBe(deployment)
    expect(record).toMatchObject({ kind, model: deployment, effort: 'high', provider: { route: 'azure-foundry' } })
    f.agents.saveSelection(space, 'another-chat', f.agents.selectionToken('another-chat'), { kind, deployment })
    f.settings.set('provider.route', 'Personal'); f.calls.length = 0
    await expect(f.agents.launch(space, 'another-chat', kind, 'Wait')).rejects.toThrow('saved Azure connection changed')
    expect(f.calls).toEqual([])
    f.agents.saveSelection(space, 'another-chat', f.agents.selectionToken('another-chat'), { kind, deployment: '' })
    expect(f.agents.selection('another-chat')).toBeUndefined()
  } finally { f.close() }
})

test('role deployment defaults are separate from Personal models and from the other role', () => {
  const f = fixture()
  try {
    f.azure()
    f.settings.set('task.model', 'claude-opus-5-5')
    f.settings.set('task.azure.claudeDeployment', 'claude-sonnet-5-5', space.id)
    expect(f.settings.agent('task', space.id)).toMatchObject({ deployment: 'claude-sonnet-5-5' })
    expect(f.settings.agent('coordinator', space.id)).toMatchObject({ deployment: 'example-opus-deployment' })
    const rows = f.settings.sections().find(section => section.name === 'Agents' && section.level === space.id)!.rows
    expect(rows.find(row => row.key === 'task.azure.claudeDeployment')).toMatchObject({ value: 'claude-sonnet-5-5', text: true })
    f.settings.set('provider.route', 'Personal')
    expect(f.settings.agent('task', space.id)).toMatchObject({ model: 'claude-opus-5-5' })
    expect(f.settings.agent('task', space.id)).not.toHaveProperty('deployment')
  } finally { f.close() }
})

test('a selection changed away and back still rejects an older open selector', () => {
  const f = fixture()
  try {
    f.azure()
    const pick = { kind: 'claude', deployment: 'claude-sonnet-5-5' }
    f.agents.saveSelection(space, 'new', f.agents.selectionToken('new'), pick)
    const old = f.agents.selectionToken('new')
    f.agents.saveSelection(space, 'new', old, { ...pick, deployment: 'claude-haiku-5-5' })
    f.agents.saveSelection(space, 'new', f.agents.selectionToken('new'), pick)
    expect(() => f.agents.saveSelection(space, 'new', old, { ...pick, deployment: 'claude-haiku-5-5' })).toThrow('Selection changed')
    expect(f.agents.selection('new')?.deployment).toBe('claude-sonnet-5-5')
    expect(f.calls).toEqual([])
  } finally { f.close() }
})
