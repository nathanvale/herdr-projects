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
  `herdr-task launch receive NAME` runs in a command substitution. The receiver's exit status
  decides, not its text: `if NAME=$(…); then export NAME; else unset NAME; fi`. A receiver that
  printed something and then failed leaves it unset, `allexport` included. The existing check then
  runs unchanged. Nothing arrived means it stays unset, the check refuses with "needs NAME pushed …",
  and nothing starts. After the CLI ends, the kept shell unsets it.
- **POSIX shells only:** sh, bash, zsh, ksh and dash, plus an "other" shell, which runs the agent
  through `sh -c`. A fish shell with push on refuses before asking ("supported only in a POSIX
  shell"), so no request is made and the CLI doesn't start. Why: fish's `--debug` categories and
  `--profile` can't be shown to keep the value out. With push off, fish's words are unchanged.
- **Tracing:** `set -x` (from a startup file, or kept in the shell) would print `NAME=value` and the
  check expanded. So the shell's own tracing is off from before the receive until the value is unset
  again, then put back as it was. `set -v` shows only unexpanded words. Not covered: a person's own
  function or hook that prints the variable.
- **Reader first, then the request:**
  1. the receiver creates the FIFO;
  2. it opens the read end, non-blocking, which succeeds with no writer (fifo(7));
  3. only then does it write the request to `request.json.part` and rename it to `request.json`.

  A request that exists is therefore whole, and names a reader that is already open. It doesn't name
  one that will open later.
- **The request (nonsecret):** in a new `0700` folder `shepherdr-credential-<nonce>` in the
  receiver's temporary directory (`TMPDIR`, else `/tmp`), `request.json` (`0600`) holds
  `{version: 1, nonce, credential, terminal, pid, start_ticks, parent, parent_start_ticks, uid,
  pipe_device, pipe_inode}`, beside `value.pipe` (a `0600` FIFO). Its path is said on stderr.
- **The push:** a 4-byte big-endian length, then that many UTF-8 bytes. It must be one value of at
  most 65536 bytes, with no NUL, CR or LF. This is the same framing as the Personal push prototype.
  Both files are removed before `receive` returns: after a push, a refusal, the deadline, a writer
  that closes before a whole frame, an interrupt, SIGTERM or SIGHUP (the terminal closing). Those
  three signals only set one flag. Their handlers never raise, so nothing can interrupt the cleanup.
  A signal noted at any point, even after a whole frame, refuses. SIGKILL (or a crash of the interpreter) can't be caught: its folder,
  request and FIFO stay behind with no reader, and such a dead request must never be pushed to
  (custody checks 2 and 5 below).
- **Bounds:** 300 seconds by default (`--wait`, 1 to 3600). The receiver polls in steps of a
  quarter-second until the deadline, so a writer that stalls is bounded too. On Linux the poll
  reports nothing until a writer has opened; it doesn't report end-of-file before then. Another
  system that reports end-of-file early fails closed as a cut-short push. `receive` refuses before creating anything for a name that isn't a plan credential
  variable, with no `HC_TERMINAL_ID`, or when stdout is a terminal. It never retries; a new start
  asks again.
- **Never carries the value:** argv, `hc` words, labels, settings, the journal, task records,
  one-off templates, typed revival lines and stdout/stderr messages hold the name only.

### Native binding and trigger (MIG-13 binding unit)

With push on, Shepherdr gives credential custody what it needs to bind a request to one native start, without
exposing a task, prompt, setting or value:

- **Invocation record.** Before a pushed start, same-session revival or Assistant template start is dispatched,
  its launch-journal record gets `invocation`: sha256 of the exact argv of the program its receive runs in
  (`launch.invocation_digest`: NUL-separated, as `/proc/PID/cmdline` shows it). Push off, nothing is recorded and
  every word is as before.
- **`herdr-task launch binding TERMINAL --json`.** A read only: `hc get` and the journal file as last saved. The
  entry skips its layout migration for it, and it makes no lock file or folder. It gives
  `{version: 1, terminal, pid, launch, identity, space, state, kind ("start" or "revival"), how, session (a
  same-session revival's conversation id, else null), terminal_pid, address, provider, invocation}`.
  - **Which launch:** the newest one the journal records as sent (submission uncertain or confirmed) for the
    terminal. That is either its start (`herdr.launch`) or a revival recorded against its address. Admission records
    a revival under the journal's lock before `hc send` types it. So the revival is named before its receiver can
    run, whatever `herdr.resume` says yet. A cancelled or never-sent launch is never named.
  - **Refusal:** it refuses when that launch's binding no longer equals `recorded_binding`'s.
- **Direct revival.** A revival of an agent that started without the person's shell runs its child with `-c`
  and `command "$@"`, so a shell function, including an exported bash one, can't stand in for the agent. That
  exact program is the one recorded.
- **Waiting labels.** After publishing its request, the receiver labels its own terminal
  `herdr.credential=waiting` and `herdr.credential.request=<nonce>`, so custody can find it through herdr-core
  (`hc events --label herdr.credential=waiting`, `hc ls --label …`). If herdr-core doesn't take them, the receive
  refuses at once: no sender could find it. Cleanup clears them only while they still name its own nonce; a later
  receive in the same kept shell starts only after it ends. A label grants nothing.

Custody's recipient check then is exact: the receiver's parent hashes to `invocation`. For a start, that parent
is herdr-core's root pid for the terminal. For a revival, it is a direct child of that root, leading the
foreground.

Not covered: a same-uid process can write herdr-core labels and the journal too, so these records bind to native
owners but are not attestations. How herdr-core runs a template's command isn't pinned here.

**What Shepherdr does not do (the adapter boundary).** A request is not authorization and grants
nothing. The receiver checks only its own inputs. In particular, its stdout not being a terminal
does not prove that stdout is the intended shell's command substitution. The request's fields are
claims for the custody to verify, not evidence. The deployment's credential custody, outside this
repository and not part of this change, must do all of this, in order, before writing anything:

1. **Request files:** the folder, `request.json` and `value.pipe` are owned by the expected uid, with
   modes `0700`, `0600` and `0600`, not symbolic links. The folder name's nonce equals the request's
   `nonce`. The FIFO's device and inode equal `pipe_device` and `pipe_inode`. Hold an exclusive lock
   on `request.json` so only one pusher acts.
2. **The receiver is alive and is the receiver:**
   - `/proc/<pid>` exists with the same uid and `start_ticks`;
   - its command line is the installed `herdr-task` entry running `launch receive <credential>`;
   - one of its descriptors (`/proc/<pid>/fd/*`) is the FIFO with that device and inode, opened
     read-only (`/proc/<pid>/fdinfo`). That descriptor exists before the request does.

   A dead request (SIGKILL) fails here.
3. **The recipient is the agent's shell:**
   - the receiver's parent is `parent`, with `parent_start_ticks`;
   - the receiver's fd 1 is a pipe whose read end that parent holds (its command substitution);
   - the parent's ancestry reaches the pid of `terminal` from herdr-core's own `hc get`.
4. **The terminal is the approved start:**
   - herdr-core reports it live, with labels `herdr.provider=azure-foundry` and `herdr.agent`;
   - its task (`herdr.task` and `herdr.task.space`) or Assistant (`herdr.role`) and its `herdr.launch`
     match a launch-journal record that recorded this binding;
   - the custody's own policy approves that task, process, account and binding for `credential`.
5. **Push once:**
   - get a fresh token on the host that holds the sign-in;
   - re-run checks 1 to 3 under the lock;
   - open the FIFO's write end non-blocking (`ENXIO`: no reader, stop);
   - confirm its device and inode;
   - write the frame;
   - never retry a push whose outcome is uncertain.

These checks narrow, but do not remove, the window between checking a process and writing to it.
Owning that residual risk, and the token's account and lifetime, is the custody's decision.

Shepherdr opens no vault, holds no credential and runs no broker or proxy. Until that adapter exists
and is qualified, turning the option on makes every Azure start on that machine wait and then refuse.

| Path | The program the receive runs in (recorded as `invocation` before dispatch) | Not covered |
| --- | --- | --- |
| Task start, new conversation or new-terminal resume (`launch.py`'s `in_shell`) | `in_shell`'s argv, the terminal's root after the exec chain | |
| Same-session resume into a kept shell (`revive.revival_child`, typed by the one revival owner) | one child shell (`SHELL -ic SCRIPT SHELL argv…`, `-c` when it started without the person's shell) that receives, checks and resumes the recorded session | a revival with missing history (a new conversation) isn't a same-session resume |
| Assistant new start and restart (`launch_admission.write_one_off`) | the template's command execs `/bin/sh -c SCRIPT /bin/sh argv…` | the recipient is the terminal's root only if herdr-core runs a template's command as that process, which no pinned source shows |
| A CLI already running | | never refreshed: a token that expires mid-session fails there. The next start, resume or revival receives a fresh one. |
| A tab agent or fork | | Personal only, unchanged |
| An agent whose shell is fish, with push on | | refuses before asking; push isn't supported there |

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
  timeout start nothing; refusals happen before anything is made.
  - Its stand-in custody follows custody check 2 above: it opens its writer (non-blocking) only after
    finding the receiver's read-only descriptor on the FIFO.
  - `set -x` in `/bin/sh`, bash and zsh never shows the value and is put back afterwards.
  - SIGINT, SIGTERM and SIGHUP leave nothing behind.
  - A partial frame starts nothing.
  - A receiver that fails after printing starts nothing, even under `set -a`.
  - fish with push on refuses without asking. Off, its words are byte-identical to before.

  The opt-in rule and the words being byte-identical when off are tested in `Binding`. `herdr-task start` asking before the check is in
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
- push malformed, or its writer closed before a whole frame;
- stopped by an interrupt, SIGTERM or SIGHUP;
- couldn't wait.

Every station except "received" leaves no file behind and is never retried.
