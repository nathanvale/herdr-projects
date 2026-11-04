// Native provider configuration, composed per launch without editing CLI homes.
import { createHash } from 'node:crypto'
import type { AgentKind } from './model.ts'
import type { SettingRow } from '../../shared/types.ts'

export const PROVIDER_ROWS: SettingRow[] = [
  { group: 'Connection', key: 'provider.route', label: 'Provider', value: 'Personal', options: ['Personal', 'Azure Foundry'] },
  { group: 'Azure Foundry', key: 'azure.claudeResource', label: 'Claude Azure resource', value: '', text: true },
  { group: 'Azure Foundry', key: 'azure.claudeDeployment', label: 'Claude deployment', value: '', text: true },
  { group: 'Azure Foundry', key: 'azure.codexEndpoint', label: 'Codex Azure endpoint', value: '', text: true },
  { group: 'Azure Foundry', key: 'azure.codexDeployment', label: 'Codex deployment', value: '', text: true },
]
export interface ProviderBinding { route: 'personal' | 'azure-foundry'; fingerprint: string }
export interface ProviderPlan {
  binding: ProviderBinding
  model?: string
  claudeEnv: Record<string, string>
  env: Record<string, string | null>
  codexArgs: string[]
}
const CLEAN = ['CLAUDE_CODE_USE_FOUNDRY', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_FOUNDRY_API_KEY', 'ANTHROPIC_FOUNDRY_AUTH_TOKEN', 'ANTHROPIC_FOUNDRY_RESOURCE', 'ANTHROPIC_FOUNDRY_BASE_URL', 'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL', 'OPENAI_BASE_URL', 'OPENAI_API_KEY', 'AZURE_OPENAI_API_KEY']
const override = (key: string, value: string | boolean) => ['-c', `${key}=${JSON.stringify(value)}`]

/** Credentials stay in the launch environment, never settings, argv, or the binding. */
export function providerPlan(kind: AgentKind, get: (key: string) => string, environment: NodeJS.ProcessEnv): ProviderPlan {
  const route = get('provider.route') || 'Personal'
  if (!['Personal', 'Azure Foundry'].includes(route)) throw Error('Choose Personal or Azure Foundry')
  const env: Record<string, string | null> = Object.fromEntries(CLEAN.map(key => [key, null]))
  const claudeEnv = Object.fromEntries(CLEAN.map(key => [key, '']))
  const binding: ProviderBinding = { route: 'personal', fingerprint: 'personal' }
  if (route === 'Personal') return { binding, env, claudeEnv, codexArgs: [...override('model_provider', 'openai'), ...override('openai_base_url', 'https://api.openai.com/v1'), ...override('model_providers.openai.requires_openai_auth', true), ...override('model_providers.openai.base_url', 'https://api.openai.com/v1')] }
  const model = get(kind === 'claude' ? 'azure.claudeDeployment' : 'azure.codexDeployment').trim()
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(model)) throw Error('Set an explicit Azure deployment name for this CLI in Agents settings')
  const endpoint = get(kind === 'claude' ? 'azure.claudeResource' : 'azure.codexEndpoint').trim()
  const codexArgs: string[] = []
  if (kind === 'claude') {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9-]{1,62}$/.test(endpoint)) throw Error('Set the Claude Azure resource name, not a URL')
    Object.assign(claudeEnv, { CLAUDE_CODE_USE_FOUNDRY: '1', ANTHROPIC_FOUNDRY_RESOURCE: endpoint, ANTHROPIC_DEFAULT_OPUS_MODEL: model, ANTHROPIC_DEFAULT_SONNET_MODEL: model, ANTHROPIC_DEFAULT_HAIKU_MODEL: model })
    Object.assign(env, claudeEnv)
    // Entra uses the native Azure SDK credential chain. No copied access tokens.
  } else {
    let url: URL
    try { url = new URL(endpoint) } catch { throw Error('Set a valid HTTPS Azure OpenAI v1 endpoint') }
    if (url.protocol !== 'https:' || !url.hostname.endsWith('.openai.azure.com') || url.port || url.username || url.password || url.search || url.hash || !/^\/openai\/v1\/?$/.test(url.pathname)) throw Error('Use https://RESOURCE.openai.azure.com/openai/v1 without credentials or query parameters')
    if (!environment.AZURE_OPENAI_API_KEY) throw Error('Azure Codex requires AZURE_OPENAI_API_KEY supplied by the host credential owner')
    env.AZURE_OPENAI_API_KEY = environment.AZURE_OPENAI_API_KEY
    codexArgs.push(...override('model_provider', 'shepherdr_azure'), ...override('model_providers.shepherdr_azure.name', 'Azure Foundry'), ...override('model_providers.shepherdr_azure.base_url', endpoint.replace(/\/$/, '')), ...override('model_providers.shepherdr_azure.env_key', 'AZURE_OPENAI_API_KEY'), ...override('model_providers.shepherdr_azure.wire_api', 'responses'), ...override('model_providers.shepherdr_azure.requires_openai_auth', false))
  }
  binding.route = 'azure-foundry'
  binding.fingerprint = createHash('sha256').update(JSON.stringify([kind, endpoint, model])).digest('hex')
  return { binding, model, env, claudeEnv, codexArgs }
}
