// SHEP-186: the suggested next message the chat box shows greyed out (the agent's reply's last line, core/chat-log.js).
import type { Chat } from '@shared/types.ts'

// SHEP-186: the suggested next message the box shows greyed out: the newest text is the agent's, it carries a suggestion
// (its reply's last line, core/chat-log.js) and the person hasn't written after it. Off in Settings: none. { id, text } or null.
// Anything the person sent ends it, words or not: a photo, a file or a queued one comes as rows of theirs with no text
// (service/compat.ts), and the suggestion before it is old (PR 60).
export function suggestionOf(chat: Chat | undefined, on: boolean): { id: string; text: string } | null {
  if (!on || !chat) return null
  for (let i = chat.messages.length - 1; i >= 0; i--) {
    const m = chat.messages[i]!
    if (m.who === 'you') return null
    if (!m.text) continue
    if (m.error) return null
    return m.suggest ? { id: m.id, text: m.suggest } : null
  }
  return null
}
// Settings › Agents › Suggested next message: on unless it's off, as the chat's space has it (its own value, else its
// machine's or Everywhere's: the service resolves each space's row, service/settings.ts pick). A chat in no space, or
// a space with no section: Everywhere's (PR 60).
export function suggestionsOn(settings: { level?: string; rows: { key: string; value: string }[] }[] | undefined, place: string | null = null): boolean {
  const row = (level: string) => (settings ?? []).filter((s) => (s.level ?? 'all') === level).flatMap((s) => s.rows).find((r) => r.key === 'agents.suggestions')
  return ((place ? row(place) : undefined) ?? row('all'))?.value !== 'off'
}
