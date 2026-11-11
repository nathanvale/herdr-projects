import { expect, test } from 'bun:test'
import { suggestionOf, suggestionsOn } from './suggest.ts'
import type { Chat, Message } from '@shared/types.ts'

const chat = (messages: Partial<Message>[]) => ({ key: 'p:sp1', messages: messages.map((m, i) => ({ id: `m${i}`, who: 'agent', ...m })) }) as Chat

test('the newest agent text with a suggestion is the ghost text', () => {
  expect(suggestionOf(chat([{ who: 'you', text: 'hi' }, { text: 'Merge it?', suggest: 'yes, merge it' }]), true))
    .toEqual({ id: 'm1', text: 'yes, merge it' })
})

test('nothing after the person wrote, and nothing from an agent reply without a suggestion', () => {
  expect(suggestionOf(chat([{ text: 'Merge it?', suggest: 'yes' }, { who: 'you', text: 'no' }]), true)).toBeNull()
  expect(suggestionOf(chat([{ text: 'Merge it?', suggest: 'yes' }, { text: 'Merged.' }]), true)).toBeNull()
})

test('rows that are not words (activity, news) never hide or replace a suggestion', () => {
  expect(suggestionOf(chat([{ text: 'Merge it?', suggest: 'yes' }, { activity: undefined, news: undefined } as Partial<Message>]), true))
    .toEqual({ id: 'm0', text: 'yes' })
})

test('a suggestion never shows with the setting off, nor in an empty chat', () => {
  expect(suggestionOf(chat([{ text: 'Merge it?', suggest: 'yes' }]), false)).toBeNull()
  expect(suggestionOf(undefined, true)).toBeNull()
  expect(suggestionOf(chat([]), true)).toBeNull()
})

test('the setting is on unless Settings says off', () => {
  const row = (value: string) => [{ rows: [{ key: 'agents.suggestions', value }] }]
  expect(suggestionsOn(row('on'))).toBe(true)
  expect(suggestionsOn(row('off'))).toBe(false)
  expect(suggestionsOn(undefined)).toBe(true)
})

// PR 60: a photo, a file or a queued one with no words is the person's message too (service/compat.ts gives it rows of
// theirs with no text); the suggestion before it is old, so Enter must not send it
test('a message of the person with no words ends the suggestion: a file, photos, a queued file', () => {
  const asked = { text: 'Merge it?', suggest: 'yes, merge it' }
  expect(suggestionOf(chat([asked, { who: 'you', file: { name: 'shot.png', path: '/tmp/shot.png' } }]), true)).toBeNull()
  expect(suggestionOf(chat([asked, { who: 'you', images: 2 }]), true)).toBeNull()
  expect(suggestionOf(chat([asked, { who: 'you', waiting: true, waitsFor: 'queue', file: { name: 'a.txt', path: '/tmp/a.txt' } }]), true)).toBeNull()
  // the agent's own rows with no words still never hide it
  expect(suggestionOf(chat([asked, { who: 'agent', activity: undefined }]), true)).toEqual({ id: 'm0', text: 'yes, merge it' })
})

// PR 60: a space's own setting wins over Everywhere's for its chats; the service gives each space its resolved row
test("the chat's space's setting, else Everywhere's", () => {
  const section = (level: string, value: string) => ({ level, rows: [{ key: 'agents.suggestions', value }] })
  const settings = [section('all', 'on'), section('sp1', 'off'), section('vm/sp2', 'on')]
  expect(suggestionsOn(settings, 'sp1')).toBe(false)
  expect(suggestionsOn(settings, 'vm/sp2')).toBe(true)
  expect(suggestionsOn([section('all', 'off'), section('sp1', 'on')], 'sp1')).toBe(true)
  expect(suggestionsOn([section('all', 'off'), section('sp1', 'on')], null)).toBe(false)
  // a space with no section of its own (or a chat in none): Everywhere's
  expect(suggestionsOn(settings, 'sp9')).toBe(true)
  expect(suggestionsOn([section('all', 'off')], 'sp9')).toBe(false)
})
