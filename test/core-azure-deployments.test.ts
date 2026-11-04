import { expect, test } from 'bun:test'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CoreStore } from '../server/core/store.ts'
import { CoreSettings } from '../server/core/settings.ts'
import { CoreFiles } from '../server/core/files.ts'
import { providerPlan } from '../server/core/providers.ts'
import type { CoreSession } from '../server/core/session.ts'
import type { CoreSpace } from '../server/core/model.ts'

const subscription = '11111111-2222-3333-4444-555555555555'
const space: CoreSpace = { id: 'space', machine: 'local', name: 'Example', folder: '/unused', base: 'main', prefix: 'EX', mode: 'regular', added: 1 }
const deployment = (name: string, format: string, capabilities: Record<string, string>, state = 'Succeeded') => ({ name, properties: { model: { name: 'test-model', format, version: '1' }, provisioningState: state, capabilities } })
function fixture() {
  const home = mkdtempSync(join(tmpdir(), 'shep-discovery-')), store = new CoreStore(home)
  const calls: string[][] = []
  const controls = { remote: false, cloud: 'AzureCloud', failure: '', malformed: false, beforeInventory: async () => {}, inventory: [
    deployment('code-deployment', 'OpenAI', { responses: 'true' }),
    deployment('claude-deployment', 'Anthropic', { chatCompletion: 'true' }),
    deployment('embedding-only', 'OpenAI', { embeddings: 'true' }),
    deployment('still-creating', 'OpenAI', { responses: 'true' }, 'Creating'),
    deployment('unknown-capabilities', 'OpenAI', {}),
  ] }
  const core = { call: async (method: string, input: { argv: string[] }) => {
    if (method !== 'machine.exec') throw Error('Discovery must never launch a terminal')
    const argv = input.argv; calls.push(argv)
    if (controls.failure) return { code: 1, stdout: '', stderr: Buffer.from(controls.failure).toString('base64') }
    let result: unknown
    if (argv[1] === 'account') result = { id: subscription, environmentName: controls.cloud }
    else if (argv[3] === 'list') result = [{ name: 'example', resourceGroup: 'example-group' }]
    else { await controls.beforeInventory(); result = controls.malformed ? {} : controls.inventory }
    return { code: 0, stdout: Buffer.from(JSON.stringify(result)).toString('base64'), stderr: '', timed_out: false, truncated: false }
  } } as unknown as CoreSession
  const files = new CoreFiles(core, async () => controls.remote ? 'remote' : undefined)
  const settings = new CoreSettings(store, files, () => [space], id => id, () => {})
  settings.set('azure.codexEndpoint', 'https://example.openai.azure.com/openai/v1')
  settings.set('azure.claudeResource', 'example')
  const row = (kind = 'codex', level = 'all') => settings.sections().find(section => section.name === 'Agents' && section.level === level)!.rows.find(row => row.key === `azure.${kind}Deployment`)!
  return { settings, store, controls, calls, row, close: () => { store.close(); rmSync(home, { recursive: true, force: true }) } }
}

test('deployment discovery offers only ready deployments with the CLI capability and persists an explicit selection', async () => {
  const f = fixture()
  try {
    expect(f.row().discovery?.options).toEqual([])
    expect(f.calls).toEqual([])
    await f.settings.refreshDeployments('codex')
    expect(f.row().discovery?.options).toEqual([{ value: 'code-deployment', label: 'code-deployment · test-model (1)' }])
    expect(f.settings.get('azure.codexDeployment')).toBe('')
    expect(f.row().hint).toContain(subscription)
    f.settings.set('provider.route', 'Azure Foundry')
    f.settings.set('azure.codexDeployment', 'code-deployment')
    expect(f.store.get('settings', 'all\0azure.codexDeployment')).toBe('code-deployment')
    expect(providerPlan('codex', key => f.settings.get(key)).model).toBe('code-deployment')
    expect(f.calls).toHaveLength(3)
    expect(f.calls[2].slice(0, 12)).toEqual(['az', 'cognitiveservices', 'account', 'deployment', 'list', '--name', 'example', '--resource-group', 'example-group', '--subscription', subscription, '--query'])
    await f.settings.refreshDeployments('claude')
    expect(f.row('claude').discovery?.options).toEqual([{ value: 'claude-deployment', label: 'claude-deployment · test-model (1)' }])
  } finally { f.close() }
})

test('discovery pins an explicit subscription without changing the Azure CLI account', async () => {
  const f = fixture()
  try {
    f.settings.set('azure.subscription', subscription, 'm:local')
    await f.settings.refreshDeployments('codex', space.id)
    expect(f.calls[0]).toEqual(['az', 'account', 'show', '--subscription', subscription, '--query', '{id:id,environmentName:environmentName}', '--output', 'json', '--only-show-errors'])
    expect(f.row('codex', space.id).discovery?.options.map(item => item.value)).toEqual(['code-deployment'])
    expect(f.row().discovery?.options).toEqual([])
    expect(() => f.settings.set('azure.subscription', '--debug')).toThrow('UUID')
  } finally { f.close() }
})

test('failed refresh removes old choices, hides raw errors and retains manual selection', async () => {
  const f = fixture()
  try {
    await f.settings.refreshDeployments('codex')
    f.settings.set('azure.codexDeployment', 'manual-deployment')
    f.controls.failure = 'private-token-do-not-display'
    await f.settings.refreshDeployments('codex')
    expect(f.row()).toMatchObject({ value: 'manual-deployment', text: true, discovery: { busy: false, options: [] } })
    expect(f.row().warn).toContain('Azure CLI account')
    expect(JSON.stringify(f.settings.sections())).not.toContain('private-token-do-not-display')
  } finally { f.close() }
})

test('a late discovery response cannot repopulate choices after the endpoint changes', async () => {
  const f = fixture()
  let release!: () => void, entered!: () => void
  const waiting = new Promise<void>(resolve => { entered = resolve })
  f.controls.beforeInventory = () => { entered(); return new Promise<void>(resolve => { release = resolve }) }
  try {
    const pending = f.settings.refreshDeployments('codex')
    await waiting
    expect(f.row().discovery?.busy).toBe(true)
    await f.settings.refreshDeployments('codex') // coalesces duplicate clicks
    expect(f.calls).toHaveLength(3)
    f.settings.set('azure.codexEndpoint', 'https://different.openai.azure.com/openai/v1')
    release(); await pending
    expect(f.row().discovery).toMatchObject({ busy: false, options: [] })
    expect(f.row().hint).not.toContain(subscription)
  } finally { f.close() }
})

test('discovery refuses remote hosts and additional Azure clouds without listing deployments', async () => {
  const f = fixture()
  try {
    f.controls.remote = true
    await f.settings.refreshDeployments('codex')
    expect(f.calls).toEqual([])
    expect(f.row().warn).toContain('local execution host')
    f.controls.remote = false; f.controls.cloud = 'AzureUSGovernment'
    await f.settings.refreshDeployments('codex')
    expect(f.calls).toHaveLength(1)
    expect(f.row().warn).toContain('public cloud only')
  } finally { f.close() }
})

test('empty inventory and unreadable inventory have distinct outcomes and never select a replacement', async () => {
  const f = fixture()
  try {
    f.controls.inventory = []
    await f.settings.refreshDeployments('codex')
    expect(f.row().hint).toContain('0 matching deployments')
    expect(f.row().warn).toBeUndefined()
    f.controls.malformed = true
    await f.settings.refreshDeployments('codex')
    expect(f.row().warn).toContain('unreadable deployment inventory')
    expect(f.settings.get('azure.codexDeployment')).toBe('')
  } finally { f.close() }
})
