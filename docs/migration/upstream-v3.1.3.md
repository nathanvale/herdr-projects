# Full 3.x source migration

S0 is a source-only foundation; A1 adds provider launch plans and deployment discovery
owners on it, with Azure dispatch held, and C1 finds a Claude Code session under its own
agent's folder. Required Bitbucket, Azure and lifecycle ports are
pending. This checkpoint is not deployable or ready for application use. Check's
`candidate-readiness` job intentionally refuses it even when native source checks
pass. Imported installer/service code is source input, not authority to run it.

## Inputs and source ownership

| Input | Exact commit |
| --- | --- |
| F, reserved fork parent | `4f0236f03a88c5e9fa344475d90d3a20ef418481` |
| U, upstream v3.1.3 parent | `dc018f2a42f3a1d8562f7b23a3bcd3988f347bdc` |
| P, required Bitbucket contract source | `074dec5ea0bf0a057f520fa50497bf9e1b696ad9` |
| B, actual common ancestor | `de8e17957efb4aa016d7e4d652f397aaa95f0880` |

S0 merges U into private `integrate/upstream-v3.1.3` rooted at F. P is not a merge
parent. Its behavior is required regardless of the old-architecture PR decision.
Native runtime sources use exact U. Git's suggested relocation of old server
modules into `service/hc` was rejected; core transport is not their product owner.
The upstream README and existing version/release text are imported provenance,
not a newly authored landing-page design or a fork release.

[Behavior inventory](upstream-v3.1.3.json) binds the pending requirements.
[File dispositions](upstream-v3.1.3-files.json) enumerate every changed B..F and
F..P path, original hashes and static test declarations. Fixed Git objects retain
removed implementation and test bodies. Historical docs remain labelled references.
Deleting an old test file does not discharge its regression obligation.

## Source phases

`T/` means `mods/tasks/bin/herdr_task/`. New paths are proposed dependent-phase
owners, not implemented interfaces.

| Phase | Dependencies | Owner and exit |
| --- | --- | --- |
| S0 | This source admission | Exact U, F/P dispositions and blocked readiness; Root review and CI before dependent work. |
| S1 | Reviewed S0 | New `T/forge.py`, existing `T/github.py`, commands/proof/worktree consumers; preserve GitHub defaults. Smallest next customization. |
| A1 | Reviewed S0 | New `T/providers.py` and `service/azure-deployments.ts`; nonsecret bindings, supported authentication and discovery custody. |
| C1 | S0, separately authorized | `core/chat-log.js` FIND and `T/sessions.py`; a Claude Code session is found under its own process's folder, for reading only. Not a port. |
| B1 | S1 | New `T/bitbucket.py`, `T/bitbucket_http.py`; qualified identity, host credentials and complete exact-head reads. |
| B2 | B1 | New `T/publications.py`, commands/output/CLI; durable claims, publication/readiness and current admission. |
| A2 | A1 | Shared settings/agents, desktop/web controls, `T/settings.py`, launch/resume; discovery, selectors and binding parity. |
| L1 | A1 | New `T/launch_admission.py`; one dispatch authority with durable uncertainty and sender fencing. |
| L2 | A2, L1 | Native revive/watch/manual restart through that owner; independent qualification and conditional retirement. |
| Q | B2, A2, L2 | Exact candidate CI/public process proof; all required ports and old proof obligations resolved. |
| R | Q, human state choices | Separately admitted rehearsal and matching executable/state rollback. |

### A1 provider checkpoint

`bin/check-migration` names each phase's admitted owner paths; the manifest's
`source_deltas` pins each one's content hash and exact-U blob. The gate proves two
things: every U path outside that table and outside the three overrides is
byte-identical to U with U's mode, and each admitted path matches its pin (an
admitted U path keeps exact U's mode; an admitted added path is a plain file). A
symbolic link at an admitted path or at a U path outside the overrides refuses, even
to identical content. The three overrides (`AGENTS.md`, `docs/develop.md`, `.github/workflows/check.yml`) are
skipped whole, content and mode. They, the checker, the manifest and added files
outside the table are not pinned by it and rely on review. Candidate readiness
stays blocked.

- `T/providers.py` owns nonsecret bindings, the four supported launch plans and the
  admission gate. Start, queue, resume, switch, backup, the tick's queue and an
  automation's run consult it. A valid Azure plan is held, not dispatched.
- `service/azure-deployments.ts` owns explicit read-only discovery. Nothing calls it yet.
- Hard A2 prerequisite: coordinator launch sites (`service/actions.ts`,
  `service/spaces.ts`, `service/agents.ts`, `mods/chat/main.js`,
  `mods/coordinator/restart.sh`) do not read the binding. No control, command or
  selector may set an Azure route until each refuses or plans through the provider owner.
- Carried to L1: binding the execution machine. A pushed settings copy refuses Azure,
  but a Serve-from host's file is its own.
- Carried to Q: empty settings `env` values are documented as unset for provider
  selection only; the same treatment of endpoint, credential and model variables is unproved.
  The backup's gate has in-module proof only; its public-process proof is Q's.
- Detail, official sources and authored regressions: [Azure launch plans](../azure-launch-plans.md).

### C1 chat profile checkpoint

`core/chat-log.js` (FIND, copied to `mods/chat/core/` by `bin/sync-shared`) and
`T/sessions.py` (`session_of()`) find an agent's Claude Code session, each by one rule,
for each candidate process and never for the caller:

- That process's `CLAUDE_CONFIG_DIR` set to an absolute path: exactly that folder.
- Its environment readable and the variable unset: `$HOME/.claude`.
- Unreadable, an empty environment, or a value that isn't an exact absolute path: nothing
  for that process, and no other folder is tried. macOS shows a system binary's environment
  as empty, so empty is no evidence.
- Metadata whose `pid` isn't that process's selects nothing. A session with no log stays
  pending under `~/.claude`. Nothing scans across folders.
- Under another folder a session with no log prints nothing, and FIND stops at that process,
  as pending has no path for a guard to read and would open a chat that could restart it. The cost: a fresh custom-folder
  agent shows "Can't find this conversation" until its first log line, as today. Both chats
  look again while they have no path, so it opens then.
- A reused pid isn't caught: a crashed agent's metadata names the same pid as a new process
  under that folder, so it can match until the new process rewrites the file. The `pid`
  check catches metadata for another pid and no other stale metadata.
- Only that one variable is taken from a process. Linux reads `/proc/<pid>/environ`; macOS
  reads `KERN_PROCARGS2` through python3, as `ps eww` is flat text. Any other platform
  finds nothing. Both read the environment the process started with.
- macOS reads live memory, and `argc` no longer marks where the environment starts once a
  process sets its title (Node's `process.title` rewrites argv). A short title zero-fills argv
  past itself, so with `argc` of 2 or more and every word after `argv[0]` empty the
  environment starts at the next word, and a Node agent reads as usual. A title that fills
  argv collapses it: the variable seen anywhere but in the counted environment refuses, and
  so does an empty count, so a set variable reads as unset only if a process overwrites its
  own environment memory. An argument shaped like the variable, with the variable unset,
  refuses too.
- Behaviour change: on macOS FIND now needs python3 on its PATH. Without it every Claude
  agent there loses Chat, including default ones that work today. `session_of()` runs in
  python already and doesn't.
- A session under another folder is for reading only. Revive, resume, a restart and a fork
  carry no `CLAUDE_CONFIG_DIR`, so continuing it would start on another profile, perhaps
  another account. `session_of()` returns such a session only to `any_folder=True`, which
  `T/news.py` alone asks for, so for a non-default folder nothing records it and no path
  that starts an agent gains anything: each behaves as before, or refuses once a log is found.
  A default agent whose environment can't be read
  does change: it gets no record, so a resume starts fresh. `sessionOf()` in `core/agents.js` gives it no id, and the window's picker
  and `service/agents.ts` `restart()` refuse before anything ends, as a found log is what
  newly shows the window's picker and the web's Composer for such an agent. The window's start
  screen shows its picker with no log, as before, and that isn't refused. Carrying the folder
  belongs to L1 and L2.
- `sessionOf()` knows ~/.claude by its shape, as the agent's machine's home isn't known
  there, so FIND finds nothing for another folder called `.claude`, and so does `session_of()`.
- The macOS reader has no CI: `core/chat-find.test.js` and `test/test_session_discovery.py`
  take it only when run on macOS.
- This fix is not a required port. No inventory requirement changes status.

### Bitbucket contract

Port P's behavior into native owners, not its old server paths. GitHub retains
its transport. Keep local Git, approval, task state and cleanup outside the adapter.
Preserve provider-qualified identity, host-owned credentials without fallback,
frozen push routes, preflight before effects and current exact-candidate admission.
Preserve persistent draft publication, readiness preparation and current title,
reviewers, destination and `close_source_branch`. Create sets that flag to false;
preparation preserves its current value. True requests source-branch closure.
Exact-commit checks retain complete pagination and distinct missing/incomplete/
pending/failed/passed outcomes. Empty checks cannot establish readiness.

Persist an operation UUID before uncertain dispatch. Lost reply, empty lookup or
changed context cannot justify retry or replacement. Positive exact reconciliation
retains the same UUID. Preserve confirmed push facts and truthful typed unknown
CLI outcomes. `ready`, `show --evidence` and `accept` cross the native workflow;
readiness needs a durable draft/preparation stage instead of apparent success
despite uncertain publication. Keep Bitbucket native merge refused absent an
official expected-source-head guarantee. No GitHub/local/agent merge fallback.
Feedback, base health and extra provider features stay outside this scope.

### Azure contract

Personal remains the default, preserving native CLI configuration and sign-in;
it does not force a personal account. Use general-purpose fields without a fixed
tenant/account or organization. Provider connection, endpoint/resource, authentication
and discovery subscription remain human-owned at every scope.

Port existing explicit Refresh and manual deployment entry for both CLIs in
desktop/web settings and task/coordinator new-start selectors. Inventories are
scope-specific and memory-only. Keep explicit subscription reads, unique resource
matching, public-cloud/local-only bounds and Everywhere's single-machine rule.
Offer only Succeeded Anthropic/chatCompletion or OpenAI/responses deployments;
exclude missing capability metadata. Display deployment IDs separately from model
names/versions. Retain saved/manual choices and Default effort for unknown models.
Coalesce refreshes, clear failed/stale results and reject in-flight responses after
endpoint/resource/subscription changes. Sanitize errors. No automatic selection
or replacement. Refresh never starts an agent, signs in or sends inference.
Inventory and credential presence do not prove account, inference, tool or effort support.

Re-ground the following existing authentication inputs against official exact-version
CLI/Azure docs at implementation admission. Do not infer other combinations.

| CLI/authentication | Fresh launch and resume reconstruction |
| --- | --- |
| Claude Entra ID | Native Foundry resource/deployment environment; execution-host SDK default credential chain; blank inactive credentials/competing routes. |
| Claude API key | Same routing; inherit `ANTHROPIC_FOUNDRY_API_KEY`, blank inactive token/competing routes. |
| Claude supplied bearer token | Same routing; inherit `ANTHROPIC_FOUNDRY_AUTH_TOKEN`, blank inactive key/competing routes; host owner renews it. |
| Codex API key | Azure `/openai/v1` Responses route; stable reserved provider table with `env_key=AZURE_OPENAI_API_KEY`. |

The same provider owner plans fresh launch and resume from the admitted nonsecret
binding. Reconstruct Claude environment because native `env_of()` only recreates
browser-task metadata. Independently verify Codex provider/model/effort/Fast retention.
Values remain in the admitted execution-host environment, never argv, settings,
labels, logs, stored records or persisted core environment overrides.

Resume retains recorded routing, deployment, authentication, native session and
hooks. New defaults do not rewrite it; changed retained routing refuses before
interruption or authority replacement. Model selection does not choose an account;
configuration fingerprints do not attest account identity. Credential rotation alone
does not change the fingerprint. Save-only new-start choices remain revision-bound,
send no prompt and preserve task holds. A stopped recorded chat is not unstarted.
No silent Personal fallback, remote Azure expansion, new cloud or cross-CLI reuse
of an Azure conversation. Deployment discovery is unrelated to the separately
owned LogTape/JSON/command-discovery research.

### Recovery disposition

All evidence here is source-inspected, not runtime-qualified.

| Behavior | Chosen disposition/owner | Independent qualification or gap |
| --- | --- | --- |
| Ordinary crash/manual resume | Reuse native `T/revive.py` and resume through one admission owner. | Same session/history/provider, one execution; restart is not reboot. |
| Kept terminal/screen reconnect | Reuse native hub/screens/attach. | Current execution and screen identity; reconnect is not dispatch proof. |
| Convenience failed starts | Reuse native where qualified; conditional retirement. | Bounded handling without duplicate launch; exact convenience gaps remain human choices. |
| Missing history | Native fresh fallback remains a gap decision. | Explicit new-session identity; allow fresh fallback or retain hold per case. |
| Provider/model/effort/Fast | Port binding enforcement; reuse qualified parsing. | Both CLI resumes after defaults change; labels do not prove provider/account. |
| Unknown core submission | Port journal guarantee into `T/launch_admission.py`. | Never-submitted versus submission-uncertain; no inventory-based release/retry. |
| Late old sender/replacement | Port application fence; native process authority remains a gap. | Delayed sender cannot regain dispatch; journal alone cannot fence unknown PTY execution. |
| Manual uncertain recovery/reboot | Retain old-state custody; port demonstrated requirements only. | Exact identity/revocation, reboot evidence and past-effect uncertainty remain separate. |
| Provider retries/queued delivery | Reuse qualified native retry; port missing guards/receipts. | No replay after uncertain effect or changed binding. |
| Task cleanup/approval/lifecycle holds | Reuse native owners; port uncovered guarantees. | Exact approval head, owned descendants, no unrelated-worker effects. |
| Protected update | Retain operational hold; cutover admission separate. | Native restart is not idle-safe update proof. |
| Plugins/public persisted state | Required Q/R compatibility review. | Registry/failure isolation, last-good behavior, outbox/drafts, labels/state formats; no automatic import. |

Use one revival/admission owner for task and coordinator dispatch. No competing
revival loops. Native receipt/revocation gaps remain held until independently proved
or Nathan chooses the exact tradeoff. Do not automatically port all old lifecycle code.

## Verification contract

Check retains native tagged suites. Old Foundry/core-rewrite workflow bodies and
their test/sensitivity obligations remain fixed F sources, recorded by hash in the
inventory. Q must port or explicitly reconcile every obligation. Default native
tests do not establish fork parity. Old optional production-plugin proof is not
silently considered covered by default tests.

Root runs `python3 bin/check-migration`, its public-CLI checkpoint tests
(`test/test_migration.py`), the A1 provider and discovery tests (`test/test_providers.py`,
`service/azure-deployments.test.ts`), the C1 discovery tests (`core/chat-find.test.js`,
`test/test_session_discovery.py`) and every native Check command. CI owns frozen dependency installation, web
generation, shared-copy/parser checks, typecheck, Bun service/core/web tests,
Python tests and production build. Locally run only `bun run typecheck`.
Missing dependencies/generated web sources are prerequisite blockers, not authority
to install or build. Static declaration counts are not executed test counts.

Dependent proof crosses public commands and actual process/durable-state interfaces.
Bitbucket covers zero-effect preflight, complete exact checks, current fields, lost
responses, reopen/no retry, same-UUID reconciliation, two-machine exclusion and merge
refusal. Azure covers both filters, scopes/subscriptions, stale responses, sanitized
manual fallback, save-only effects, each admitted authentication route and bound resume.
Recovery separately covers crash, missing history, uncertain launch and late sender.
Task locks and core document CAS do not inherently establish receipts or idempotency.

## State and cutover

No live state conversion occurs in S0. Separate service data does not isolate HOME,
core, task ownership, shared helpers/hooks or synchronization. No installer/service/
mod init or real-home parity command is admitted. Existing conversations, worktrees,
credentials and runtimes are preserved and are not source fixtures.

Hold state carryover, conversation migration, genuine fresh-session gaps, manual
recovery, costs, rehearsal budgets, shared merges and deployment for named decisions.
Rollback pairs exact executable/core versions with matching state/configuration,
templates, helpers, links and hooks. Unknown effects/claims cannot disappear during
conversion. Independently stop authorized new writers before restoration; restoring
a database does not prove an old process ended.

Preserve F/U/P. After PR3's recorded decision, qualify main/integration composition
explicitly without rebasing F or silently folding P into ancestry. Source admission
does not authorize installation, native requests, shared merge, state import or cutover.
Root's S0 inspection and CI precede every dependent phase.

## Implementation and review handoff

Implementation and independent review are separate assignments. Root qualifies S0
and owns the isolated source handoff. Review uses the exact committed candidate
and its scoped brief; an implementer does not independently approve its own work.
Operational assignments and trust/readiness receipts belong to the native
conversation and runtime handback, not this portable repository contract.

Azure implementation and independent review require
`my-second-brain-playground:cli-design`, maintain/extend existing-project route.
Each execution harness resolves and reads its active installed SKILL.md and required
references first. Resolve that harness's active registration rather than a fixed
cache path or version. Do not refresh/install plugins or borrow another machine's paths.
Use the complex profile because authentication, authority, ordered effects and
uncertain submissions are involved. Preserve native Python task CLI ownership and
host output/exit/serialization contracts; do not bootstrap, compose, replatform,
install Fallow or change dependencies/tooling to satisfy a template.

Capture affected commands/entry points, inputs, effect classes, public results and
current contracts. Trace source help, exact argv/environment construction, official
Claude/Codex Azure contracts, authenticated mailbox results, persisted provider/session
bindings, launch journals and existing process regressions. Prove secret redaction,
unsupported-route refusal before effects, revision/fencing/uncertainty and truthful
repair hints through public entry points with reopened persistence. Return scoped
code/help/tests where affected, expected-versus-observed matrices and exact-candidate
Root CI evidence. Local verification stays typecheck-only.

Contract Core 2.0 JSON envelopes, LogTape and command discovery remain separate,
unapproved adoption work. Record compatibility gaps rather than claim full Contract
Core conformance or silently alter defaults. Autonomous recovery, breaking defaults,
extra clouds and remote execution remain human choices. This requirement starts no
Azure phase, new agent, provider probe, runtime change or external write in S0.
