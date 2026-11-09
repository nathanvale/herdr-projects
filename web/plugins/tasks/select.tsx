// A task's new-start choice (A2), in its row menu while it hasn't started: the CLI its first agent starts on, and on
// Azure Foundry its deployment (what Settings' Refresh found, or typed) and its effort (levels only where the
// deployment's model is known; otherwise Default). herdr-task keeps it (herdr-task select, through the service's
// service/selections.ts): Save starts nothing, sends no prompt and keeps the task's holds and place; it carries the
// revision it was shown at, so a choice or a provider setting changed since refuses. A task with a recorded
// conversation shows its choice locked.
import clsx from 'clsx'
import { useEffect, useState } from 'react'
import type { Task } from '@shared/types.ts'
import { act } from '@client/kernel.ts'
import { field, Ghost, Primary, Tab, Tabs } from '@client/ui.tsx'
import * as AG from '@core/agents.js'

const { NAMES, levelName } = AG as unknown as { NAMES: Record<string, string>; levelName: (e: string | null) => string | null }
type Model = { id: string; name: string; efforts: string[] }
type View = {
  ok?: boolean; error?: string; locked: boolean; route: string; revision: string
  /** what it follows without a choice of its own: Settings' Workers CLI */
  inherit?: { agent: string }
  selection: { agent: string | null; deployment: string | null; effort: string | null }
  clis: Record<string, { routing: string; deployment: string | null; problem: string | null }>
  menus: Record<string, { models: Model[] }> | null
}
// Personal: each CLI's usual levels (its model's own aren't known before it starts)
const LEVELS: Record<string, string[]> = { claude: ['low', 'medium', 'high', 'xhigh', 'max'], codex: ['low', 'medium', 'high', 'xhigh'] }
export const WORDS = {
  item: 'Model for its start…',
  title: 'For its first start',
  locked: 'Locked: its recorded conversation keeps the provider, deployment and effort it started on.',
  deployment: 'Deployment',
  typed: 'or type its name',
  effort: 'Effort',
  dflt: 'Default',
  save: 'Save',
  defaults: 'Use configured defaults',
  saved: 'Saved. Nothing was started.',
}

export function TaskSelect({ task, done }: { task: Task; done: () => void }) {
  const chat = task.agent?.chat ?? `${task.id}/Agent`
  const [v, setV] = useState<View | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [agent, setAgent] = useState('claude')
  const [dep, setDep] = useState('')
  const [effort, setEffort] = useState('')
  const show = (r: View) => {
    setV(r)
    setAgent(r.selection.agent ?? r.inherit?.agent ?? 'claude')
    setDep(r.selection.deployment ?? '')
    setEffort(r.selection.effort ?? '')
  }
  useEffect(() => {
    void (act({ type: 'task-select', chat } as never) as Promise<View>).then((r) => (r?.ok === false ? setError(r.error ?? 'Not shown.') : show(r)), (e: Error) => setError(e.message))
  }, [chat])
  const save = async (change: Record<string, unknown>) => {
    if (!v) return
    setBusy(true)
    setError('')
    const r = (await act({ type: 'task-select', chat, change: { ...change, revision: v.revision } } as never).catch((e: Error) => ({ ok: false, error: e.message }))) as View
    setBusy(false)
    if (r?.ok === false) return setError(r.error ?? 'Not saved.')
    done()
  }
  if (!v) return <p className="px-2 py-1.5 text-[0.8125rem] text-fg2" role={error ? 'alert' : undefined}>{error || '…'}</p>
  const azure = v.route === 'azure-foundry'
  const models = v.menus?.[agent]?.models ?? []
  const levels = azure ? (models.find((m) => m.id === dep)?.efforts ?? []) : LEVELS[agent] ?? []
  const problem = azure ? v.clis[agent]?.problem : null
  return (
    <div className="flex w-72 max-w-full flex-col gap-2 px-2 py-1.5 text-[0.8125rem] phone:px-3">
      <p className="font-medium text-fg">{WORDS.title}</p>
      {v.locked ? <p className="text-fg2">{WORDS.locked}</p> : null}
      <Tabs label="CLI">
        {Object.keys(NAMES).map((k) => (
          <Tab key={k} on={agent === k} disabled={v.locked || busy} onClick={() => { if (k !== agent) { setAgent(k); setDep(''); setEffort('') } }}>{NAMES[k]}</Tab>
        ))}
      </Tabs>
      <p className="text-fg2">{v.clis[agent]?.routing}</p>
      {azure ? (
        <label className="flex flex-col gap-1">
          <span className="text-fg2">{WORDS.deployment}</span>
          {models.length ? (
            <select aria-label={WORDS.deployment} disabled={v.locked || busy} value={models.some((m) => m.id === dep) ? dep : ''} onChange={(e) => { setDep(e.target.value); setEffort('') }}
              className={clsx(field, 'h-8 rounded-md bg-bg px-2')}>
              <option value="">{v.clis[agent]?.deployment ? `${WORDS.dflt} (${v.clis[agent].deployment})` : WORDS.dflt}</option>
              {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          ) : null}
          <input aria-label={WORDS.typed} placeholder={WORDS.typed} disabled={v.locked || busy} value={dep} onChange={(e) => { setDep(e.target.value.trim()); setEffort('') }}
            className={clsx(field, 'h-8 rounded-md bg-bg px-2')} />
        </label>
      ) : null}
      <label className="flex flex-col gap-1">
        <span className="text-fg2">{WORDS.effort}</span>
        <select aria-label={WORDS.effort} disabled={v.locked || busy} value={levels.includes(effort) ? effort : ''} onChange={(e) => setEffort(e.target.value)}
          className={clsx(field, 'h-8 rounded-md bg-bg px-2')}>
          <option value="">{WORDS.dflt}</option>
          {levels.map((l) => <option key={l} value={l}>{levelName(l)}</option>)}
        </select>
      </label>
      {problem ? <p className="text-need-fg">{problem}</p> : null}
      {error ? <p role="alert" className="text-need-fg">{error}</p> : null}
      {v.locked ? null : (
        <span className="flex flex-wrap items-center justify-end gap-1.5">
          <Ghost disabled={busy} onClick={() => void save({ default: true })}>{WORDS.defaults}</Ghost>
          <Primary disabled={busy} onClick={() => void save({
            // its CLI only when chosen here, or with a deployment (one belongs to one CLI); an effort alone follows Settings' CLI
            ...(agent !== (v.selection.agent ?? v.inherit?.agent ?? 'claude') || v.selection.agent || (azure && dep) ? { agent } : {}),
            ...(azure ? { deployment: dep } : {}), effort: levels.includes(effort) ? effort : 'default' })}>{WORDS.save}</Primary>
        </span>
      )}
    </div>
  )
}
