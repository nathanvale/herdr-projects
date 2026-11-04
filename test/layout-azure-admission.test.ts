// Real browser + production settings/agent code. The core boundary is a fake;
// no live state, native CLI, credential probe or model request is involved.
import { afterAll, describe, expect, test } from 'bun:test'
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CoreSource } from '../server/core/source.ts'
import { startApp } from '../server/app.ts'
import { launch } from './chromium.ts'
import { builtScreen } from './web.ts'

const browser = await launch()
afterAll(async () => { await browser?.close() })

describe.skipIf(!browser)('Azure admission through browser settings', () => {
  test('a connection edit invalidates an admitted start and requires fresh validation', async () => {
    const home = mkdtempSync(join(tmpdir(), 'shep-browser-admission-'))
    const source = new CoreSource({ home, port: 0, socket: '/unused', session: 'test', binary: 'hc', plugins: false })
    source.route = async () => undefined
    source.core.current.connected = true
    const space = { id: 'space', machine: source.localMachineId(), name: 'Isolated admission test', folder: '/unused', base: 'main', prefix: 'EX', mode: 'regular' as const, added: 1 }
    source.store.set('space', space.id, space)
    source.settings.set('provider.route', 'Azure Foundry')
    source.settings.set('azure.claudeResource', 'example-before')
    source.settings.set('azure.claudeDeployment', 'claude-sonnet-5-5')
    const runs: Record<string, unknown>[] = []
    source.core.call = async <T>(method: string, params: Record<string, unknown> = {}) => {
      if (method !== 'terminal.run') throw Error('Unexpected core request: ' + method)
      runs.push(params)
      return { address: 't-fake', state: 'live', pid: 1, labels: params.labels } as T
    }
    const server = startApp({ source, dist: await builtScreen(), host: '127.0.0.1', port: 0 })
    const page = await browser!.newPage({ viewport: { width: 1280, height: 900 } })
    try {
      const prepared = await source.agents.preflight(space, space.id, 'claude')
      source.agents.admit(prepared)
      await page.goto(`http://127.0.0.1:${server.port}/?place=space`)
      await page.getByRole('button', { name: 'Settings', exact: true }).click()
      const settings = page.getByRole('region', { name: 'Settings' })
      await settings.getByRole('button', { name: 'Agents', exact: true }).click()
      const resource = settings.getByRole('textbox', { name: 'Claude Azure resource', exact: true })
      const saved = page.waitForResponse(response => response.url().endsWith('/api/action') && response.request().method() === 'POST' && response.request().postDataJSON()?.key === 'azure.claudeResource')
      await resource.fill('example-after')
      await resource.press('Tab')
      expect((await saved).ok()).toBe(true)
      expect(source.settings.get('azure.claudeResource')).toBe('example-after')
      await expect(source.agents.launch(space, space.id, 'claude', 'Wait', { prepared })).rejects.toThrow('fresh validation')
      expect(runs).toEqual([])
      expect(source.agents.get(space.id)).toBeUndefined()
      expect(source.mailbox.active()).toEqual([])
      mkdirSync('test-results', { recursive: true })
      await page.screenshot({ path: 'test-results/azure-admission-settings.png', fullPage: true })
      // The same entry point accepts a newly validated plan, exactly once.
      const fresh = await source.agents.preflight(space, space.id, 'claude')
      await source.agents.launch(space, space.id, 'claude', 'Wait', { prepared: fresh })
      expect(runs).toHaveLength(1)
    } finally {
      await page.close(); server.stop(true); source.stop(); source.mailbox.close(); source.store.close()
      rmSync(home, { recursive: true, force: true })
    }
  }, 30_000)
})
