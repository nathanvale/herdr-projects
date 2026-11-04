import { createServer, createConnection } from 'node:net'
import { chmodSync, lstatSync } from 'node:fs'
import { join, basename } from 'node:path'
import { ProtectedUpdate } from './protected-update.ts'
import type { CoreSource } from './source.ts'

const LIMIT = 512 * 1024
export interface OperatorResult { out: string; code: number }
/** OS-owned socket in the private installation home. No web route or caller-selected agent identity. */
export async function startOperator(source: CoreSource, boot: string, stop?: () => void) {
  const path = join(source.config.home, `operator.${boot.slice(0, 8)}.sock`)
  if (Buffer.byteLength(path) > 100) throw new Error('Home path is too long for its private operator socket')
  const server = createServer({ allowHalfOpen: true }, socket => {
    const request = new AbortController(), expires = performance.now() + 5000
    const cancel = () => request.abort(Error('Protected update refused: operator request expired or disconnected before admission. Inspect application status before retrying.'))
    const deadline = setTimeout(() => { cancel(); socket.destroy() }, 5000)
    socket.on('close', () => { clearTimeout(deadline); cancel() })
    let size = 0, started = false, framed = false
    const chunks: Buffer[] = []
    socket.on('error', cancel)
    const handle = async (bytes: Buffer, newline: boolean) => {
      if (socket.destroyed || source.quiescing) { socket.destroy(); return }
      let result: OperatorResult
      try {
        let input: { args?: unknown; stdin?: unknown }
        try { input = JSON.parse(bytes.toString('utf8')) } catch { throw new Error('Invalid private operator request') }
        if (!input || typeof input !== 'object') throw new Error('Invalid private operator request')
        if (!Array.isArray(input.args) || input.args.length > 16 || input.args.some(word => typeof word !== 'string' || word.length > 256) ||
          input.stdin !== undefined && (typeof input.stdin !== 'string' || Buffer.byteLength(input.stdin) > 64 * 1024)) throw new Error('Invalid private operator request')
        if (newline && input.args[0] !== 'recover-launch') throw Error('Newline framing is reserved for recover-launch')
        if (input.args[0] === 'stop-if-idle') {
          if (!stop || input.args.length !== 2 || input.args[1] !== boot || input.stdin !== undefined) throw Error('Protected stop identity or protocol is unavailable; application left running')
          await new ProtectedUpdate(source).prepareStop(request.signal, expires, () => {
            // Admission owns shutdown even when its acknowledgement is lost.
            try { socket.end(JSON.stringify({ out: `idle-stop:${boot}`, code: 0 })) } finally { stop() }
          })
          return
        } else if (input.args[0] === 'recover-launch') {
          if (!newline) throw Error('Recovery requires a newline-framed request with its write side open until the reply')
          if (input.stdin !== undefined) throw Error('Recovery does not accept stdin or caller-supplied host evidence')
          result = { out: await source.launchRecovery.operator(input.args, request.signal, expires), code: 0 }
        } else result = { out: await source.secrets.operator(input.args, input.stdin as string | undefined), code: 0 }
      } catch (error) { result = { out: (error as Error).message + '\n', code: 1 } }
      if (!socket.destroyed) socket.end(JSON.stringify(result))
    }
    socket.on('data', data => {
      if (started) { cancel(); socket.destroy(); return }
      const chunk = Buffer.from(data); size += chunk.length
      if (size > LIMIT) { cancel(); socket.destroy(); return }
      chunks.push(chunk)
      const bytes = Buffer.concat(chunks), newline = bytes.indexOf(10)
      if (newline < 0) return
      // Only recovery opts in. Existing EOF requests may contain JSON whitespace.
      try { if (JSON.parse(bytes.subarray(0, newline).toString('utf8'))?.args?.[0] !== 'recover-launch') return } catch { return }
      started = true; framed = true
      if (newline !== bytes.length - 1) { cancel(); socket.destroy(); return }
      void handle(bytes.subarray(0, newline), true)
    })
    socket.on('end', () => {
      // Recovery never uses FIN as its request delimiter. A peer's FIN during
      // observation is loss of operator authority, even with allowHalfOpen.
      if (framed) { request.abort(Error('Recovery operator peer disconnected before admission')); socket.destroy(); return }
      if (started) return
      started = true
      void handle(Buffer.concat(chunks), false)
    })
  })
  server.maxConnections = 16
  // Legacy clients delimit by FIN. Recovery keeps the request half open until its reply.
  try {
    await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(path, resolve) })
    chmodSync(path, 0o600)
  } catch (error) { server.close(); throw error }
  return { path, close: () => server.close() }
}

export async function operatorRequest(home: string, path: string, args: string[], stdin?: string): Promise<OperatorResult> {
  const directory = lstatSync(home)
  if (!directory.isDirectory() || directory.isSymbolicLink() || directory.mode & 0o077 || directory.uid !== process.getuid?.()) throw new Error('Operator home must be a private directory owned by you')
  if (!/^operator\.[a-f0-9]{8}\.sock$/.test(basename(path)) || join(home, basename(path)) !== path) throw new Error('Invalid private operator socket')
  const stat = lstatSync(path)
  if (!stat.isSocket() || stat.mode & 0o077 || stat.uid !== process.getuid?.()) throw new Error('Operator socket must be private and owned by you')
  const body = JSON.stringify({ args, stdin })
  if (Buffer.byteLength(body) > LIMIT) throw new Error('Operator request is too large')
  return new Promise((resolve, reject) => {
    const socket = createConnection(path), chunks: Buffer[] = []; let size = 0
    socket.setTimeout(10_000, () => socket.destroy(new Error('The operator command timed out; inspect the named setting before retrying')))
    socket.on('error', reject)
    socket.on('connect', () => { if (args[0] === 'recover-launch') socket.write(body + '\n'); else socket.end(body) })
    socket.on('data', data => { const chunk = Buffer.from(data); size += chunk.length; if (size > LIMIT) socket.destroy(new Error('Operator reply is too large')); else chunks.push(chunk) })
    socket.on('end', () => { try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))) } catch { reject(new Error('No valid operator reply; inspect the named setting before retrying')) } })
  })
}
