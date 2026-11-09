# Native restart and revival (L2)

Source phase L2 of the [migration contract](migration/upstream-v3.1.3.md), on L1's launch owner
([launch admission](launch-admission.md)) and A2's recorded bindings ([Azure selectors](azure-selectors.md)).
This is source and authored regressions only. CI runs them; nothing here is installed, deployed or natively
qualified, and no agent was revived, restarted or signed in on a real machine to write it.

## What goes through the owner now

Every place an agent comes back goes through `mods/tasks/bin/herdr_task/launch_admission.py`, the one owner L1 made
for starts. Nothing types or starts an agent beside it.

| Where an agent comes back | Before L2 | Since L2 |
| --- | --- | --- |
| Revival after a crash, power loss or reboot (the tick, `T/revive.py`) | `hc send` with no claim; Personal only | Claimed in the journal, then `hc send`; on its recorded binding |
| A lost session at its shell, from the service (`service/watch.ts`) or the window's chat (`mods/chat/main.js`) | Each typed the new agent itself (a second loop beside revival); Personal only | `herdr-task launch revive TERMINAL --lost`: the same owner as revival |
| A lost session whose terminal ended (the same two) | `restart.sh`; Personal only | `restart.sh`, which the owner plans |
| Restart or Switch agent of an Assistant (window, web, `restart.sh`) | Personal only (`--replaced-route`) | `launch run --replaces TERMINAL`: the owner plans it |
| Restart or Switch agent of a task's agent (`herdr-task switch --restart`) | Personal only | Planned as resume and switch are |
| Fork (window and web) | Personal only (`providerRefusal`, `routeRefusal`) | `launch run --role agent --slot fork --replaces TERMINAL --argv FORK --check`: the owner admits or refuses it, then the window opens the tab |

## Which binding it comes back on

The rule A2 set for a task's resume, now at every site:

- **Continuing the same conversation** (a revival's resume, a restart whose argv resumes: Claude Code's `--resume`,
  `-r`, `--continue` or `-c`, Codex's `resume`): its recorded binding, rebuilt by the provider owner
  (`providers.plan_of_record`). Its deployment survives a changed default. Changed routing (route, resource or
  endpoint, sign-in) refuses with the reason, and so does a record this version can't read.
- **A new conversation** (a restart's handoff, another CLI): today's settings for the role, as a new start, but never
  on another route than the agent it replaces started on (`RESTART_ROUTE`): that would move its work to another
  provider without anyone choosing it.
- **Missing history** (its log is gone, or the CLI says the session isn't found), at revival or behind its chat
  (`restart.sh` with no handoff passes `--continues`): a new conversation with a handover, on the same recorded binding,
  since no one chose a new one, and recorded as missing history.
- **A fork** continues the conversation (Claude Code's `--resume ... --fork-session`, Codex's `fork`) as a tab agent:
  admitted on Personal; one recorded on Azure Foundry is refused by the owner (`TAB_BOUND`: tab agents start Personal
  only, A2's decision), and a Personal one under an Azure route now is refused as a resume would be.
- **No record of a binding** for an agent whose terminal says it started on Azure Foundry: refused or held with the
  reason (`NO_BINDING`). It is never read as Personal.

Where the binding comes from (`launch_admission.recorded_binding`), first found wins, and it must name the route the
terminal's `herdr.provider` label says:

1. A task's agent: its row on its task (A2 records it at every start).
2. An Assistant: the copy revival keeps on its terminal (`herdr.resume`'s `provider`), written while it runs, so it
   outlives the journal's 30 days.
3. Its start's journal record, found by its `herdr.launch` label.
4. Personal when its terminal names no other route.

A copy on a terminal label is only as trusted as the label: it is planned again against today's settings, and its
fingerprint must match, so it can't route anywhere the settings don't.

A restart (an Assistant's through `restart.sh`, a task's through `switch --restart`) that continues a recorded Azure
conversation and names a model other than its recorded deployment (or the one its own argv already named) refuses
(`RESTART_MODEL`) rather than silently keep the deployment. Effort, Fast and permission words stay as given (A2's
`compose`). Codex's own provider table, which a restart's argv carries from the running agent, is taken off and put back
once by `compose` (`without_table`); any other provider in the argv still refuses.

## Revival through the journal

- **Identity.** A revival is claimed under the agent's own launch identity (`agent_identity`): `task:<list>#<n>` (a
  reviewer's adds `/reviewer`) or `coordinator:local/<space>`. So a revival and any start of the same agent (a task's
  resume or switch, `restart.sh`) fence each other.
- **Order.** Preflight (the binding planned, the line composed), claim (`never-submitted`), then under the journal's
  lock the claim checked as its own and its revision unchanged, `submission-uncertain`, then `hc send` next. hc's
  success confirms it and lets the claim go. Its record carries `revival`: how (`resume` or `fresh`),
  `missing_history`, the session it resumed or the one that was lost, and its `provider`.
- **One sender per terminal process.** Under the journal's lock, just before it is recorded as sent, a revival
  refuses when another revival of the same `how` was already sent into the same terminal process (the tick and a
  lost-session recovery that both planned before either wrote its record): the first releases its claim on hc's
  success, so the journal itself, not the terminal's record, fences the second.
- **Uncertain.** hc failing or its reply lost may still have pasted the line. The start stays submission uncertain
  under its launch id, the terminal is marked handled, and nothing types it again: not the tick, not a lost-session
  recovery, not a task's resume. `herdr-task launch reconcile IDENTITY LAUNCH` confirms it once an agent runs in that
  terminal. No agent there keeps it uncertain.
- **Held.** An open start of the same agent holds the revival with the next step (`launch recover` for a
  never-submitted one, `launch reconcile` for an uncertain one). Not marked handled, so the next tick tries again
  once that is resolved. A binding that can't be carried is held once, with its reason, as before.
- **Its folder.** A Claude Code agent's own folder is read from its process while it runs (C1's rule) and recorded
  with a session found there, so a revival exports `CLAUDE_CONFIG_DIR` before the agent; a task's agent lost before
  any record takes its row's folder. A shell that isn't POSIX or fish can't be given a folder or a binding: held.
- **Its line.** Personal adds nothing to the line it typed before. On Azure Foundry the plan's variables precede the
  agent and, with a credential variable, the agent starts only when it is set (the same check `launch.provider_words`
  makes). Codex's provider table is taken off the recorded argv and put back in front of `resume` (`compose`).
- **What it never changes.** Revival writes no task list: state, holds, queue, dependencies, review, approval head,
  worktree and cleanup stay with their owners. A task's agent comes back only while its task is Working or Ready.

## Missing history, said apart

A revival or a lost session at its shell that starts a new conversation reports `how: fresh`,
`missing_history: true`, `session: null` and `previous_session`, in the tick's report, in `launch revive --json` and on
its journal record; one behind its chat (`restart.sh --continues`) records `missing_history: true` on its start. It is
never reported as a resumed session, and `launch revive`'s words say what was typed, not that the CLI resumed it. Its
first message says the earlier session is gone (as before).

## Commands

```sh
herdr-task launch revive [TERMINAL] [--lost] [--json]
herdr-task launch run ... [--replaces TERMINAL] [--argv JSON] ...
```

- `launch revive` with no terminal is the tick's pass (run outside the tick's lock it is fenced by the journal as
  above). With one, it acts on that terminal here; `--lost` says its CLI reported its session gone, which it checks on
  the terminal's own screen before typing anything. An agent running there, or one already brought back, types
  nothing (`how: none`); one held before is planned again, so the caller hears why. Another machine's terminal:
  `herdr-task --on MACHINE launch revive TERMINAL --lost` (the service and the chat do this).
- `launch run --replaces` names the terminal of the agent a restart (or a fork) replaces or continues; `--argv` is
  what it runs; `--continues` says it continues that agent (no handoff). On Azure, `restart.sh` gives the owner its own
  one-off template as `--new-start` and `--source`, and the owner runs its planned one-off in its place, as an
  Assistant's new start does; an argv word holding a newline is rebuilt by `printf` on the one-off's single command
  line, never split. `--replaced-route` is gone (it was only `restart.sh`'s).
- `restart.sh` reads templates from `HERDR_TASK_TEMPLATES` when set (the owner's own override), else herdr-core's
  folder as before.

## Held, not invented

- **Native receipts and revocation.** herdr-core gives no receipt, idempotency key or revocation for `hc send` or
  `hc run`. A revival hc doesn't confirm stays uncertain, and only an agent seen running in its terminal confirms it.
  Releasing one without that evidence is the inventory's held `manual-recovery` decision: no command does it.
- **One machine.** The journal fences this application's senders on this machine. An unknown process already
  running, or another machine's sender, is not fenced.
- **Automatic recovery.** Nothing reconciles or recovers by itself. A revival held by an uncertain start stays held
  until a person runs `launch reconcile`.
- **Fork's dispatch.** The owner admits a fork (`--check`: its plan, its refusals, an open start of the same slot),
  but the window's `tab.new` starts it in a new tab, not `hc run`, so the fork's own start isn't claimed in the
  journal. A fork admitted and then refused or lost by the window is not recorded anywhere.
- **Tab agents** start Personal only (A2's decision); their restart keeps that.
- **Remote Azure** stays refused (`NOT_EXECUTION_HOST`); a remote Assistant's binding is read from labels only.
- **Settings changed away and back** read as unchanged (content revisions, as in L1 and A2).
- **Real behaviour** of every route is unproven: a real CLI resuming a session on a rebuilt Foundry environment or
  Codex provider table, a real crash or reboot, the credential check (it runs after the terminal exists), and a
  revival's line in a person's own shell configuration.

## Conveniences retired: none

No convenience is retired (the grant's S3). Native revival, the chat's lost-session recovery, `restart.sh`, the
window's and the web's Restart and Switch agent and fork all stay, each now through the owner (fork's admission only,
above).
Retiring any of them needs that convenience's own native qualification first.

## Human choices still open

- Whether a revival held by an uncertain start may ever be released on other evidence (`manual-recovery`).
- Whether missing history should start a new conversation automatically (today's native behaviour, kept and now
  reported apart) or hold for a person, per case (`missing-history`).
- Whether reconcile may run by itself on positive evidence (automatic recovery).
- Whether a tab agent (and so a fork) may ever start on Azure, and whether a fork's own start should be journalled
  (it needs the window to start tabs through `hc run`).
- Reboot evidence, state carryover and rollback (R).

## Proof

Authored, not run locally (repository policy allows only `bun run typecheck`). CI runs them.

- `test/test_native_restart.py` (processes, a stateful `hc` stand-in, the journal, task list and terminal labels
  reopened as files): ordinary resume once through the journal with the task list untouched; missing history said
  apart; an unconfirmed send kept uncertain, holding later revivals and a task's resume, confirmed only by an agent
  running there; an open start holding a revival until recovered; a finished task's agent left a shell; its own folder
  carried; an Azure task agent on its recorded deployment with the credential check; changed routing held; Codex's
  table before `resume` with its effort and Fast; an Azure Assistant from its start's journal record and one with no
  record held; a second sender into the same terminal process fenced; `launch revive --lost` once whoever asks;
  `restart.sh` continuing an Azure Assistant on its recorded deployment, a lost session behind its chat on its
  recorded binding with a multi-line message kept one word, a model the recorded deployment would replace refused, and
  a new conversation refused on another route; a fork admitted on Personal and refused by the owner on Azure.
- `test/test_herdr_task.py` (`Revive`, in-process): the journal record, missing history, an unconfirmed send held.
- `test/test_providers.py`: `revive.plan` on its recorded binding or held; the settings read once; a model menu's
  restart on its recorded binding, a picked model it would replace refused, a new conversation never moved; a Codex
  restart carrying its own provider table once.
- `test/test_launch_admission.py`: `restart.sh` refusals in the owner's words; a start with no command line on Azure.
- `test/test_session_discovery.py`: a session under another folder recorded with its folder.
- `core/chat-find.test.js`: the service's lost-session recovery through `launch revive` and `restart.sh`, never typed
  by the service; the owner's refusal said; the web's fork asking the owner with its argv, its refusal making no tab;
  the window's recovery reaching the owner (source order).
- Not covered by any test: the window's restart, lost-session and fork paths run only inside the window (source-inspected),
  a real core restart, and the shell line in a real person's shell beyond `sh -n` parsing it.
