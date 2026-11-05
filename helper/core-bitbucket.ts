import { runBitbucket } from '../server/core/forge/bitbucket-http.ts'
import { BITBUCKET_LIMITS } from '../server/core/forge/bitbucket-protocol.ts'

// Loaded only from the admitted immutable helper directory with --no-env-file.
// Never print exceptions, provider bodies, credential output or authorization headers.
try {
  const reader = Bun.stdin.stream().getReader(), chunks: Uint8Array[] = []
  let size = 0
  for (;;) {
    const row = await reader.read()
    if (row.done) break
    size += row.value.length
    if (size > BITBUCKET_LIMITS.input) throw Error('bounded input')
    chunks.push(row.value)
  }
  const value: unknown = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  process.stdout.write(JSON.stringify(await runBitbucket(value)))
} catch { process.stdout.write(JSON.stringify({ ok: false, category: 'invalid-request' })) }
