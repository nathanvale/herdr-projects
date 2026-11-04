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
under Personal. There is no database migration or new dependency.

Azure uses an explicit deployment per CLI instead of the personal model catalogue.
The UI retains personal model choices for switching back. Existing effort settings
still apply; deployment support for that effort must be qualified before use.
Claude maps its default Opus, Sonnet and Haiku aliases to the selected deployment,
including background work. Separate model aliases are outside this change.
Autopilot and remote Azure execution refuse before launch. Personal retains their
existing behavior. Additional clouds and remote credential delivery remain open
product decisions, rather than silently inheriting unrelated credentials.

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
its route, Azure endpoint, deployment or authentication method refuses relaunch,
including resume. Start a separate conversation to change those values. Rotating
a credential without changing the method does not alter the fingerprint; account
identity is not pinned or attested by it. Same-configuration resume preserves the
native session ID and hooks. Child launches cannot cross Personal/Azure routes.
Cross-CLI Azure backup cannot reuse an existing conversation and refuses; select
Backup off when using that combination. No silent personal-provider fallback is
added. Personal model catalogue and quota checks do not prove Azure readiness.

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
unchanged across that canary. No Claude Azure runtime, token expiry, remote execution
or additional cloud is qualified by this proof. No live installation was replaced.

For an unused candidate, reset Provider to Personal (and any machine/space
overrides), then stop only that candidate. The CLI homes and shared configuration
need no restoration. For a candidate that has run, preserve its state directory,
transcripts and CLI homes; stop its identified workers before downgrading. Do not
resume Azure-bound conversations with stock Shepherdr: stock lacks the binding
check and would use its native defaults. Keep that state with the candidate until
its conversations are retired or an explicit migration is approved. Removing the
candidate does not require stopping the old setup or deleting credential stores.
