# Personal and Azure Foundry

This fork adds **Settings → Agents → Connection → Provider**. Choose Personal
or Azure Foundry at the existing Everywhere, machine or space scope. The choice
applies to coordinators, tasks and reviewers in that scope on their next launch.
Changing it leaves running agents alone. Existing settings default to Personal.

Azure requires explicit deployment names, independent of the personal model
catalogue. Enter the Claude Azure resource name and Claude deployment, or the
Codex Azure OpenAI v1 endpoint and Codex deployment, for each CLI you intend to
use. Model rows show the deployment while Azure is selected. Personal model
choices are retained for switching back. Effort remains explicit; deployment
support for that effort must be qualified before production use.

The integration invokes the official native binaries, preserving their normal
homes, transcripts and Shepherdr's per-launch hooks. It does not replace binaries,
change shell startup files, install a proxy or edit shared CLI configuration.

## Official contracts

- [Claude Code on Microsoft Foundry](https://code.claude.com/docs/en/microsoft-foundry):
  `CLAUDE_CODE_USE_FOUNDRY=1`, `ANTHROPIC_FOUNDRY_RESOURCE`, deployment mappings,
  and the native Azure SDK credential chain for Microsoft Entra ID.
- [Claude settings](https://code.claude.com/docs/en/settings): invocation settings
  compose routing environment and lifecycle hooks without overwriting user files.
- [Codex advanced configuration](https://developers.openai.com/codex/config-advanced/):
  per-run `-c` TOML overrides and custom model providers.
- [Microsoft's Codex Azure guide](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/codex):
  Azure OpenAI `/openai/v1`, `wire_api = "responses"`, deployment names and an
  `env_key` reference rather than a literal key in configuration.

Documentation was consulted on 4 November 2026. The intended target currently has
Claude Code 2.1.318 and Codex CLI 0.166.0. Source/type checks are not proof of native
provider execution on those versions.

## Authentication and routing

Claude uses Entra's native credential chain on the execution host. This version
clears inherited API keys and bearer tokens instead of copying them into settings.
Its resource and all default model aliases are pinned to the configured deployment.
No Azure login, permission grant or deployment creation is performed by the UI.

Codex requires the host's credential owner to supply `AZURE_OPENAI_API_KEY` to the
Shepherdr process. The value is forwarded only in the private core launch environment;
it is never put in UI settings, argv or the saved agent binding. Only HTTPS endpoints
under `*.openai.azure.com/openai/v1` are admitted. Other clouds/endpoints require
explicit support, not an arbitrary URL receiving the key.

Personal selects native Anthropic routing and the built-in OpenAI provider, clearing
inherited Azure routing variables. No automatic Azure-to-personal fallback is added.
Native account status still needs verification. Plan limits and personal CLI catalogue
probes are not Azure quota or deployment discovery and must not be used as proof of
Azure readiness.

A saved agent records its selected route and a nonsecret configuration fingerprint.
Changing route or deployment refuses reuse of that chat, including resume. Start a
separate conversation. Child launches cannot cross Personal/Azure routes. Missing
Azure configuration or Codex credentials refuses before mailbox allocation or terminal
creation. Local launch only: remote execution and Autopilot Azure launches currently
refuse rather than inheriting unrelated credentials.

## Verification and removal

`test/core-providers.test.ts` covers the settings projection, durable selected values,
native launch composition, hooks, credential omission, endpoint restrictions and
changed-route refusal. Run it in CI with the existing core settings/agents tests;
repository policy limits local verification to `bun run typecheck`. A protocol fake
is not a native-agent acceptance test.

Before production deployment, separately authorize an isolated preview and harmless
first turns for both CLIs. Verify actual provider, account, deployment, effort,
hook events and same-session resume. Neither a dropdown nor a launch record proves
those runtime identities. Keep the stock application and legacy workers running.

To revert an unused candidate, switch Provider to Personal or reset its override.
For an executed candidate, preserve conversations and stop only its identified
processes before returning to the previous build. Do not restart or change the live
stock installation as part of this feature's verification.
