# Personal and Azure Foundry

**Settings → Agents → Connection → Provider** selects Personal or Azure Foundry
at the existing Everywhere, machine or space scope. It applies to coordinators,
tasks and reviewers on their next launch. Changing settings does not restart
running agents. No account, tenant, endpoint or credential store is built in.

## Compatibility

Personal is the default and preserves existing native CLI configuration,
environment and sign-in. It does **not** guarantee a personal subscription:
if the CLI already uses an organizational provider, that remains its default.
Forcing a personal account would be a separate, compatibility-breaking decision.
No CLI home, binary, launcher, service, shared configuration or lifecycle hook
is replaced. Legacy agent records without a provider binding remain resumable
under Personal. There is no destructive database migration or new dependency. Optional selection, configuration revision and launch-attempt records use the existing store.

Azure uses an explicit deployment per CLI instead of the personal model catalogue.
The UI retains personal model choices for switching back. Existing effort settings
still apply; deployment support for that effort must be qualified before use.
Claude maps its default Opus, Sonnet and Haiku aliases to the selected deployment,
including background work. Separate model aliases are outside this change.
Autopilot and remote Azure execution refuse before launch. Personal retains their
existing behavior. Additional clouds and remote credential delivery remain open
product decisions, rather than silently inheriting unrelated credentials.

## Task and agent selection: new starts only

The model line and existing agent menu open an Azure deployment selector when
Azure is configured. For a genuinely unstarted task or coordinator, **Save for new
start** stores the CLI, deployment and effort for that chat. It sends no prompt,
starts no process and changes no task hold, dependency or merge policy. **Use
configured defaults** clears that override. A waiting or stopped agent with a
launch record is an existing conversation, even when its task says To do. Its
selector is locked; this release does not switch its deployment in place.

Under Agents settings, Tasks and Coordinators have separate Azure deployment
defaults. They inherit the configured CLI deployment when unset; Personal model
settings remain separate. Newly created tasks snapshot their deployment like their
existing model choice. Existing tasks are not backfilled. A per-chat override wins
on first launch. The model line distinguishes a saved choice from an observed model.

The selector uses the existing inventory and manual entry. Effort choices require
a known model in the installed CLI catalogue, either matched directly by deployment
ID or by the underlying model reported in inventory. Unknown manual deployments
can use Default effort. Discovery is read-only and does not prove inference access.

Saves compare an opaque revision token and reject stale views. A saved explicit
choice also binds the nonsecret provider configuration; changing its connection
requires saving again or clearing the choice, never silently falling back to
Personal. The server refuses selection edits while a start is pending.

Task and coordinator restarts preflight provider compatibility, execution route
and credential availability before revoking authority or stopping an old process.
Admission checks the revision again, then carries the checked plan through the
stop/start operation. Existing Azure conversations resume their recorded deployment
even if a new-start default changes; changing endpoint, provider or auth still
refuses. No credential value is stored in a selection or revision token.

Existing per-target guards, durable unconfirmed launch records and launch-specific
hook reconciliation remain in force. A lost start response cannot be retried as
another launch until reconciled. Shutdown refuses before native submission. The
bounded Statechart design is not a proof of arbitrary multi-process execution,
crash durability or external core idempotency. No new live-agent qualification is
claimed for this slice. Rollback must retain candidate state and Azure-bound chats.

## Configuration and authentication

| CLI | Endpoint configuration | Authentication choice | Credential owner |
| --- | --- | --- | --- |
| Claude Code | Azure resource name; native CLI constructs the public Azure Anthropic endpoint | Entra ID (default) | Native Azure SDK default credential chain on the execution host, such as an existing Azure CLI login |
| Claude Code | Same | API key | `ANTHROPIC_FOUNDRY_API_KEY` inherited by the local core process |
| Claude Code | Same | Bearer token | `ANTHROPIC_FOUNDRY_AUTH_TOKEN` inherited by the local core process |
| Codex | `https://RESOURCE.openai.azure.com/openai/v1` | API key | `AZURE_OPENAI_API_KEY` inherited by the local core process |

Configure only the fields for CLIs you intend to use. Deployment names must name
actual deployments in your resource. The public Azure endpoint restriction rejects
userinfo, query strings, fragments, alternate paths, ports, custom domains and
other clouds. Do not enter keys or tokens in any setting. Empty fields are allowed
while configuring; incomplete or unsupported configuration refuses at launch.

Supply credentials through your own host credential owner **before starting the
candidate's separate core session**. Setting an environment variable only in the
Shepherdr server or a later shell cannot change an already-running core's inherited
environment. Do not restart a shared core to satisfy this requirement. No login,
credential lookup command, token refresh service or credential storage is added.
For Entra ID, the native SDK handles its supported credential refresh. A supplied
bearer token remains the host owner's responsibility, including expiry and renewal.

Claude's token has native precedence over its key and credential chain. The launch
settings blank inactive authentication methods and competing provider variables,
and pin the resource and deployment aliases. The active credential is inherited,
not copied into the settings file. Existing managed CLI policies still apply;
conflicting managed routing must be resolved by its owner before qualification.

Codex receives per-run `-c` overrides for a custom Responses provider and an
`env_key` reference. Its provider ID uses the reserved `shepherdr_azure_` prefix
and a stable configuration hash, so an existing provider named `azure` is not
changed or reused. Do not define this reserved namespace in native configuration:
Codex merges provider tables. Native managed policies remain authoritative.
Microsoft's Codex guide currently says Entra ID is unsupported. This UI therefore
does not present a token, Azure CLI or command-helper mode for Codex. Generic
OpenAI custom-provider features are not evidence of supported Azure authentication.

## Deployment discovery

In **Settings → Agents**, set the Claude resource or Codex endpoint, then use
**Refresh deployments** beside that CLI's deployment picker. **Enter manually**
remains available without Azure CLI or management-plane permissions. Refreshing
does not select a model, start an agent, send an inference request or modify the
host's Azure login. Selecting a deployment applies to new conversations; the
existing conversation fingerprint still refuses changing a retained chat's route.

Discovery uses the local execution host's `az` on PATH and its existing login.
An optional **Discovery subscription ID** pins a subscription UUID. Blank uses
`az account show`; the resolved ID is passed explicitly to subsequent reads and
shown with the inventory timestamp. This subscription controls discovery only,
not the inference credential. Azure public cloud is required. Remote discovery
is refused, and Everywhere requires exactly one execution machine.

The read-only commands are `az account show`, `az cognitiveservices account list`
and `az cognitiveservices account deployment list`. The resource must match the
configured endpoint/resource uniquely in that subscription. The login needs read
access to the subscription's Cognitive Services resource inventory and that
resource's deployments. Resource-only permissions may be insufficient for the
subscription inventory lookup; manual entry needs neither permission.

The picker shows deployment IDs separately from model names and versions. It
offers only `Succeeded` deployments with the corresponding format and advertised
capability: OpenAI plus `responses` for Codex, Anthropic plus `chatCompletion` for
Claude. Missing capability metadata is excluded; manual entry remains possible.
Inventory does not prove CLI/tool compatibility, inference access or effort support.
No fallback or automatic selection occurs when a deployment disappears.

Results stay in memory at the requested settings scope and disappear on restart,
failed refresh, or changes to the resource, endpoint or discovery subscription.
Late responses cannot restore choices for an old configuration. Refresh explicitly
after external login or deployment changes. Raw Azure CLI diagnostics are not
returned to the UI; failures give a bounded repair path without exposing secrets.

## Credential handling

Credential values never enter the provider planner, saved settings, generated
launch files, command arguments, agent records or terminal environment overrides.
Core persists caller environment overrides for restart, so sending a credential
there would put it on disk. Credentials instead remain in core's inherited
process environment. A short local environment-presence check reports only an
exit status before grant allocation or terminal creation. It neither reads a
credential store nor makes a provider request. Probe errors are replaced with a
message naming only the required variable. This is presence, not authentication
proof. The host and native CLIs retain their own security and logging policies;
this integration is not a secret sandbox against same-user processes.

A saved conversation records a nonsecret route/configuration fingerprint. Changing
its route, Azure endpoint, explicitly requested deployment or authentication method refuses relaunch,
including resume. Start a separate conversation to change those values. Rotating
a credential without changing the method does not alter the fingerprint; account
identity is not pinned or attested by it. Same-configuration resume preserves the
native session ID and hooks. Child launches cannot cross Personal/Azure routes.
Cross-CLI Azure backup cannot reuse an existing conversation and refuses; select
Backup off when using that combination. No silent personal-provider fallback is
added. Personal model catalogue and quota checks do not prove Azure readiness.

## Model choices for new starts

Task and coordinator settings have separate Azure deployment defaults for each
CLI. Personal model defaults are retained separately. A conversation that has
never launched can save an explicit agent, deployment and effort through its
model menu. Saving does not start a process, release a task hold, or change global
settings. Use configured defaults clears that conversation override. Existing
conversations, including stopped or waiting agents, show a locked selector.
Creating a task still follows the existing startup behavior: a task marked for
later can already have a waiting agent. This feature does not add agent-free
backlog creation.

Discovery supplies deployment identifiers; known model metadata supplies effort
choices. Unknown deployments support Default effort until compatibility is known.
Manual deployment entry remains available. Refresh does not select a replacement.
Changing global deployment defaults affects new conversations; an existing
Azure conversation retains its bound deployment during compatible resume.

Selection saves compare a token containing persisted settings and selection
revisions plus current launch identity. Changing a selection away and back still
invalidates an older open selector. Restart preflight validates provider binding,
execution route and credential presence before revocation or stopping the old
worker. Admission freezes the checked provider plan. Shutdown prevents terminal
submission, and an unconfirmed durable launch blocks blind retry after a lost
reply or application reload. These guards assume one application owner per home.

### Launch admission and recovery boundaries

Configuration revisions contain settings and selection revisions, separately from
launch identity. Recording an attempt does not invalidate its own admission.
`CoreAgents` checks the admitted revision before claiming, recording and submitting,
and checks the captured parent launch, terminal address and PID across asynchronous
work. A changed revision refuses and requires fresh validation. Azure task starts
preflight their worker and required coordinator before preparing the checkout,
seeding includes or starting either process. Existing Personal task preparation
and capacity holds remain unchanged.

`CoreLaunches` persists a per-chat claim and an attempt keyed by launch UUID:

| Stored state | Meaning | Permitted next step |
| --- | --- | --- |
| `never-submitted` | No sender has crossed the durable dispatch gate | Cancel the exact claim transactionally, then validate a fresh attempt |
| `submission-uncertain` | Dispatch may have occurred | Reconcile that launch identity; no blind retry or cancellation |
| `confirmed` | Core returned a terminal or reconciliation matched its launch labels | Keep the existing terminal/conversation binding |
| `cancelled` | The never-submitted attempt lost dispatch authority | Its delayed continuation must refuse; a new attempt can claim |

The final revision/parent check and transition to uncertainty occur in one SQLite
transaction. `CoreAgents.launch` immediately calls `CoreSession.call`, which calls
`CoreClient.call` and writes the RPC synchronously. There is no intervening await
or application callback, so settings actions in this application cannot interleave.
The socket write, not recording an agent or allocating a grant, is the external
submission boundary. A crash after committing uncertainty but before the write
is deliberately conservative: it remains uncertain.

The internal `recoverUnsubmitted(chat, launch)` operation requires that exact
persisted claim, a never-submitted attempt and an unchanged conversation identity.
Cancellation and the sender's final transition serialize on the same SQLite store.
The old sender must check the claim before recording and dispatch; a late
continuation cannot start or revoke its replacement's mailbox grant. This is
application dispatch fencing, not a core cancellation API. Recovery is not wired
to a button, scheduler or startup routine. Automatic versus user-triggered recovery
remains an explicit product decision.

Inspected core 0.1.16 exposes `terminal.run`, terminal inventory and live-terminal
name uniqueness. It exposes no durable launch idempotency key or receipt proving
an uncertain request can never submit. An empty inventory therefore authorizes
nothing. Legacy records without a journal also cannot establish non-submission.
Unknown outcomes keep their original identity until a matching terminal is found.

The supported ownership boundary is one application owner per home. The launcher
serializes startup/shutdown with its lifecycle lock; its lock is not held for the
server lifetime. This change does not support bypassing the launcher to run
multiple application servers, old binaries that ignore claims, or external SQLite
writers racing configuration updates. An independently opened test source exercises
claim fencing, not arbitrary multi-server support.

Restart admission before the old process stops remains in memory. A crash after
stopping that process but before claiming its replacement loses that plan; this
change does not automatically recover it. Parent/child creation is not atomic:
if a later check refuses, an already-created valid coordinator or checkout can
remain. No live rerouting or deployment is included.

The prototype's walkthrough Reset fix stays on the separate
`prototype/azure-selection-lifecycle` branch. The prototype is a simulation and is
not shipped with this application.

## Official contracts and version scope

Consulted on 4 November 2026:

- [Claude Code on Microsoft Foundry](https://code.claude.com/docs/en/microsoft-foundry):
  provider/resource variables, all three authentication methods, token precedence
  and deployment aliases.
- [Claude settings](https://code.claude.com/docs/en/settings): invocation settings
  compose environment and lifecycle hooks without editing shared user files.
- [Codex advanced configuration](https://developers.openai.com/codex/config-advanced/):
  custom providers and per-run TOML overrides.
- [Microsoft's Codex Azure guide](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/codex):
  the v1 Responses endpoint, deployment names, API-key reference and current Entra
  ID limitation. No legacy API-version query is needed for this route.
- [Codex 0.166.0 configuration merging](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/config/src/merge.rs)
  and [override parsing](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/utils/cli/src/config_override.rs).
- [herdr-core 0.1.16 terminal launch](https://github.com/herdrdev/herdr-core/blob/v0.1.16/crates/herdr-core/src/api/run.rs)
  and [terminal records](https://github.com/herdrdev/herdr-core/blob/v0.1.16/crates/herdr-core/src/terminals.rs):
  caller overrides are saved as `restart_env`; the inherited environment is not.
- [Azure CLI deployment inventory](https://learn.microsoft.com/en-us/cli/azure/cognitiveservices/account/deployment?view=azure-cli-latest)
  and [deployment response schema](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/deployments/list?view=rest-aiservices-accountmanagement-2024-10-01):
  read-only listing, model identity, provisioning state and capability metadata.

This draft targets Shepherdr v2.1.1, herdr-core 0.1.16, Claude Code 2.1.318 and
Codex 0.166.0. These are inspected versions, not a claimed minimum or native
acceptance matrix. Older CLI versions and future configuration changes require
separate qualification. No installation or automatic CLI update is part of this
feature. Existing native CLI version checks remain in place.

## Verification and rollback

`test/core-providers.test.ts` exercises the existing settings and launch interfaces
with a temporary real settings store and a fake core protocol. It covers default
pass-through, legacy and same-provider resume, all advertised authentication
choices, credential-reference-only launches, hooks, refusal before side effects,
endpoint validation and scope inheritance/reset. Run in CI alongside the core
settings/agents regressions. Repository policy permits only `bun run typecheck`
locally. `test/core-azure-deployments.test.ts` crosses CoreSettings and CoreFiles
with a fake core protocol, checking filtering, explicit selection, subscription
pinning, errors, scope and stale responses. CI deliberately disables capability
filtering to establish that the regression fails, then restores and runs the suite.
Protocol tests do not establish Azure authentication or native rendering.

Before deployment, authorize isolated native acceptance for each desired CLI/auth
combination. Verify provider/account/deployment/effort, real hook events, first turn,
resume, token expiry behavior and stop/restart. Keep existing delivery running.
An explicitly authorized isolated Mini canary on 4 November 2026 completed a
Codex 0.166.0 Azure `gpt-6.1-sol` High first turn and resume in the same native
session, with SessionStart, UserPromptSubmit and Stop hook evidence. Both disposable
terminals were stopped. The native UI displayed both replies and the Azure Foundry
label. The stock application's process/boot identity and core inventory remained
unchanged across that canary.

A separate authorized Claude Code 2.1.318 canary then completed an Entra ID
`claude-sonnet-5-5` High first reply and same-native-session resume through the
actual Shepherdr UI. Native `/status` identified Microsoft Foundry and the configured
resource. Both launches emitted SessionStart, UserPromptSubmit and Stop hooks;
the transcript contained both expected replies and zero tool calls. Both canary
terminals were stopped, its repository stayed clean, and the existing Codex session,
prior terminal inventory and stock application identity were unchanged.

This qualifies those exact two routes and CLI versions. Claude API-key and supplied
bearer-token execution, token expiry, remote execution and additional clouds remain
unqualified. No live installation was replaced. An unrelated Monash catalogue refresh
reported missing configured deployments; the exact Claude target was independently
verified through Azure's deployment API before the successful native test.

For an unused candidate, reset Provider to Personal (and any machine/space
overrides), then stop only that candidate. The CLI homes and shared configuration
need no restoration. For a candidate that has run, preserve its state directory,
transcripts and CLI homes; stop its identified workers before downgrading. Do not
resume Azure-bound conversations with stock Shepherdr: stock lacks the binding
check and would use its native defaults. Keep that state with the candidate until
its conversations are retired or an explicit migration is approved. Removing the
candidate does not require stopping the old setup or deleting credential stores.

## Protected preview updates: unresolved runtime contract

A model-selector update restarts the application, even when it keeps core and its
workers running. `CoreSource.start()` calls `closeInterrupted()`: outstanding
permission cards are closed, native refusals can be delivered, and a restart
notice is queued to the existing worker through `saveAndDeliver`. Starting core
observation and delivery can then send that notice and existing queued messages.
Unchanged PIDs and native session IDs therefore do not establish an unaffected
worker or absence of model requests.

The 4 November isolated update to `9a99da6` preserved all 66 native worker process
identities, both core inventories, settings and agent/session bindings. It also
closed two stale permission cards and queued an automatic notice. Delivery was
unconfirmed. The implementation is not qualified for effect-free preview updates.

A preflight database count alone is insufficient: a worker can ask for permission
or queue delivery after inspection. The existing lifecycle lock serializes
launcher start/stop, not agent activity. There is no supported core handover receipt
that proves an application restart preserves all in-flight permission responses.
Do not repeat a live preview update on the strength of the earlier process check.

The pending decision is whether protected updates refuse while any worker is live
or unconfirmed, require a stronger permission/delivery handover protocol, or allow
explicitly approved cancellation and notification. No policy has been selected,
no new global default is implied, and no protection flag is implemented yet.

## Final native acceptance plan, not executed

The prior canaries qualify their earlier candidate only. The final model-selector
candidate needs bounded native acceptance after explicit authorization. Do not use
live delivery chats or tasks for this proof.

Before authorization, prepare a private evidence manifest containing the exact
candidate commit and CI artifact hashes, CLI/core versions, isolated app home and
core session, disposable repository, deployment IDs, authentication methods and
requested effort. Include protected application boot/PID and worker/session
identities, a settings snapshot hash, existing pending permission/delivery counts,
and a finite prompt/agent budget. Keep credential values outside the manifest.
Resolve the protected-update policy before changing another running preview.

For each desired CLI, qualify these cases through the actual task and coordinator
controls, using separate disposable conversations:

| Case | Required observation |
| --- | --- |
| Save a new-start deployment/effort | Reload preserves the choice; zero terminal or model requests; task holds unchanged |
| Launch the approved task/coordinator choice | Native provider, requested deployment, observed model/effort and hook identity match the admitted manifest |
| Change defaults while the disposable conversation exists | That conversation stays on its recorded binding; no process restart or extra turn occurs from the settings edit |
| Explicitly resume with the same binding | New launch identity, same native session, recorded deployment and lifecycle hooks; one approved resume turn |
| Request a changed endpoint/auth/deployment for that retained conversation | Refuse before interruption, grant replacement or native submission |
| Stop the disposable proof | Exact proof terminal exit confirmed; protected workers and conversations retained |

Start with the already approved authentication contracts, Claude Entra ID and Codex
API key, only if Nathan authorizes those exact routes for this candidate. API-key
and supplied-token Claude execution and token-expiry qualification remain separate
unproved combinations. Inventory refresh alone is not inference or tool support.
Personal native sign-in/defaults also require an explicitly approved disposable
route if native compatibility is to be claimed beyond protocol regression proof.

Compare before/after identities and persisted records. Report permission changes,
new queued messages, unexpected native/model activity and unconfirmed outcomes,
even when all worker PIDs match. A lost reply must reconcile the same launch; it
must not spend the remaining budget on blind retries. Keep raw receipts private.
Do not call native acceptance complete from the prototype, protocol fakes, green
CI, a saved deployment label or an earlier candidate's canary.
