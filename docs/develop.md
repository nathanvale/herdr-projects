# Develop

Follow [AGENTS.md](../AGENTS.md) for local verification and approval boundaries.
Follow [coding standards](../CODING_STANDARDS.md) when writing or reviewing code.

## CI and merge checks

The [Check workflow](../.github/workflows/check.yml) owns the full checks and their
triggers, including docs-only pull requests. The
[Core rewrite workflow](../.github/workflows/core-rewrite.yml) checks the integration
branch without deploying main. Neither installs services, changes private sharing,
migrates state or publishes a release.

Wait for the pull request's required checks before merging. `shepherdr checks <id>`
shows them; `shepherdr merge <id>` proceeds once green. A red main reaches the
coordinator for a fix forward. Inspect a failed run with `gh run view <run> --log-failed`.

Each pull-request push runs checks again and costs Actions minutes. For rare cases
without a pull request, request a branch check with
`gh workflow run check.yml --ref <branch>` and watch it with `gh run watch`.
Use an environment-required wrapper for GitHub CLI commands where applicable.

If tests have already been started locally outside the verification policy, keep
them at the lowest priority and isolated from live `~/.shepherdr`. This containment
requirement does not authorize local test execution.

## Isolated development

Use [isolated preview startup](core/start.md), with a separate home, port and core
session. Never use live `~/.shepherdr` for development. The optional fictional demo
uses `SHEPHERDR_SOURCE=demo bun server/main.ts`; it is UI fixture data, not acceptance
proof. Its optional browser is local-only, without any remote sharing or SSH code.
Vite can proxy an isolated app through `SHEPHERDR_API_URL`.
Codex keeps one trust fingerprint per hook slot for all Shepherdr installs, so trusting hooks in a second checkout
untrusts the first; a preview or moved checkout will do this.

```text
server/core/       core client, product state, tasks and standalone lifecycle
server/common/     shared log readers, parsers, vault and demo formatting
server/demo/       fictional UI world and optional local demo browser
server/app.ts      private HTTP/WebSocket app
src/               existing screen kernel and shared presentation
plugins/           built-in plugin parts
helper/core-*.ts   immutable authenticated helpers executed through core
bin/shepherdr      standalone lifecycle/human control or authenticated agent mailbox
bin/agent-browser  pinned shared-browser wrapper
skill/             agent and coordinator guides
```

Task IDs and workflow records live in the selected application's private SQLite
store. Prefix/next-number changes are per repository space and only move forward.
No 2.0 JSON/task-ID import is performed. See [state and cutover](core/cutover.md).
