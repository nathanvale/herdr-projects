# Azure selectors and bound starts (A2)

Source phase A2 of the [migration contract](migration/upstream-v3.1.3.md), built on A1's planner and
discovery ([Azure launch plans](azure-launch-plans.md)) and L1's launch owner
([launch admission](launch-admission.md)). This is source and authored regressions only. CI runs
them; nothing here is deployed, and no Azure, Foundry or Codex account was used. Native
qualification of every sign-in route stays with Q.

## What a person sees and does

| Where | What |
| --- | --- |
| Settings › Agents › Provider (window and web) | Personal or Azure Foundry at Everywhere or a space. On Azure: each CLI's resource or endpoint, deployment and sign-in, the discovery subscription, and the Assistant's and the workers' own deployments. |
| A deployment row | Type its name, or press Refresh and pick from what this machine's Azure CLI login finds. Refresh selects nothing. |
| A task's row menu, before it starts (web) | Model for its start: the CLI, and on Azure its deployment and effort (on Personal its effort). Save starts nothing and keeps its holds. Use configured defaults clears it. |
| A task's row menu, before it starts (window) | Model for its start… opens the model menu (settings mode): on Azure each CLI's deployments, on Personal its models. Each change is saved at once through `herdr-task select` with the revision it was shown at. |
| An Assistant's chat before its first message (window) | Its model menu lists each CLI's deployments on Azure. The pick, on either route, carries the revision of the routing it was made under. |
| A space's chat with no Assistant (web) | Its model line opens the model menu in new-start mode: Save for new start keeps a pick for the space (with its revision), Use configured defaults clears it. The first message's start carries it, then drops it. |
| `herdr-task select ID` | The same task choice from the command line. Without a change it only shows it. |
| `herdr-task provider show --role worker\|coordinator` | What a selector shows: the route, each CLI's routing, the deployment a new start takes, and the revision a pick is bound to. |

These are the person's own controls. `herdr-task` has no command that writes the `provider`
section, and an agent's instructions are not authority to change it.

## Settings

The `provider` section keeps A1's fields and adds four role deployments:
`worker_claude_deployment`, `worker_codex_deployment`, `coordinator_claude_deployment` and
`coordinator_codex_deployment`. A role's field left out or empty follows that CLI's deployment. A
task's reviewer and backup are workers.

- Inheritance is field by field, most specific first. A field left out follows the level above,
  `""` is the level's own empty value, and Reset removes it.
- Every save is checked the way `herdr-task` checks it (`core/settings.js providerValue`, judged
  by `test/azure-binding.cases.json` with `providers.py clean`). A refused value is never repeated.
- The window writes the file directly; the web goes through the service (`service/settings.ts`).
  Both refuse a value that can't be one before writing anything.

## Discovery

Refresh calls A1's `AzureDeployments` through the service, for one CLI at one level. The window asks
the service; without a running service it offers typed entry only.

- Results stay in memory for that level and CLI, under the configuration they were read with.
- Saving a resource, endpoint, subscription or route drops every list.
- A pick from a list carries that list's revision (when it was read). A pick from a list read
  under another configuration is refused, never saved. The window checks the same thing against
  the configuration its list was read under.
- Everywhere refreshes only with exactly one execution machine; a space uses its own machine.

## New-start selections

A task's choice is `agent`, `deployment` (Azure) or `model` (Personal) and `effort` on the task,
saved by `herdr-task select`:

- A save must quote the revision `select` showed. That revision covers the choice, a save counter,
  the task's recorded agents and each CLI's routing. A stale one refuses and changes nothing.
- A save changes only the choice. State, queue place, dependency, schedule and hold stay as they
  are, and no hc command runs. A queued task's plan takes the new argv in its old place.
- A task with a recorded agent, or one that has left To do, Queued or Scheduled, is locked. So is
  one whose start is still open in the journal. A stopped recorded conversation is not unstarted.
- A deployment choice records the routing it was made under (`selection_routing`). Under another
  routing (a different route, resource, endpoint or sign-in), its start refuses. It never falls
  back to Personal.
- Efforts on offer: a deployment whose model this CLI's own catalogue knows (by its id or the
  model the inventory reports) gets that model's levels; any other gets Default only. `herdr-task`
  checks an effort's shape; the selectors offer only those levels.

An Assistant chat's pick lives in the window, as before. On Azure its list is the deployments. A pick
the person made carries the revision `provider show` gave when the chat loaded, Personal too, so a
route changed before its start refuses it rather than reinterpreting it. The shown default (no pick)
is marked auto and isn't sent: the Assistant's own deployment decides. The web's pick for a space
whose Assistant hasn't started is kept by the service (`assistant.picks`, per space, with its
revision); the first message's start carries it as `--argv`, `--deployment` and `--revision`, and
drops it once used.

## Starts and resumes

| Start | Plan |
| --- | --- |
| A task's start, the tick's queue, an automation's run, a backup | Today's settings for the worker role (the task's own choice wins for its CLI). |
| Resume or switch of a recorded conversation (same CLI, known session) | Its recorded binding, rebuilt by the same planner. |
| Resume or switch with `--fresh`, or to another CLI | A new conversation with a handoff, on today's settings. |
| An Assistant's new start (window chat, New space, first message) | Today's settings for the Assistant's role, or the chat's pick. |
| Restart, Switch agent, fork, a lost session's new start, revival (L2) | Personal only: an agent that started on Azure, or a route at its space that isn't Personal (asked of `herdr-task provider show`; unreadable refuses), refuses with its reason. |

- Each Azure start records `{route, agent, target, deployment, auth, fingerprint}` on its agent
  (a task's) or its journal record (an Assistant's), and labels its terminal
  `herdr.provider=azure-foundry`. Personal records nothing new, so its words are unchanged.
- A resume plans from the record: the recorded deployment survives a changed default. The route,
  resource or endpoint and sign-in method must still be the recorded ones. Otherwise it refuses
  before any effect (switch never ends the old agent) and names `--fresh`. A record this version
  didn't write refuses too.
- Claude Code's Foundry environment is rebuilt into its `--settings` on every start and resume.
  `env_of()` only recreates the task's browser variable, so the plan is never left to it.
- Codex's provider table, `env_key` and `-m` deployment go before its `resume` subcommand. The
  argv's own effort, `service_tier` (Fast) and permission words stay where they were.
- A task's agent runs in the person's shell. There the plan's nonsecret variables are exported
  after startup files. With a credential variable, the CLI starts only when that variable is set
  and not empty; otherwise the shell names the variable and stays. This checks presence, not
  sign-in, and the terminal exists first.
- An Assistant's Azure start uses an owner-written one-off template: the source template's words,
  `CLEAN_ENV`, the same exports and check, then the planned argv. It replaces the site's template
  word, and is removed once hc has run. A template command that isn't one plain claude or codex
  command refuses on Azure. Personal starts keep the site's own words and template.

## Compatibility

- Output: `provider plan --json` gains `target` and `revision` (Personal too: `target` is null),
  `dispatch` is `planned` for an Azure plan (A1 said `held`), and `launch run --check --json` gains
  `route`. All additive; the words and exit codes of existing refusals are kept.
- Mixed versions: A1's and L1's herdr-task refuse a `provider` field they don't know, on every route.
  Once a role deployment is saved (and pushed to another machine), a machine still on an older
  herdr-task refuses its starts, Personal included, until it is updated or the field is removed.
- A tab agent (a chat of another role) starts Personal only, with its own reason.
- `herdr-task select` gains `--model` (Personal); `provider show --space` reads a space the settings
  file holds by its own folder, as launch admission does.
- Shared store: the web's Assistant picks live in the service's `assistant.picks` (nonsecret).

## Held, not invented

- Native behaviour of every route is unproven: the settings `env` blanking, Codex's root `-c`
  and `-m` before `resume`, and managed settings or a required provider outranking the plan.
- Restart, fork, a lost session's new start and revival refuse Azure-bound agents rather than
  carry the binding (L2).
- The credential check runs after the terminal exists. There is no presence check before effects,
  because herdr-task's environment is not the terminal's.
- Selection and settings revisions are content digests plus a task's save counter. Settings
  changed away and back read as unchanged, as in L1. A window chat's pick made under Personal
  carries no revision.
- Source-inspected only, with no test of their own: the window's Provider rows
  (`provider-section.js`), the window chat's Assistant pick and its fork's and lost session's route
  check, the window's task selector (`mods/tasks`, `mods/tasks-menu`), the web's `select.tsx`,
  `DeploymentValue` and new-start model menu (`restart.tsx`), and the service's `assistant-pick` and
  `model-menu` handlers in `service/main.ts`. Their owners' rules are tested through `herdr-task` and
  the service.
- A window chat's revision is the one read when the chat loaded its choices: settings changed after
  that refuse its pick until the chat is opened again.
- Inventory and an effort list don't prove account, inference, tool or effort support.

## Regressions

Authored, not run locally (repository policy allows only `bun run typecheck`, and this worktree has
no dependencies installed). CI runs them.

- `test/test_providers.py`: Azure task starts and their records, each sign-in's shell check, worker
  deployments, resume keeping the recorded deployment (Claude, and Codex's effort and Fast),
  changed routing refused before effects with `--fresh` after, Personal never moved, manual
  restart Personal only, automation and tick starts, `select` revision/save-only/lock/routing
  binding, a deployment refused on Personal, `provider show`, a backup on Azure, revival held under
  an Azure route or label, and the shell check run by a real `/bin/sh`.
- `test/test_launch_admission.py`: Personal new starts unchanged; an Azure new start's one-off
  template, label, record and removal for each Claude sign-in and for Codex; a remote one refused
  before any template is read; a chat's pick refused under changed routing; a template command
  that isn't plain; restart of an Azure-started Assistant refused.
- `service/settings.test.ts`: the shared field table, Provider rows at both levels, inheritance,
  empty values and Reset, and Refresh with a stand-in `az`: nothing asked until Refresh, nothing
  selected, a stale pick refused, typed entry, and Everywhere's one-machine rule.
- `service/selections.test.ts`: what the service asks herdr-task, revision carried on a save, each
  CLI's list and its effort levels.
- `service/launch-sites.test.ts`: the service's two Assistant sites send `--new-start`; a first
  message carries the web's saved pick with its revision, then drops it.
- `core/chat-find.test.js`: the service's lost-session recovery and fork ask `provider show` and
  refuse a route that isn't Personal (or can't be read), with nothing typed or made.
- `core/agents.test.js`: the shared refusals, the words that ask the route, and the Azure list.

## CLI design notes

Route: maintain and extend the native Python CLI, complex profile (settings, authority, ordered
effects). `select` and `provider show` are `inspect` without a change; `select` with a change is
`repository-local`. Both keep the host contract: `--json` prints one object, a refusal prints
`{"error": ...}` and exits 1, and without `--json` a refusal goes to stderr. Contract Core 2.0
envelopes, a station catalogue, `--discover` and LogTape are not adopted (unapproved; see A1).
