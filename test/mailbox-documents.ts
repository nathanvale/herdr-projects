import { CoreError } from '../server/core/client.ts'
import { seal, unseal, type MailCredential } from '../server/core/envelope.ts'
import { mailRequestHash, type DocConnection, type MailRequest, type MailResponse } from '../server/core/mailbox.ts'

export class Documents implements DocConnection {
  docs = new Map<string, { version: number; value: unknown }>()
  async call<T>(method: string, p: Record<string, unknown>): Promise<T> {
    const key = `${p.on ?? ''}:${p.name}`
    const doc = this.docs.get(key) ?? { version: 0, value: null }
    if (method === 'doc.get') return structuredClone(doc) as T
    if (method !== 'doc.set') throw new Error('Unexpected method')
    if (p.version !== doc.version) throw new CoreError('conflict', 'stale version')
    this.docs.set(key, { version: doc.version + 1, value: structuredClone(p.value) })
    return { version: doc.version + 1 } as T
  }
  put(credential: MailCredential, id: string, request: MailRequest, on = 'box') {
    this.docs.set(`${on}:shep-q-${credential.grant}`, { version: 1, value: { [id]: seal(credential, id, 'request', request) } })
  }
  response(credential: MailCredential, id: string): MailResponse {
    const doc = this.docs.get(`box:shep-a-${credential.grant}`)!
    const requests = this.docs.get(`box:shep-q-${credential.grant}`)!.value as Record<string, unknown>
    const request = unseal<MailRequest>(credential, id, 'request', requests[id])
    return unseal(credential, `${id}:${mailRequestHash(request)}`, 'response', (doc.value as Record<string, unknown>)[id])
  }
}
