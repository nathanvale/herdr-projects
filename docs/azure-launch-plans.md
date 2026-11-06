# Azure launch plans and deployment discovery (A1)

Source phase A1 of the [migration contract](migration/upstream-v3.1.3.md). It adds two native
owners and nothing else:

- `mods/tasks/bin/herdr_task/providers.py`: nonsecret provider bindings and launch plans.
- `service/azure-deployments.ts`: explicit, read-only deployment discovery.

This is source and authored regressions only. Nothing here is CI-proved, deployed or natively
qualified, and no Azure launch is dispatched. The [2.x reference](azure-foundry.md) stays a
historical document.

## What works now, and what is held

| Behavior | State in A1 |
| --- | --- |
| Personal (the default) | Unchanged. No provider setting, or `route: personal`, adds nothing to a launch. |
| `herdr-task provider plan` | Shows the plan for one CLI. Reads no credential, starts nothing, runs no `hc`. |
| Start, queue, resume, switch or backup under an Azure binding | Refused before any worktree, task state or terminal effect. |
| A valid Azure plan | Held: `dispatch: "held"`. Launch admission (L1) and bound resume (A2, L2) are pending. |
| Discovery | A module with regressions. No Settings control calls it yet (A2). |
| Assistants (coordinators) | Not gated: their launch path is A2's. Only task agents consult the binding. |

Azure dispatch stays off on purpose. A launch record does not yet carry its binding, so a resume
would follow today's settings and could reroute an existing conversation.

## The binding

A `provider` section in Shepherdr settings, at Everywhere, a machine or a space. The most
specific layer wins field by field. A field left out (or `null`) follows the layer above; an
empty string is that layer's own empty value.

| Field | Meaning |
| --- | --- |
| `route` | `personal` (default) or `azure-foundry`. Any other value refuses; there is no silent Personal fallback. |
| `claude_resource` | The Azure resource name for Claude Code. Not a URL. |
| `claude_deployment` | The deployment Claude Code uses. |
| `claude_auth` | `entra-id` (default), `api-key` or `bearer-token`. |
| `codex_endpoint` | `https://RESOURCE.openai.azure.com/openai/v1` exactly. |
| `codex_deployment` | The deployment Codex uses. |
| `codex_auth` | `api-key` only. |
| `azure_subscription` | Optional subscription UUID for discovery only. |

Any other field in the section refuses, naming the field and never its value, so a key pasted
into settings is not read as configuration. `herdr-task` has no command that writes this section:
provider connection stays a human Settings control (A2 adds the controls). Settings pushed to
another machine are a copy; an Azure route there refuses, so Azure stays on the machine that owns
the settings.

## Supported combinations

Each row is the official contract for the inspected CLI version. No other combination is planned.

| CLI and sign-in | Plan | Credential |
| --- | --- | --- |
| Claude Code, Entra ID | `--settings` env: `CLAUDE_CODE_USE_FOUNDRY=1`, `ANTHROPIC_FOUNDRY_RESOURCE`, the three `ANTHROPIC_DEFAULT_*_MODEL` aliases and `--model` set to the deployment | None named. The Azure SDK default credential chain on the execution host. |
| Claude Code, API key | Same routing | `ANTHROPIC_FOUNDRY_API_KEY`, inherited. |
| Claude Code, bearer token | Same routing | `ANTHROPIC_FOUNDRY_AUTH_TOKEN`, inherited. The host owner renews it. |
| Codex, API key | `-c model_provider` and one reserved `model_providers.shepherdr_azure_<fingerprint>` table: `base_url`, `env_key`, `wire_api="responses"`, `requires_openai_auth=false`; `-m` set to the deployment | `AZURE_OPENAI_API_KEY`, inherited. |

Claude's plan also sets every competing route and inactive credential variable to an empty
string, which Claude Code treats as unset. The active credential's variable is left out of the
plan entirely. Codex with Entra ID or a bearer token refuses: Microsoft's guide says Entra ID is
not available for Codex. A `--settings` file path, or an argv that names its own Codex provider,
also refuses.

The fingerprint is the SHA-256 of the CLI, endpoint or resource, deployment and sign-in method. It
uses the same expression as the 2.x planner, so equal configuration gives an equal fingerprint
and Codex provider name. It does not identify an account, and rotating a credential does not
change it.

## Credential custody

`providers.py` never reads an environment value. A plan carries a variable's name only. Values do
not enter argv, settings, labels, task records or output. The environment-presence preflight from
2.x is not ported: it belongs with launch admission (L1). Presence would not prove sign-in anyway.

## Discovery

`AzureDeployments.refresh()` runs three read-only Azure CLI commands on this computer:
`az account show`, `az cognitiveservices account list` and
`az cognitiveservices account deployment list`. It never signs in, starts an agent, sends a model
request or selects a deployment.

- Offered: `Succeeded` deployments with format `OpenAI` and capability `responses` (Codex), or
  format `Anthropic` and capability `chatCompletion` (Claude Code). Missing capability metadata
  is excluded. The deployment ID, model name and version are separate fields.
- Subscription: an optional UUID is passed to `az account show`. The resolved ID is then named on
  every later read. A different answering subscription refuses.
- Bounds: Azure public cloud, this computer only, and exactly one execution machine at the scope.
- Cache: in memory, per scope and CLI, keyed by resource or endpoint and subscription. A view
  under another configuration shows nothing. A late response is dropped. A failed refresh clears
  the scope's choices.
- Errors: fixed repair lines only. Azure CLI's stderr is never read.
- Manual entry: `deploymentName()` validates a typed name and needs no inventory.

An inventory does not prove account identity, inference access, tool support or effort support.

## Still pending

- A2: Settings controls, per-role deployments, new-start selectors, coordinator launches, and
  wiring discovery to Refresh and to configuration changes.
- L1: one dispatch authority, credential-presence preflight and durable uncertainty.
- A2 and L2: recording a launch's binding and enforcing it on resume and revive.
- Q: CI on the exact candidate and native qualification of each sign-in route.

Known limits of this slice: the `fable` alias is not pinned for Claude Code; revive retypes a
recorded argv without consulting the binding (no Azure agent can exist yet); discovery assumes the
service's computer is the local execution host.

## Official contracts and versions

Consulted 6 November 2026 for Claude Code 2.1.318, Codex 0.166.0 and Azure CLI 2.91.0. These are
inspected versions, not a minimum or an acceptance matrix.

- [Claude Code on Microsoft Foundry](https://code.claude.com/docs/en/microsoft-foundry): the
  resource variable, three sign-in methods, bearer-token precedence and model pinning.
- [Claude Code environment variables](https://code.claude.com/docs/en/env-vars): provider
  selectors, `CLAUDE_CODE_SKIP_FOUNDRY_AUTH`, and an empty settings `env` value read as unset.
- [Claude Code settings](https://code.claude.com/docs/en/settings) and
  [CLI reference](https://code.claude.com/docs/en/cli-reference): inline `--settings` JSON, its
  precedence, and `--model`.
- [Microsoft's Codex guide](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/codex):
  the `/openai/v1` base URL, `env_key`, `wire_api = "responses"` and no Entra ID support.
- [Codex 0.166.0 provider schema](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/model-provider-info/src/lib.rs)
  and [override parsing](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/utils/cli/src/config_override.rs):
  `env_key`, the Responses-only wire API, `requires_openai_auth`, and configured providers
  extending the built-in set.
- [Azure CLI deployment list](https://learn.microsoft.com/en-us/cli/azure/cognitiveservices/account/deployment)
  and [deployment schema](https://learn.microsoft.com/en-us/rest/api/aiservices/accountmanagement/deployments/list?view=rest-aiservices-accountmanagement-2024-10-01):
  read-only listing, model format, provisioning state and capabilities. Argument names were also
  read from the installed CLI's own help.

Every Claude Code variable the plan names was also found by name in the installed 2.1.318 binary.
That confirms the names exist in that version; it does not qualify their behavior.

## Regressions

Authored, not run locally (repository policy allows only `bun run typecheck`). Root CI runs them.

- `test/test_providers.py`: the public `herdr-task` process with a recording `hc` stand-in.
  Personal pass-through, refusal before effects for start, queue, resume and switch, the four
  plans against written-out values, layering, and no credential value anywhere.
- `service/azure-deployments.test.ts`: the discovery class against a stand-in `az` process.
  Filters for both CLIs, subscription pinning, scope, memory-only state, stale responses,
  sanitized failures, bounds and timeout.
- `test/azure-binding.cases.json`: one field table both suites judge.

These stand-ins do not prove Azure sign-in, inference, a real launch or the real Azure CLI.

## CLI design notes

Route: maintain and extend the existing native Python CLI, complex profile. `provider plan` is an
`inspect` command. It follows the host contract: `--json` prints one object, a refusal prints
`{"error": ...}` and exits 1, and without `--json` a refusal goes to stderr. Contract Core 2.0 envelopes,
typed exit classes, a station catalogue, `--discover` and LogTape are not adopted; those remain
separate, unapproved work and are recorded here as known gaps.
