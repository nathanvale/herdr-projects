// Minimal restart dialogs for both chat roles; only GitHub runs these browser tests.
import { describe, expect, test } from 'bun:test'
import { layout } from './layout.ts'

const { browser, world, server } = await layout({ everything: true })

describe.skipIf(!browser)('restarting an agent', () => {
  test('Settings mismatches show no banner and do not restart either role', async () => {
    const p = world.snapshot().places.find((x) => x.id === world.tasks.find(task => task.id === 'GTM-17')!.place)!
    for (const task of [false, true]) {
      const key = task ? 'GTM-17/Agent' : p.chat
      const c = world.chats[key]
      c.restart = { on: 'Claude Code', want: 'Codex' }
      const before = JSON.stringify(c.agent)
      const cards = c.messages.filter((m) => m.card?.restart).length
      const page = await browser!.newPage({ viewport: { width: 390, height: 844 } })
      await page.goto(`http://127.0.0.1:${server!.port}/?place=${encodeURIComponent(p.id)}${task ? '&task=GTM-17' : ''}`)
      const controls = page.locator('[data-agent-controls]:visible').last()
      await page.locator('[data-composer]:visible').last().waitFor()
      expect(await controls.count()).toBe(0)
      await page.locator('[data-composer]:visible button[aria-label="Attach files and more"]').last().click()
      await controls.waitFor()
      expect(await page.locator('[data-restart-hint]').count()).toBe(0)
      expect(await controls.getByRole('menuitem').count()).toBe(4)
      expect(JSON.stringify(c.agent)).toBe(before)
      expect(c.messages.filter((m) => m.card?.restart).length).toBe(cards)
      await page.close()
    }
  }, 30_000)

  test("a task's ⋯ opens the sheet: Settings' CLI picked, another CLI offers its models; Restart posts the card", async () => {
    const page = await browser!.newPage({ viewport: { width: 1440, height: 900 } })
    await page.goto(`http://127.0.0.1:${server!.port}/?place=${encodeURIComponent('p:vm-str:gtm')}`)
    const row = page.locator('section[aria-label="Tasks"] li', { hasText: 'GTM-17' })
    await row.hover()
    await row.getByRole('button', { name: 'More for this task' }).click()
    await page.getByRole('menuitem', { name: 'Restart agent…' }).click()
    const sheet = page.getByRole('alertdialog', { name: 'Restart GTM-17 agent?' })
    await sheet.waitFor()
    await sheet.locator('[data-restart]').waitFor()
    expect(await sheet.textContent()).not.toMatch(/Recorded launch|Settings for|unknown|CLI|resumes|meanwhile/)
    expect(await sheet.getByRole('switch').count()).toBe(0)
    await sheet.getByRole('button', { name: /^Agent: / }).click()
    await page.getByRole('menuitemradio', { name: 'Codex' }).click()
    expect(await sheet.textContent()).toContain('Codex starts a new session with this chat, its instructions and branch.')
    await sheet.getByRole('button', { name: /^Model: / }).click()
    await page.getByRole('menuitemradio', { name: 'GPT-6-Sol', exact: true }).click()
    await sheet.getByRole('button', { name: /^Effort: / }).click()
    await page.getByRole('menuitemradio', { name: 'High', exact: true }).click()
    await sheet.getByRole('button', { name: 'Restart', exact: true }).click()
    await sheet.waitFor({ state: 'detached' })
    expect(world.chats['GTM-17/Agent'].messages.at(-1)?.card).toMatchObject({ restart: true, text: 'Restarted on Codex (GPT-6-Sol, high)' })
    await page.close()
  }, 30_000)

  test('/model in a chat opens Restart for this agent, its model picked; nothing reaches the CLI', async () => {
    const p = world.snapshot().places.find((x) => x.id === world.tasks.find(task => task.id === 'GTM-17')!.place)!
    const sent = world.chats[p.chat].messages.length
    const page = await browser!.newPage({ viewport: { width: 1280, height: 800 } })
    await page.goto(`http://127.0.0.1:${server!.port}/?place=${encodeURIComponent(p.id)}`)
    const box = page.locator('[data-composer]:visible textarea').last()
    await box.fill('/model sonnet')
    await box.press('Enter')
    const sheet = page.getByRole('alertdialog', { name: 'Restart coordinator?' })
    await sheet.locator('[data-restart]').waitFor()
    expect(await sheet.textContent()).toContain('Changes this agent only')
    await sheet.getByRole('button', { name: /^Model: Sonnet/ }).waitFor()
    expect(await box.inputValue()).toBe('')
    expect(await sheet.getByRole('switch').count()).toBe(1)
    expect(await sheet.getByRole('switch').getAttribute('aria-checked')).toBe('false')
    await sheet.getByRole('button', { name: 'Cancel' }).click()
    await sheet.waitFor({ state: 'detached' })
    expect(world.chats[p.chat].messages.length).toBe(sent)
    await page.close()
  }, 30_000)

  test('the sheet fits a phone, and Cancel leaves the agent as it was', async () => {
    const p = world.snapshot().places.find((x) => x.id === world.tasks.find(task => task.id === 'GTM-17')!.place)!
    const ctx = await browser!.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })
    const page = await ctx.newPage()
    await page.goto(`http://127.0.0.1:${server!.port}/?place=${encodeURIComponent(p.id)}`)
    await page.getByRole('button', { name: /^Menu/ }).click()
    await page.getByRole('menuitem', { name: 'Restart agent…' }).click()
    const sheet = page.getByRole('alertdialog', { name: 'Restart coordinator?' })
    await sheet.locator('[data-restart]').waitFor()
    expect(await sheet.textContent()).not.toMatch(/Recorded launch|Settings for|unknown|CLI|resumes|meanwhile/)
    expect(await sheet.getByRole('switch').count()).toBe(0)
    const box = (await sheet.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(390)
    const cards = world.chats[p.chat].messages.filter((m) => m.card?.restart).length
    await sheet.getByRole('button', { name: 'Cancel' }).click()
    await sheet.waitFor({ state: 'detached' })
    expect(world.chats[p.chat].messages.filter((m) => m.card?.restart).length).toBe(cards)
    await ctx.close()
  }, 30_000)

  test('saving defaults is optional, scoped to the role, and sent only when selected', async () => {
    const p = world.snapshot().places.find((x) => x.id === world.tasks.find(task => task.id === 'GTM-17')!.place)!
    for (const task of [false, true]) {
      const chat = task ? 'GTM-17/Agent' : p.chat
      world.chats[chat].agent = { kind: 'codex' }
      world.chats[chat].cli = 'Codex'
      world.chats[chat].restart = undefined
      const page = await browser!.newPage({ viewport: { width: 390, height: 844 } })
      let restart: unknown
      page.on('request', (r) => {
        if (r.url().endsWith('/api/action') && r.method() === 'POST') {
          const action = r.postDataJSON()
          if (action.type === 'restart') restart = action
        }
      })
      await page.goto(`http://127.0.0.1:${server!.port}/?place=${encodeURIComponent(p.id)}${task ? '&task=GTM-17' : ''}`)
      for (const save of [false, true]) {
        await page.locator('[data-composer]:visible button[aria-label="Attach files and more"]').last().click()
        await page.locator('[data-agent-controls]:visible').last().getByRole('menuitem', { name: /^Model:/ }).click()
        const sheet = page.getByRole('alertdialog')
        await sheet.locator('[data-restart]').waitFor()
        if (!save) expect(await sheet.getByRole('switch').count()).toBe(0)
        await sheet.getByRole('button', { name: /^Effort: / }).click()
        await page.getByRole('menuitemradio', { name: save ? 'Low' : 'High', exact: true }).click()
        const toggle = sheet.getByRole('switch')
        expect(await toggle.count()).toBe(1)
        expect(await toggle.getAttribute('aria-label')).toBe(`Use for future ${task ? 'task agents' : 'coordinators'} in ${p.name}`)
        expect(await toggle.getAttribute('aria-checked')).toBe('false')
        if (save) await toggle.click()
        await sheet.getByRole('button', { name: 'Restart', exact: true }).click()
        await sheet.waitFor({ state: 'detached' })
        expect(restart).toMatchObject({ type: 'restart', chat, kind: 'codex', model: '', effort: save ? 'low' : 'high', save })
      }
      await page.close()
    }
  }, 30_000)

  test('machine-qualified task IDs retain their header PR and restart menu', async () => {
    const original = world.tasks.find(task => task.id === 'GTM-17')!
    const id = 'box/GTM-901', chat = `${id}/Agent`
    world.tasks.push({ ...original, id, status: 'work', pr: { number: 901, url: 'https://github.com/example/repo/pull/901' }, agent: { ...original.agent!, chat } })
    world.chats[chat] = { ...world.chats['GTM-17/Agent'], key: chat }
    const page = await browser!.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await page.goto(`http://127.0.0.1:${server!.port}/?place=${encodeURIComponent(original.place)}&task=${encodeURIComponent(id)}`)
      await page.locator('[data-pr="901"]').waitFor()
      await page.getByRole('button', { name: 'More', exact: true }).click()
      await page.getByRole('menuitem', { name: 'Restart agent…', exact: true }).click()
      await page.getByRole('alertdialog').locator('[data-restart]').waitFor()
      expect(await page.getByRole('alertdialog').textContent()).toContain(id)
    } finally { await page.close(); world.tasks = world.tasks.filter(task => task.id !== id); delete world.chats[chat] }
  })

})

describe.skipIf(!browser)('Azure new-start selection', () => {
  test('task and coordinator pickers save without restarting; existing conversations are locked', async () => {
    const original = world.act.bind(world), requests: import('../shared/types.ts').Action[] = []
    const place = world.snapshot().places.find(p => p.id === world.tasks.find(task => task.id === 'GTM-17')!.place)!
    let locked = false, inventory = true
    world.act = async action => {
      requests.push(action)
      if (action.type === 'restart-info') return { ok: true, info: {
        role: action.chat.includes('/Agent') ? 'task' : 'coordinator', onKnown: locked,
        on: { kind: 'claude', model: 'claude-sonnet-5-5', effort: 'high' }, onWords: 'Claude Code', working: false,
        want: { kind: 'claude', deployment: 'claude-sonnet-5-5', effort: 'high' },
        azure: { token: 'selection-version', level: place.id, locked, reason: locked ? 'Azure model selection is for new starts only.' : undefined },
        clis: [{ kind: 'claude', name: 'Claude Code', models: [{ id: 'claude-sonnet-5-5', label: 'Sonnet 5.5', efforts: ['low', 'high'] }, { id: 'claude-haiku-5-5', label: 'Haiku 5.5', efforts: ['low'] }], azure: { deployment: 'claude-sonnet-5-5', busy: false, refreshKey: 'azure.claudeRefresh',
          options: inventory ? [{ value: 'claude-sonnet-5-5', label: 'Sonnet deployment', efforts: ['low', 'high'] }, { value: 'claude-haiku-5-5', label: 'Haiku deployment', efforts: ['low'] }] : [] } }]
      } }
      if (action.type === 'select-agent') return { ok: true }
      if (action.type === 'restart') throw Error('Azure selection must never restart')
      return original(action)
    }
    try {
      for (const task of [false, true]) {
        const page = await browser!.newPage({ viewport: { width: 390, height: 844 } })
        try {
          await page.goto(`http://127.0.0.1:${server!.port}/?place=${encodeURIComponent(place.id)}${task ? '&task=GTM-17' : ''}`)
          const openModel = async () => {
            await page.locator('[data-agent-line]:visible').last().click()
            await page.locator('[data-agent-controls]:visible').last().getByRole('menuitem', { name: /^Model:/ }).click()
          }
          await openModel()
          const sheet = page.getByRole('alertdialog', { name: 'Azure Foundry model' })
          await sheet.waitFor()
          await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Azure agent')
          expect(await sheet.getByLabel('Azure agent', { exact: true }).evaluate(element => element === document.activeElement)).toBe(true)
          await page.keyboard.press('Tab')
          expect(await sheet.getByLabel('Azure deployment', { exact: true }).evaluate(element => element === document.activeElement)).toBe(true)
          await sheet.getByLabel('Azure deployment', { exact: true }).selectOption('claude-haiku-5-5')
          await sheet.getByLabel('Azure effort', { exact: true }).selectOption('low')
          await sheet.getByRole('button', { name: 'Save for new start' }).click()
          await sheet.waitFor({ state: 'detached' })
          expect(requests.at(-1)).toMatchObject({ type: 'select-agent', chat: task ? 'GTM-17/Agent' : place.chat, deployment: 'claude-haiku-5-5', effort: 'low', token: 'selection-version' })
          locked = true
          await openModel()
          await sheet.waitFor()
          await page.waitForFunction(() => document.activeElement?.textContent === 'Cancel')
          expect(await sheet.getByRole('button', { name: 'Cancel', exact: true }).evaluate(element => element === document.activeElement)).toBe(true)
          expect(await sheet.getByRole('button', { name: 'Save for new start' }).isDisabled()).toBe(true)
          expect(await sheet.getByLabel('Azure deployment', { exact: true }).isDisabled()).toBe(true)
          expect(await sheet.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
          await sheet.getByRole('button', { name: 'Cancel', exact: true }).click()
          locked = false; inventory = false
          await openModel(); await sheet.waitFor()
          // A saved known model's effort survives without discovery inventory.
          expect(await sheet.getByLabel('Azure effort', { exact: true }).inputValue()).toBe('high')
          expect(await sheet.getByRole('button', { name: 'Save for new start' }).isEnabled()).toBe(true)
          await sheet.getByLabel('Azure deployment name', { exact: true }).fill('unverified-team-alias')
          expect(await sheet.getByLabel('Azure effort', { exact: true }).locator('option').allTextContents()).toEqual(['Default'])
          await sheet.getByLabel('Azure deployment name', { exact: true }).fill('claude-sonnet-5-5')
          await sheet.getByLabel('Azure effort', { exact: true }).selectOption('high')
          await sheet.getByRole('button', { name: 'Save for new start' }).click()
          await sheet.waitFor({ state: 'detached' })
          expect(requests.at(-1)).toMatchObject({ type: 'select-agent', deployment: 'claude-sonnet-5-5', effort: 'high' })
          inventory = true
        } finally { await page.close() }
      }
      expect(requests.filter(action => action.type === 'restart')).toEqual([])
      expect(requests.filter(action => action.type === 'select-agent')).toHaveLength(4)
    } finally { world.act = original }
  }, 30_000)
})
