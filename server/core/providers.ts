// Native provider configuration, composed per launch without editing CLI homes.
import { createHash } from 'node:crypto'
import type { AgentKind } from './model.ts'
import type { SettingRow } from '../../shared/types.ts'

export const PROVIDER_ROWS: SettingRow[] = [
  { group: 'Connection', key: 'provider.route', label: 'Provider', value: 'Personal', options: ['Personal', 'Azure Foundry'] },
  { group: 'Azure Foundry', key: 'azure.claudeResource', label: 'Claude Azure resource', value: '', text: true },
  { group: 'Azure Foundry', key: 'azure.claudeDeployment', label: 'Claude deployment', value: '', text: true },
  { group: 'Azure Foundry', key: 'azure.claudeAuth', label: 'Claude authentication', value: 'Entra ID', options: ['Entra ID', 'API key', 'Bearer token'], warn: 'Entra ID uses the native Azure SDK credential chain. API key and bearer token use the execution host environment. Never enter credentials in settings.' },
  { group: 'Azure Foundry', key: 'azure.codexEndpoint', label: 'Codex Azure endpoint', value: '', text: true },
  { group: 'Azure Foundry', key: 'azure.codexDeployment', label: 'Codex deployment', value: '', text: true },
  { group: 'Azure Foundry', key: 'azure.codexAuth', label: 'Codex authentication', value: 'API key', options: ['API key'], warn: 'Requires AZURE_OPENAI_API_KEY in the execution host environment. Microsoft does not currently support Entra ID for Codex.' },
]
export interface ProviderBinding { route: 'personal' | 'azure-foundry'; fingerprint: string }
export interface ProviderPlan {
  binding: ProviderBinding
  model?: string
  /** A variable name only. Its value is inherited from core, never sent in RPC. */
  credential?: string
  claudeEnv: Record<string, string>
  env: Record<string, string>
  codexArgs: string[]
}
const CLAUDE_ENV = ['CLAUDE_CODE_USE_FOUNDRY', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_FOUNDRY_API_KEY', 'ANTHROPIC_FOUNDRY_AUTH_TOKEN', 'ANTHROPIC_FOUNDRY_RESOURCE', 'ANTHROPIC_FOUNDRY_BASE_URL', 'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL']
const DEPLOYMENT = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/
const RESOURCE = /^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,62}[a-zA-Z0-9])?$/
const ENDPOINT_ERROR = 'Use https://RESOURCE.openai.azure.com/openai/v1 without credentials or query parameters'

function codexEndpoint(value: string): string {
  let url: URL
  try { url = new URL(value) } catch { throw Error(ENDPOINT_ERROR) }
  const resource = url.hostname.slice(0, -'.openai.azure.com'.length)
  if (url.protocol !== 'https:' || !url.hostname.endsWith('.openai.azure.com') || !RESOURCE.test(resource) || url.port || url.username || url.password || url.search || url.hash || !/^\/openai\/v1\/?$/.test(url.pathname)) throw Error(ENDPOINT_ERROR)
  // Compare the original spelling too: URL parsing must not hide credentials or traversal.
  const canonical = `https://${url.hostname}/openai/v1`
  if (value !== canonical && value !== `${canonical}/`) throw Error(ENDPOINT_ERROR)
  return canonical
}

/** Validate nonsecret routing fields before saving as well as before launch. Empty permits setup in steps. */
export function providerSetting(key: string, value: string): string {
  const clean = value.trim()
  if (!clean) return clean
  if (key === 'azure.codexEndpoint') return codexEndpoint(clean)
  if (key === 'azure.claudeResource' && !RESOURCE.test(clean)) throw Error('Set the Claude Azure resource name, not a URL')
  if (['azure.claudeDeployment', 'azure.codexDeployment'].includes(key) && !DEPLOYMENT.test(clean)) throw Error('Set an explicit Azure deployment name for this CLI in Agents settings')
  return clean
}

/** No credential values enter this module. Personal is a compatibility-preserving pass-through. */
export function providerPlan(kind: AgentKind, get: (key: string) => string): ProviderPlan {
  const route = get('provider.route') || 'Personal'
  if (!['Personal', 'Azure Foundry'].includes(route)) throw Error('Choose Personal or Azure Foundry')
  if (route === 'Personal') return { binding: { route: 'personal', fingerprint: 'personal' }, env: {}, claudeEnv: {}, codexArgs: [] }
  const model = providerSetting(`azure.${kind}Deployment`, get(`azure.${kind}Deployment`))
  if (!model) throw Error('Set an explicit Azure deployment name for this CLI in Agents settings')
  const endpoint = providerSetting(kind === 'claude' ? 'azure.claudeResource' : 'azure.codexEndpoint', get(kind === 'claude' ? 'azure.claudeResource' : 'azure.codexEndpoint'))
  if (!endpoint) throw Error(kind === 'claude' ? 'Set the Claude Azure resource name, not a URL' : ENDPOINT_ERROR)
  const auth = get(`azure.${kind}Auth`) || (kind === 'claude' ? 'Entra ID' : 'API key')
  const fingerprint = createHash('sha256').update(JSON.stringify([kind, endpoint, model, auth])).digest('hex')
  let credential: string | undefined
  const env: Record<string, string> = {}, claudeEnv: Record<string, string> = {}, codexArgs: string[] = []
  if (kind === 'claude') {
    if (!['Entra ID', 'API key', 'Bearer token'].includes(auth)) throw Error('Choose a supported Claude Azure authentication method')
    credential = auth === 'API key' ? 'ANTHROPIC_FOUNDRY_API_KEY' : auth === 'Bearer token' ? 'ANTHROPIC_FOUNDRY_AUTH_TOKEN' : undefined
    Object.assign(claudeEnv, Object.fromEntries(CLAUDE_ENV.filter(key => key !== credential).map(key => [key, ''])), {
      CLAUDE_CODE_USE_FOUNDRY: '1', ANTHROPIC_FOUNDRY_RESOURCE: endpoint,
      ANTHROPIC_DEFAULT_OPUS_MODEL: model, ANTHROPIC_DEFAULT_SONNET_MODEL: model, ANTHROPIC_DEFAULT_HAIKU_MODEL: model,
    })
    Object.assign(env, claudeEnv)
  } else {
    if (auth !== 'API key') throw Error('Codex Azure supports API key authentication only; Entra ID is not supported by Microsoft\'s Codex guide')
    credential = 'AZURE_OPENAI_API_KEY'
    Object.assign(env, { OPENAI_BASE_URL: '', OPENAI_API_KEY: '' })
    // Codex merges provider tables. A reserved, configuration-specific name avoids reusing
    // an operator's normal `azure` provider, while remaining stable for session resume.
    const id = `shepherdr_azure_${fingerprint}`
    const fields = { name: 'Azure Foundry', base_url: endpoint, env_key: credential, wire_api: 'responses', requires_openai_auth: false }
    codexArgs.push('-c', `model_provider=${JSON.stringify(id)}`, '-c', `model_providers.${id}={${Object.entries(fields).map(([key, value]) => `${key}=${JSON.stringify(value)}`).join(',')}}`)
  }
  return { binding: { route: 'azure-foundry', fingerprint }, model, credential, env, claudeEnv, codexArgs }
}
