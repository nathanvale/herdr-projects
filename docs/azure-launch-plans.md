# Azure launch plans and deployment discovery (A1)

Source phase A1 of the [migration contract](migration/upstream-v3.1.3.md). It adds two native
owners and nothing else:

- `mods/tasks/bin/herdr_task/providers.py`: nonsecret provider bindings and launch plans.
- `service/azure-deployments.ts`: explicit, read-only deployment discovery.

This is source and its regressions only. CI's source checks run them; nothing here is deployed or
natively qualified, and no Azure launch is dispatched. The [2.x reference](azure-foundry.md) stays a
historical document.

## What works now, and what is held

Since A2 ([Azure selectors and bound starts](azure-selectors.md)) a valid plan is dispatched where its
start records it. This table says where each start stands now.

| Behavior | State |
| --- | --- |
| Personal (the default) | Unchanged. No provider setting, or `route: personal`, adds nothing to a launch. |
| `herdr-task provider plan` / `provider show` | Show the plan for one CLI, or what a selector shows. Read no credential, start nothing, run no `hc`. |
| A task's start, queue, the tick's queue, an automation's run, a backup | Planned on today's settings (the task's own choice wins for its CLI) and its binding recorded (A2). |
| Resume or switch of a recorded conversation | Planned from its recorded binding; changed routing refuses before any effect (A2). |
| An Assistant's new start (window chat, New space, first message) | Planned through `launch run --new-start` with an owner-written one-off template (A2). |
| Restart, Switch agent, fork, a lost session's new start, revival | Personal only (L2). Each refuses an Azure route or an Azure-started agent with its reason. |
| An unsupported or incomplete Azure plan | Refused before any worktree, task state or terminal effect. |
| Discovery | Settings' Refresh for both CLIs (A2), through the service. |

### A2 prerequisite: coordinator launch sites (met)

Assistant (coordinator) starts and restarts do not go through `herdr-task`'s task launch owner. They
start from `service/actions.ts`, `service/spaces.ts`, `service/agents.ts`, `mods/chat/main.js` and
`mods/coordinator/restart.sh`. A1 recorded that no Settings control may set an Azure route until each
of those refuses or plans through the provider owner.

L1 made all five start through `herdr-task launch run`. Since A2 its three new-start sites plan
through the provider owner (`--new-start`), and the restart sites (`restart.sh`, reached from the
window, `service/actions.ts`, `service/agents.ts` and `service/watch.ts`) admit Personal only. The
process proof is in `test/test_launch_admission.py` and `service/launch-sites.test.ts`; the chat
mod's own start is source-inspected only.

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

Any other field in the section refuses, so a key pasted into settings is not read as
configuration. The refusal lists the known fields and never repeats the unknown field's name or
value: either could be the pasted secret, and the reason is kept on a task or an automation. A value that is not text refuses too. This shape rule
holds on every route, Personal included, because settings are copied between machines. With no
`provider` section at all, nothing is checked and Personal is exactly as before. A half-filled
Azure setup under `route: personal` is fine: field values are checked only when a plan needs them.

`herdr-task` has no command that writes this section: provider connection stays a human Settings
control (Settings › Agents › Provider, since A2). A2 adds four role deployments
(`worker_claude_deployment`, `worker_codex_deployment`, `coordinator_claude_deployment`,
`coordinator_codex_deployment`), each following its CLI's deployment when left out or empty.

A copy that the settings window or the service pushed to another machine (marked `pushed_from`)
refuses an Azure route.
That is not a full local-only guard. Serve-from sync writes the host machine's file as its own,
without that mark, so the same route would read as local there. Since L1 every start records its execution machine, and an Assistant's
start on another machine (`hc run --on`) refuses any route but Personal, and a Serve-from client's
copy refuses Azure too: its herdr-core node record says another machine serves
([launch admission](launch-admission.md)).

## Supported combinations

Each row is the official contract for the inspected CLI version. No other combination is planned.

| CLI and sign-in | Plan | Credential |
| --- | --- | --- |
| Claude Code, Entra ID | `--settings` env: `CLAUDE_CODE_USE_FOUNDRY=1`, `ANTHROPIC_FOUNDRY_RESOURCE`, the three `ANTHROPIC_DEFAULT_*_MODEL` aliases and `--model` set to the deployment | None named. The Azure SDK default credential chain on the execution host. |
| Claude Code, API key | Same routing | `ANTHROPIC_FOUNDRY_API_KEY`, inherited. |
| Claude Code, bearer token | Same routing | `ANTHROPIC_FOUNDRY_AUTH_TOKEN`, inherited. The host owner renews it. |
| Codex, API key | `-c model_provider` and one reserved `model_providers.shepherdr_azure_<fingerprint>` table: `base_url`, `env_key`, `wire_api="responses"`, `requires_openai_auth=false`; `-m` set to the deployment | `AZURE_OPENAI_API_KEY`, inherited. |

Claude's plan also sets every competing route and inactive credential variable to an empty
string. The official statement is narrower than that use: Claude Code treats an empty settings
`env` value as unset for provider selection (the `CLAUDE_CODE_USE_*` names). That the endpoint,
credential and model variables read the same way is the 2.x planner's working assumption, not a
documented contract; native qualification (Q) has to prove it for each sign-in route. The active
credential's variable is left out of the plan entirely.

The plan's deployment is the argv's only model selection. The first selection the argv already
has keeps its place with the deployment as its value, every later one is removed, and with none
the flag is added after the program name. For Codex that covers `-m value`, `-mvalue`,
`-m=value`, `--model value` and `--model=value`; an attached `-m` form becomes two words. For
Claude Code it covers `--model value` and `--model=value`. A flag with no value of its own (it
is the last option, or the next word starts with `-`) takes the deployment, and the next word
stays where it is. Words from a bare `--` on are left as they are (for Claude Code, see the
refusal below).

Refused before any effect:

- Codex with Entra ID or a bearer token. Microsoft's guide says Entra ID is not available for Codex.
- An argv that names its own Codex provider: `--oss`, `--local-provider`, or a `model_provider`
  or `model_providers` override. The key is read as Codex 0.166.0 reads it (trimmed, up to the
  first `=`), in the `-c key=value`, `-ckey=value`, `-c=key=value`, `--config key=value` and
  `--config=key=value` forms.
- A Claude Code `--settings` file path, an attached `--settings=`, or more than one `--settings`.
- A Claude Code `--settings` with no value after it: the last word, or the last before a bare
  `--`.
- An inline `--settings` whose `env` names the plan's own credential variable. The refusal names
  the variable and never its value.

A bare `--` is read differently for each CLI:

- Codex: these checks and the model selection stop at the `--`. Words from it on are operands:
  one that looks like `--oss` or a `-c` override is neither refused nor parsed, and the plan's
  own `-c` and `-m` words go before the `--`. The reason is that clap treats `--` as a
  terminator. That was read from clap's main branch, not the version Codex 0.166.0 pins, so Q
  owns proving it.
- Claude Code: a `--settings`, `--settings=`, `--model` or `--model=` word from a bare `--` on
  refuses. The `--` may be another option's value (`--append-system-prompt -- --settings file`),
  and then that word is a real option that could override the plan's routing or carry a
  credential. Which way Claude Code's parser reads it is not confirmed, so the argv is refused
  under both readings and no word of it is repeated. Any other word after the `--` is left as
  it is and plans normally, with the plan's own `--settings` before the `--`. If the `--` is
  another option's value, such a word is a real option and passes unexamined, as any option
  before the `--` does, so the `--` opens nothing new.

A backup the provider holds is not spent. Its reason line says "backup held" and then the
refusal's own words, as far as the one line holds them.

The fingerprint is the SHA-256 of the CLI, endpoint or resource, deployment and sign-in method. It
uses the same expression as the 2.x planner, so equal configuration gives an equal fingerprint
and Codex provider name. It does not identify an account, and rotating a credential does not
change it.

## What can outrank a plan

A plan is what Shepherdr would add to a launch, never a claim of what will run. Three layers on the
execution host can outrank it, so `provider plan` lists them (`outranked_by` in `--json`), each with
its evidence and what is seen of it here. Since nothing dispatches on Azure, no start reports a plan
as running.

| Layer | Effect on a plan | Evidence | Seen here |
| --- | --- | --- | --- |
| A signed-in Claude apps gateway session | Authenticates with the gateway's token even when `CLAUDE_CODE_USE_FOUNDRY` is set | Official docs as reviewed for A1 (PR 17), Claude Code 2.1.318 installed then; not re-read in L1 | Unknown: not checked |
| Claude managed settings | Outrank `--settings`, its `env` included; `allowedProviders` can refuse a provider, and `--model` picks only from allowed models | Official docs as reviewed for A1 (PR 17), Claude Code 2.1.318 installed then; not re-read in L1 | Whether a file is at `/Library/Application Support/ClaudeCode/managed-settings.json` or `/etc/claude-code/managed-settings.json`; MDM and other managed sources are not checked, and the file is never read |
| Codex `required_model_provider()` | Resolves ahead of the other provider sources, the plan's `-c model_provider` included | Source inference: the Codex 0.166.0 tag read through summarised fetches. Microsoft's Codex guide validated only 0.152.1, 0.153.0 and 0.155.1 | Unknown: not checked |

Bare `--` parsing is not established by official docs for either CLI (see above). Native proof of
every layer stays with Q.

## Credential custody

`providers.py` never reads an environment value. A plan carries a variable's name only, so the
planner adds no value to argv, settings, labels, task records or output. An argv that carries the
plan's credential variable itself is refused (above); an inactive credential variable written
there is blanked. The planner does not scan a person's own argv for other secrets.

The environment-presence preflight from 2.x moved with the first Azure dispatch (A2): the agent's
own shell checks that the plan's credential variable is set and not empty before the CLI starts,
and names it when it isn't. That runs after the terminal exists, because herdr-task's environment
is not the terminal's. Presence does not prove sign-in.

### A pushed credential (MIG-13, opt-in, source only)

A machine whose terminals can't inherit the plan's credential can take it pushed instead, right
before the CLI starts. Why: every terminal gets herdr-core's environment, and herdr-core started long
before the credential existed. A value put in `terminal.run`'s `env` is kept in core's restart state,
so it is not a transport.

- **Opt-in:** Settings > Machines' `machine` layer, set by hand: `"credential_delivery": "push"`
  (Everywhere's, or a machine's own under `machines.<key>.machine`, which wins). Unset or any other
  value: nothing changes. No settings row shows it yet.
- **Applies to:** an Azure plan that names a credential variable: Claude `api-key` or
  `bearer-token`, Codex `api-key`. Personal and Claude Entra ID name none, so they never ask. The
  person's `claude_auth` choice decides the variable; push never changes the sign-in method.
- **In the agent's shell, before the presence check:** the inherited variable is unset, then
  `herdr-task launch receive NAME` runs in a command substitution. Its value is exported for the CLI.
  The existing check then runs unchanged. Nothing arrived means it stays unset, the check refuses
  with "needs NAME pushed …", and nothing starts. After the CLI ends, the kept shell unsets it.
  fish keeps it local to one `begin … end` block.
- **The request (nonsecret):** in a new `0700` folder `shepherdr-credential-<nonce>` in the
  receiver's temporary directory (`TMPDIR`, else `/tmp`), `request.json` (`0600`) holds
  `{version: 1, nonce, credential, terminal, pid, parent, start_ticks, uid, pipe_device, pipe_inode}`,
  beside `value.pipe` (a `0600` FIFO). Its path is said on stderr.
- **The push:** a 4-byte big-endian length, then that many UTF-8 bytes. It must be one value of at
  most 65536 bytes, with no NUL, CR or LF. This is the same framing as the Personal push prototype.
  Both files are removed before `receive` returns, whatever happened.
- **Bounds:** 300 seconds by default (`--wait`, 1 to 3600). An alarm also bounds a writer that
  stalls. `receive` refuses before creating anything for a name that isn't a plan credential
  variable, with no `HC_TERMINAL_ID`, or when stdout is a terminal. It never retries; a new start
  asks again.
- **Never carries the value:** argv, `hc` words, labels, settings, the journal, task records,
  one-off templates, typed revival lines and stdout/stderr messages hold the name only.

**What Shepherdr does not do (the adapter boundary).** A request is not authorization and grants
nothing. The deployment's credential custody, outside this repository and not part of this change,
must do all of this:

1. find the request;
2. verify it against the live process (`pid` and `start_ticks`, `uid`, the FIFO's device and inode,
   and the process being inside `terminal`'s process tree);
3. verify it against the terminal's own labels from herdr-core (`herdr.task`, `herdr.task.space` or
   `herdr.role`, `herdr.launch`, `herdr.agent`, `herdr.provider=azure-foundry`);
4. decide the approved task, process, account and binding;
5. obtain a fresh token on the host that holds the sign-in;
6. write the frame.

Shepherdr opens no vault, holds no credential and runs no broker or proxy. Until that adapter exists
and is qualified, turning the option on makes every Azure start on that machine wait and then refuse.

| Path | Covered by this change | Not covered |
| --- | --- | --- |
| Task start, new conversation or new-terminal resume (`launch.py`'s `in_shell`, POSIX, fish, other shells) | asks before the check | |
| Assistant new start and restart through its one-off template (`launch_admission.write_one_off`) | asks before the check | |
| Kept-shell revival (`revive.shell_line`, typed by the one revival owner) | asks before the check, unsets after | |
| A CLI already running | | never refreshed: a token that expires mid-session fails there. The next start, resume or revival receives a fresh one. |
| A tab agent or fork | | Personal only, unchanged |

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

- L2: native revive, watch and manual restart carrying a recorded binding (they refuse Azure now).
- Q: CI on the exact candidate, native qualification of each sign-in route, and public-process
  proof of the backup's gate beyond its in-module case.

Known limits of this slice:

- The `fable` alias is not pinned for Claude Code.
- Revive holds an agent whose start recorded Azure (its `herdr.provider` label) instead of retyping it (A2).
- Discovery assumes the service's computer is the local execution host. The `az` it runs is the
  one on the service's `PATH`; there is no setting or variable that chooses another.
- Since L1, one start is preflighted once and rechecked when it is claimed and when it is sent
  (launch_admission.py), not checked three separate ways.
- Model selection reads every argv word up to a bare `--`, without either CLI's option table.
  - A word that is really another option's value (`--append-system-prompt --model`, say) is read
    as a selection.
  - A flag given after a Codex subcommand (`codex exec -m value`) is read as a selection too, and
    rewritten in place.
  - With no selection, the flag is added right after the program name, so before any subcommand.
  - Not examined: an abbreviated long flag, and a `model` set by a Codex `-c` override or profile.
  - The Codex forms follow standard short-flag parsing and were not read from the Codex 0.166.0
    source; Q owns proving them.
  - An existing limit outside this slice: `agent_argv` appends `--no-daemon` to a Codex argv
    without it, at the argv's end, so after a bare `--` when there is one.

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
  Personal pass-through, refusal before effects for start, queue, resume, switch, the tick's
  queue and an automation's run, the four plans against written-out values, one model selection
  per argv, self-routing and inline-credential refusals, operands after a bare `--`, layering,
  and no credential value anywhere.
- The backup's gate is tested in the module only (`takeover()` with its launch replaced).
  Reaching it through `herdr-task tick` needs a live agent, its session log and a provider cut,
  which the recording `hc` does not model.
- `service/azure-deployments.test.ts`: the discovery class against a stand-in `az` process.
  Filters for both CLIs, subscription pinning, scope, memory-only state, stale responses,
  another machine's refresh during a local one, sanitized failures, bounds and timeout.
- `test/azure-binding.cases.json`: one field table both suites judge.
- `test/test_migration.py`: the source checkpoint (below).
- MIG-13, authored and not yet run (CI): `test/test_providers.py`. `PushedCredential` covers the
  composed words in a real `/bin/sh`, the real `launch receive` and a stand-in custody's frame: the
  push wins over a stale inherited value and is gone from the kept shell; a cut-short push and a
  timeout start nothing; refusals happen before anything is made. The opt-in rule and the words being
  byte-identical when off are tested in `Binding`. `herdr-task start` asking before the check is in
  `AzureStartsBound`. The Assistant's one-off template is in `test/test_launch_admission.py`, and
  kept-shell revival is in `test/test_native_restart.py`.

These stand-ins do not prove Azure sign-in, inference, a real launch or the real Azure CLI.

## Source checkpoint

`bin/check-migration` names the owner paths phase A1 may change and the manifest's
`source_deltas` pins each one's content hash and exact-U blob. The gate proves two things: every
U path outside that table and outside the three overrides is byte-identical to U with U's mode,
and each admitted path matches its pin (an admitted U path keeps exact U's mode, and an admitted
added path is a plain file). A symbolic link at an admitted path or at a U path outside the
overrides refuses, even to identical content. The three overrides (`AGENTS.md`, `docs/develop.md`,
`.github/workflows/check.yml`) are skipped whole, content and mode. They, the checker, the
manifest, and added files outside the table (docs, the checkpoint tests) are not pinned by it:
they rely on review. Candidate readiness stays blocked: `--require-ready` still exits 3. The mechanism is the one the
S1 branch introduced, so the two phases merge into one table; the hashes of paths both phases
change (`T/__init__.py`, `T/commands.py`) must be pinned again by whichever merges second.

## CLI design notes

Route: maintain and extend the existing native Python CLI, complex profile. `provider plan` is an
`inspect` command. It follows the host contract: `--json` prints one object, a refusal prints
`{"error": ...}` and exits 1, and without `--json` a refusal goes to stderr. Contract Core 2.0 envelopes,
typed exit classes, a station catalogue, `--discover` and LogTape are not adopted; those remain
separate, unapproved work and are recorded here as known gaps.

`launch receive` (MIG-13) has no `--json`. Its stdout is the received value for one shell's command
substitution, so it can't also carry an envelope. Every refusal goes to stderr, exits 1 and prints
nothing on stdout. Its stations are:

- refused before any effect: name, terminal, TTY stdout or `--wait`;
- received;
- not pushed in time;
- push malformed or cut short;
- stopped by an interrupt;
- couldn't wait.

Every station except "received" leaves no file behind and is never retried.
