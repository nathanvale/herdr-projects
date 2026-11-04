import type { CoreFiles } from './files.ts'
import type { AgentKind } from './model.ts'
import type { SettingRow } from '../../shared/types.ts'

/** Read-only ARM discovery through the execution host's existing Azure CLI login. */
export async function discoverDeployments(files: CoreFiles, machine: string, kind: AgentKind, resource: string, subscription: string) {
  let remote: string | undefined
  try { remote = await files.route(machine) } catch { throw Error('Cannot reach the execution host. Restore its core connection before refreshing deployments.') }
  if (remote) throw Error('Azure discovery currently supports the local execution host only. Enter the deployment manually for other hosts.')
  const run = async (args: string[], repair: string) => {
    try {
      const bytes = await files.exec(machine, ['az', ...args, '--output', 'json', '--only-show-errors'], undefined, undefined, 30)
      return JSON.parse(bytes.toString('utf8'))
    } catch { throw Error(repair) }
  }
  const account = await run(['account', 'show', ...(subscription ? ['--subscription', subscription] : []), '--query', '{id:id,environmentName:environmentName}'], 'Cannot read the Azure CLI account. Check that az is installed and signed in on the execution host, and that the subscription is accessible. Manual entry is still available.')
  if (account?.environmentName !== 'AzureCloud') throw Error('Discovery supports Azure public cloud only. The host Azure cloud and login were not changed.')
  if (typeof account.id !== 'string' || !/^[0-9a-f-]{36}$/i.test(account.id)) throw Error('Azure CLI returned an invalid subscription identity. Check its account configuration.')
  const scope = ['--subscription', account.id]
  const accounts = await run(['cognitiveservices', 'account', 'list', ...scope, '--query', '[].{name:name,resourceGroup:resourceGroup}'], 'Cannot list Azure resources. Check Cognitive Services resource read access in this subscription, or enter the deployment manually.')
  if (!Array.isArray(accounts)) throw Error('Azure returned an unreadable resource inventory. Try refreshing again.')
  const matches = accounts.filter(item => typeof item?.name === 'string' && item.name.toLowerCase() === resource.toLowerCase())
  if (matches.length !== 1 || typeof matches[0].resourceGroup !== 'string') throw Error('The configured resource was not uniquely found in this subscription. Check the resource and subscription, or enter the deployment manually.')
  const inventory = await run(['cognitiveservices', 'account', 'deployment', 'list', '--name', resource, '--resource-group', matches[0].resourceGroup, ...scope, '--query', '[].{name:name,properties:{model:properties.model,provisioningState:properties.provisioningState,capabilities:properties.capabilities}}'], 'Cannot list Azure deployments. Check deployment read access and connectivity, then refresh. Manual entry is still available.')
  if (!Array.isArray(inventory)) throw Error('Azure returned an unreadable deployment inventory. Try refreshing again.')
  const models: Record<string, string> = {}
  const options: NonNullable<SettingRow['discovery']>['options'] = []
  for (const item of inventory) {
    const p = item?.properties, model = p?.model
    const capability = p?.capabilities?.[kind === 'codex' ? 'responses' : 'chatCompletion']
    const supported = model?.format === (kind === 'codex' ? 'OpenAI' : 'Anthropic') && (capability === 'true' || capability === true)
    if (!supported || p?.provisioningState !== 'Succeeded' || typeof item.name !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(item.name) || typeof model?.name !== 'string') continue
    models[item.name] = model.name
    options.push({ value: item.name, label: `${item.name} · ${model.name}${model.version ? ` (${String(model.version).slice(0, 64)})` : ''}` })
  }
  options.sort((a, b) => a.value.localeCompare(b.value))
  return { options, models, subscription: account.id as string }
}
