import { createServer, type Socket } from 'node:net'
import { Database } from 'bun:sqlite'
import { createDecipheriv, createHash } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { Mailbox, type Grant, type MailRequest, type MailResponse, type DocConnection } from '../server/core/mailbox.ts'
import type { Envelope } from '../server/core/envelope.ts'
import { Documents } from './mailbox-documents.ts'
import { methods, frame } from './core-wire.ts'
import { withBitbucket, type BitbucketFixture } from './bitbucket-fixture.ts'

export interface CliFixture {
  f: BitbucketFixture; grant: Grant
  replies: Map<string, MailResponse>; requestIds: Set<string>
  dispatches: { id: string; request: MailRequest }[]
  connections: () => number
  journal: () => { id: string; hash: string; response: string | null }[]
  run: () => Promise<{ stdout: string; stderr: string; code: number }>
  reopen: () => Promise<void>
}

/** Real CLI process, framed Unix core peer and authenticated durable mailbox.
 * Only Git/provider/core transport owners are synthetic; no launch authority is inherited. */
export async function withBitbucketCli(run: (fixture: CliFixture) => Promise<void>, recoverReply = false) {
  await withBitbucket(async f => {
    const docs = new Documents(), replies = new Map<string, MailResponse>(), requestIds = new Set<string>()
    const dispatches: CliFixture['dispatches'] = [], jobs = new Set<Promise<void>>()
    const home = join(f.root, 'cli-mailbox'), socketPath = join(f.root, 'cli.sock'), credentialPath = join(f.root, 'cli-credential.json')
    const connection: DocConnection = { call: (method, params) => docs.call(method, { ...params, on: 'box' }) }
    const dispatch = async (grant: Grant, request: MailRequest, id: string) => {
      dispatches.push({ id, request })
      if (request.action !== 'cli') throw Error('Fixture only admits CLI')
      return f.tasks.cli(grant, (request.args as { args: string[] }).args)
    }
    let mailbox = new Mailbox(home, connection, async () => 'box', dispatch)
    const grant = mailbox.issue('space', 'fixture-launch', 'local-machine', ['cli'])
    f.authorize(grant)
    writeFileSync(credentialPath, JSON.stringify({ socket: socketPath, mail: grant.credential }), { mode: 0o600 })
    const reopen = async () => {
      await Promise.allSettled([...jobs]); mailbox.close(); f.reopen()
      mailbox = new Mailbox(home, connection, async () => 'box', dispatch)
    }
    // Independent AES-GCM decoder: no production unseal/hash/response serializer.
    const inspect = (value: unknown) => {
      for (const [id, raw] of Object.entries((value ?? {}) as Record<string, Envelope>)) {
        const original = dispatches.find(row => row.id === id)
        if (!original) throw Error('No admitted fixture request')
        const hash = createHash('sha256').update(JSON.stringify([original.request.action, original.request.args])).digest('hex')
        const cipher = createDecipheriv('aes-256-gcm', Buffer.from(grant.credential.key, 'base64'), Buffer.from(raw.iv, 'base64'))
        cipher.setAAD(Buffer.from(JSON.stringify([1, grant.credential.server, grant.id, grant.machine, `${id}:${hash}`, 'response'])))
        cipher.setAuthTag(Buffer.from(raw.tag, 'base64'))
        replies.set(id, JSON.parse(Buffer.concat([cipher.update(Buffer.from(raw.body, 'base64')), cipher.final()]).toString()))
      }
    }
    let connections = 0, recovered = false
    const sockets = new Set<Socket>()
    const server = createServer(socket => {
      connections++; sockets.add(socket); socket.on('close', () => sockets.delete(socket))
      socket.on('error', () => socket.destroy())
      let buffer = Buffer.alloc(0), plain = true
      const answer = async (call: { id: number; method: string; params: Record<string, unknown> }) => {
        let result: unknown
        if (call.method === 'rpc.discover') result = { info: { version: '0.1.14' }, methods: methods.map(name => ({ name })) }
        else if (call.method === 'doc.get' || call.method === 'doc.set') {
          result = await connection.call(call.method, call.params)
          const name = String(call.params.name)
          if (call.method === 'doc.set' && name.startsWith('shep-q-')) {
            for (const id of Object.keys((call.params.value ?? {}) as object)) requestIds.add(id)
            const job = mailbox.receive(grant.id); jobs.add(job)
            void job.finally(() => jobs.delete(job)).catch(() => {})
          }
          if (call.method === 'doc.get' && name.startsWith('shep-a-')) {
            const value = (result as { value: unknown }).value
            inspect(value)
            if (recoverReply && !recovered && replies.size) {
              recovered = true
              await reopen()
              docs.docs.delete(`box:shep-a-${grant.id}`)
              await mailbox.resync() // Recover encrypted journal response without dispatch.
              socket.destroy(); return // CLI reconnects with its original authenticated id.
            }
          }
        } else throw Error('Unsupported synthetic core operation')
        if (!socket.destroyed) socket.write(frame(0, JSON.stringify({ jsonrpc: '2.0', id: call.id, result })))
      }
      socket.on('data', bytes => {
        buffer = Buffer.concat([buffer, Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes)])
        if (plain) {
          const end = buffer.indexOf(10); if (end < 0) return
          const hello = JSON.parse(buffer.subarray(0, end).toString()) as { id: number }
          buffer = buffer.subarray(end + 1); plain = false
          socket.write(JSON.stringify({ jsonrpc: '2.0', id: hello.id, result: { generation: 1, version: '0.1.14', framed: true, methods, features: [], core: { id: 'synthetic-cli', name: 'synthetic-cli' } } }) + '\n')
        }
        while (buffer.length >= 9) {
          const length = buffer.readUInt32LE(5); if (buffer.length < length + 9) return
          const call = JSON.parse(buffer.subarray(9, length + 9).toString())
          buffer = buffer.subarray(length + 9)
          void answer(call).catch(() => socket.destroy())
        }
      })
    })
    await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(socketPath, resolve) })
    const fixture: CliFixture = { f, grant, replies, requestIds, dispatches, connections: () => connections, reopen,
      journal: () => {
        const db = new Database(join(home, 'mailbox.sqlite'), { readonly: true })
        try { return db.query('SELECT id,hash,response FROM requests ORDER BY rowid').all() as { id: string; hash: string; response: string | null }[] } finally { db.close() }
      },
      run: async () => {
        const child = Bun.spawn([process.execPath, '--no-env-file', join(import.meta.dir, '../helper/core-cli.ts'), 'pr', 'DEMO-2'], {
          cwd: f.folder, stdin: 'ignore', stdout: 'pipe', stderr: 'pipe',
          env: { PATH: process.env.PATH, HOME: join(f.root, 'user'), XDG_CONFIG_HOME: join(f.root, 'user'), SHEPHERDR_CORE_CREDENTIAL: credentialPath },
        })
        let timer: Timer | undefined
        try {
          const deadline = new Promise<never>((_, reject) => { timer = setTimeout(() => { child.kill('SIGKILL'); reject(Error('Synthetic CLI deadline')) }, 15000) })
          const [stdout, stderr, code] = await Promise.race([Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]), deadline])
          return { stdout, stderr, code }
        } finally { clearTimeout(timer); if (child.exitCode === null) child.kill('SIGKILL'); await child.exited }
      } }
    try { await run(fixture) }
    finally {
      for (const socket of sockets) socket.destroy()
      await new Promise<void>(resolve => server.close(() => resolve()))
      await Promise.allSettled([...jobs]); mailbox.close()
    }
  })
}
