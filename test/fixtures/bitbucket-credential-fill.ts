import { appendFileSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { runChild } from '../child.ts'

// CI-only protocol fault injection AFTER the actual synthetic host's Git fill.
// No argv/URL substitution; no approve/reject or credential installation.
const input = Buffer.from(await Bun.stdin.text())
const output = (await runChild([process.env.BITBUCKET_FIXTURE_REAL_GIT!, 'credential', 'fill'], { cwd: process.env.BITBUCKET_FIXTURE_GIT_CWD, input, env: process.env })).toString().trimEnd()
const state = JSON.parse(readFileSync(process.env.BITBUCKET_FIXTURE_STATE!, 'utf8'))
// Private fixture evidence of actual Git output, without logging secret values.
appendFileSync(join(dirname(process.env.BITBUCKET_FIXTURE_STATE!), 'credential-fills.jsonl'), JSON.stringify({
  expiry: output.match(/^password_expiry_utc=(.+)$/m)?.[1], refresh: /^oauth_refresh_token=.+$/m.test(output),
  username: output.match(/^username=(.+)$/m)?.[1], password: /^password=.+$/m.test(output), decoration: state.credentialReply,
}) + '\n')
const suffix: Record<string, string> = {
  duplicate: 'username=alice', malformed: 'malformed-line', unsupported: 'authtype=Bearer\ncredential=UNSUPPORTED_SYNTHETIC_SECRET',
  metadata: 'vendor_private=SYNTHETIC_EXTRA_SECRET_789',
}
process.stdout.write(output + '\n' + (suffix[state.credentialReply] ? suffix[state.credentialReply] + '\n' : ''))
