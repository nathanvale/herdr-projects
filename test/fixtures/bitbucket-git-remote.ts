import { appendFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

// Git has already selected the transport and applied its actual URL rewrites.
// This closed server fixture maps only these independent provider URLs to bare
// repositories; it never rewrites the client's argv before Git sees it.
const [name, url] = process.argv.slice(2)
const state = JSON.parse(readFileSync(process.env.BITBUCKET_FIXTURE_STATE!, 'utf8'))
const selected = url === 'https://alice@bitbucket.org/space/sample.git' || url === 'https://bob@bitbucket.org/space/sample.git' ? state.bare
  : url === 'https://alice@bitbucket.org/other/foreign.git' ? state.foreignBare : undefined
if (!selected) process.exit(1)
const user = new URL(url).username
const gitCwd = process.env.BITBUCKET_FIXTURE_GIT_CWD!
appendFileSync(state.gitStartups, JSON.stringify({ cwd: process.cwd(), gitCwd }) + '\n')
// Exercise the same synthetic host Git credential owner the real HTTPS helper
// would use. Credential output never leaves this process.
const lookup = Bun.spawn(['git', 'credential', 'fill'], { cwd: gitCwd, stdin: Buffer.from(`protocol=https\nhost=bitbucket.org\npath=${new URL(url).pathname.slice(1)}\nusername=${user}\n\n`), stdout: 'pipe', stderr: 'ignore' })
const credential = await new Response(lookup.stdout).text()
if (await lookup.exited || !credential.includes(`password=${state.token}\n`)) process.exit(1)
appendFileSync(state.gitTransports, JSON.stringify({ url, repository: selected, username: user }) + '\n')
// The fixture's server owns its bare repository; client metadata/config must
// not become the server's GIT_DIR or configuration.
const env = { ...process.env }
for (const key of Object.keys(env)) if (/^GIT_(?:DIR|COMMON_DIR|WORK_TREE|CONFIG(?:$|_COUNT$|_PARAMETERS$|_KEY_\d+$|_VALUE_\d+$))/.test(key)) delete env[key]
const child = Bun.spawn([join(process.env.BITBUCKET_FIXTURE_GIT_EXEC_PATH!, 'git-remote-ext'), name, `git %s ${selected}`], { env, stdin: 'inherit', stdout: 'inherit', stderr: 'inherit' })
process.exit(await child.exited)
