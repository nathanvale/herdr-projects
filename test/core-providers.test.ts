import { expect, test } from 'bun:test'
import { mkdtempSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CoreStore } from '../server/core/store.ts'
import { CoreSettings } from '../server/core/settings.ts'
import { CoreAgents } from '../server/core/agents.ts'
import { providerPlan } from '../server/core/providers.ts'
import type { CoreFiles } from '../server/core/files.ts'
import type { CoreSession } from '../server/core/session.ts'
import type { Mailbox } from '../server/core/mailbox.ts'
import type { CoreSpace } from '../server/core/model.ts'

const space: CoreSpace = { id: 'space', machine: 'local', name: 'Example', folder: '/unused', base: 'main', prefix: 'EX', mode: 'regular', added: 1 }
function fixture() {
  const home = mkdtempSync(join(tmpdir(), 'shep-provider-')), store = new CoreStore(home)
  const settings = new CoreSettings(store, {} as CoreFiles, () => [space], id => id, () => {})
  return { home, store, settings, close: () => { store.close(); rmSync(home, { recursive: true, force: true }) } }
}

test('provider selector persists through the settings interface with machine and space inheritance', () => {
  const f = fixture()
  try {
    expect(f.settings.get('provider.route', space.id)).toBe('Personal')
    f.settings.set('provider.route', 'Azure Foundry', 'm:local')
    expect(f.store.get('settings', 'm:local\0provider.route')).toBe('Azure Foundry')
    const rows = f.settings.sections().find(section => section.name === 'Agents' && section.level === space.id)!.rows
    expect(rows.find(row => row.key === 'provider.route')).toMatchObject({ value: 'Azure Foundry', options: ['Personal', 'Azure Foundry'] })
    f.settings.set('provider.route', 'Personal', space.id)
    expect(f.settings.get('provider.route', space.id)).toBe('Personal')
    expect(() => f.settings.set('provider.route', 'unknown')).toThrow()
  } finally { f.close() }
})

test('Azure Claude launch composes routing and lifecycle hooks and retains its binding', async () => {
  const f = fixture()
  try {
    f.settings.set('provider.route', 'Azure Foundry')
    f.settings.set('azure.claudeResource', 'example-resource')
    f.settings.set('azure.claudeDeployment', 'example-opus-deployment')
    let submitted: { argv: string[]; env: Record<string, string | null> } | undefined
    const core = { current: { terminals: new Map() }, call: async (_method: string, input: typeof submitted) => { submitted = input; return { address: 't1', pid: 123 } } } as unknown as CoreSession
    const agents = new CoreAgents({ home: f.home, port: 0, session: 'test', socket: '/unused', binary: 'hc' }, { format: 'shepherdr-core', schema: 1, id: 'test' }, core, f.store, { issue: () => ({ id: 'grant', credential: {} }) } as unknown as Mailbox, async () => undefined, () => {})
    agents.settings = f.settings
    const record = await agents.launch(space, 'chat', 'claude', 'hello', { model: 'personal-model', effort: 'high' })
    expect(submitted!.argv[0]).toBe('claude')
    expect(submitted!.argv[submitted!.argv.indexOf('--model') + 1]).toBe('example-opus-deployment')
    const config = JSON.parse(readFileSync(submitted!.argv[submitted!.argv.indexOf('--settings') + 1], 'utf8'))
    expect(config.env).toMatchObject({ CLAUDE_CODE_USE_FOUNDRY: '1', ANTHROPIC_FOUNDRY_RESOURCE: 'example-resource', ANTHROPIC_FOUNDRY_API_KEY: '' })
    expect(config.hooks.SessionStart[0].hooks[0].command).toContain('core-hook.ts')
    expect(config.hooks.PermissionRequest[0].hooks[0].timeout).toBe(3600)
    expect(f.store.get('agent', 'chat')).toMatchObject({ provider: { route: 'azure-foundry' }, model: 'example-opus-deployment' })
    f.settings.set('provider.route', 'Personal')
    submitted = undefined
    await expect(agents.launch(space, 'chat', 'claude', 'hello', { resume: true })).rejects.toThrow('cannot be rerouted')
    expect(submitted).toBeUndefined()
    expect(f.store.get('agent', 'chat')).toEqual(record)
  } finally { f.close() }
})

test('Azure Codex uses official Responses provider overrides without placing the key in argv or binding', () => {
  const values: Record<string, string> = { 'provider.route': 'Azure Foundry', 'azure.codexEndpoint': 'https://example.openai.azure.com/openai/v1', 'azure.codexDeployment': 'example-codex' }
  const plan = providerPlan('codex', key => values[key] ?? '', { AZURE_OPENAI_API_KEY: 'test-only-not-a-secret' })
  expect(plan.codexArgs).toContain('model_provider="shepherdr_azure"')
  expect(plan.codexArgs).toContain('model_providers.shepherdr_azure.wire_api="responses"')
  expect(plan.codexArgs).toContain('model_providers.shepherdr_azure.requires_openai_auth=false')
  expect(plan.codexArgs).toContain('model_providers.shepherdr_azure.env_key="AZURE_OPENAI_API_KEY"')
  expect(JSON.stringify([plan.binding, plan.codexArgs])).not.toContain('test-only-not-a-secret')
  expect(plan.env.AZURE_OPENAI_API_KEY).toBe('test-only-not-a-secret')
  expect(() => providerPlan('codex', key => values[key] ?? '', {})).toThrow('credential owner')
  values['azure.codexEndpoint'] = 'https://attacker.example/openai/v1'
  expect(() => providerPlan('codex', key => values[key] ?? '', { AZURE_OPENAI_API_KEY: 'unused' })).toThrow('RESOURCE.openai.azure.com')
})

test('personal plan clears inherited Azure routing and uses the native OpenAI provider', () => {
  const plan = providerPlan('codex', () => '', { AZURE_OPENAI_API_KEY: 'unused', OPENAI_BASE_URL: 'https://example.invalid' })
  expect(plan.binding).toEqual({ route: 'personal', fingerprint: 'personal' })
  expect(plan.env.AZURE_OPENAI_API_KEY).toBeNull()
  expect(plan.env.OPENAI_BASE_URL).toBeNull()
  expect(plan.codexArgs).toContain('model_provider="openai"')
  expect(plan.claudeEnv.CLAUDE_CODE_USE_FOUNDRY).toBe('')
})
