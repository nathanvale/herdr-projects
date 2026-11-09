# Launch admission (L1)

Source phase L1 of the [migration contract](migration/upstream-v3.1.3.md). One owner,
`mods/tasks/bin/herdr_task/launch_admission.py`, admits every agent start on a machine and keeps a
durable journal of each one. This is source and its regressions only: CI runs them, nothing here is
deployed or natively qualified, and Azure dispatch stays held ([Azure launch plans](azure-launch-plans.md)).

## What goes through it

| Start | Entry point |
| --- | --- |
| A task's agent: start, the tick's queue, an automation's run, resume, switch, a backup | `herdr-task`'s own commands (`launch()` sends only through the owner) |
| A web-only New space's Assistant | `service/spaces.ts` runs `herdr-task launch run` |
| A space's first message with no Assistant yet | `service/actions.ts` runs `herdr-task launch run` |
| The window's Assistant chat (and a chat of another role) | `mods/chat/main.js` runs `herdr-task launch run` |
| Restart or Switch agent of an Assistant or a tab agent, and a lost session started anew behind its chat | `mods/coordinator/restart.sh` (from the window, `service/actions.ts`, `service/agents.ts` and `service/watch.ts`) runs `herdr-task launch run` |

`service/agents.ts` starts nothing itself: a task's agent goes through `herdr-task switch`, anything
else through `restart.sh`. Not agent starts, so not here: the scheduler's own terminal, the task
browser's view and Add machine's `hc machine add`. Revival (`revive.py`) types an agent back into
its own kept terminal, and `service/watch.ts` types a fresh start into a live one: neither is an
`hc run`, and both are L2's, outside this owner for now.

## The order of a start

1. **Preflight.** The settings file is read once and strictly. A file that is there but can't be
   read (not JSON, not an object, or not readable) refuses; a missing file keeps Personal. The
   provider owner admits the route: for a task's agent, Personal passes and Azure is held, as A1
   left it; for an Assistant or a tab agent, only Personal passes, here or on the machine an
   `hc run --on` names, because those sites can't carry a launch plan yet. A task's Assistant (its
   parent) is resolved. A start of the same identity that is still open refuses, naming the command
   that resolves it. Nothing has changed yet; `restart.sh` runs this step alone (`--check`) before
   it relabels the old Assistant's workers or saves its handoff.
2. **Claim.** The revision is taken again from a fresh read; if it changed, nothing is recorded.
   Otherwise the start is recorded as `never-submitted` with a new launch id, before its first
   effect (a task's state, a worktree, a terminal). A refusal, an error, Ctrl-C, SIGTERM or SIGHUP
   before it is sent cancels the start's own claim.
3. **Submit.** The task's Assistant must still be live. Then, in one step under the journal's lock,
   the claim must still be this start's own (a recovery revokes it) and the revision unchanged; the
   start is recorded `submission-uncertain`. `hc run` is the next thing done, carrying the label
   `herdr.launch=<launch id>`: no settings read, no other process and no wait in between.
4. **Confirm.** A reply naming the terminal records `confirmed`. A lost or failed reply gets one
   look for a terminal carrying its launch id. Exactly one confirms it; none keeps it uncertain, and
   the start refuses with its launch id (`--json` gives it as `launch`). Nothing retries it.
5. **Recorded.** A confirmed task start keeps its claim until its task list holds the agent. The
   next start of that task reads the list: the agent there releases the claim. Missing (its
   herdr-task ended before saving), that start refuses, so the agent never runs twice: the tick
   then puts the agent on the task and watches it, and any other command names
   `launch reconcile`, which puts it there for a person and starts its watcher.

A reconcile also restores what the start set up before sending: its worktree, branch, base, start
commit and mode. A backup whose start may have been sent is recorded as `uncertain` with its launch
id, never as failed, and the stuck agent is left as it is. The chat adopts an agent that shows up
late in its slot only when it carries this start's own launch id.

A task refused before its start is sent keeps its queue, hold and state, so a tick that saves it
never drops what was queued. Once sent, a tick keeps the task started whatever follows (it may be
running), so it never starts it again. A start, resume or switch command that fails after sending
saves nothing, and the journal's claim then keeps the task from starting until it is reconciled.
A reconcile doesn't redo what the command did after the start: a switch's or a backup's old agent
is not ended. A worktree the start made stays the task's.

## Whose settings, and which Claude Code folder

- **Settings owner (carried from A1).** Azure runs only where its settings were set. A pushed copy
  (`pushed_from`) refuses, as in A1. A Serve-from client's file, which `service/sync.ts` keeps in
  step with the serving machine and writes without that mark, refuses too: this machine's node
  record in herdr-core's documents (`shepherdr.node`, read from
  `${XDG_STATE_HOME:-~/.local/state}/herdr-core/default/docs.json`) says it doesn't serve. No
  documents, or no node record in them (no Shepherdr service here), read as its own; documents that
  can't be read, or a node record that is there but malformed (not a document, no value, no
  `serving` flag), refuse. Personal never reads them.
- **Claude Code folder (carried from C1).** A task's Claude Code start exports its folder
  (`CLAUDE_CONFIG_DIR`) inside the person's shell after its startup files, so they can't change it
  and a `claude()` function still runs, and records it on the start and its agent. After a
  previous Claude Code agent (switch, resume, a backup) the folder is that agent's recorded one;
  with none recorded (started before L1, or inherited) nothing is added, so it is never moved to
  the caller's profile. A first start uses this herdr-task's `CLAUDE_CONFIG_DIR`; a queued or
  scheduled one keeps the folder from when it was queued. What the scheduler starts by itself (an
  automation's run, a backup) never takes the scheduler's own folder: a backup keeps the stuck
  Claude Code agent's recorded one, and otherwise nothing is added. Unset,
  nothing is added and the terminal's own environment decides, as before L1. A value that isn't
  one absolute path (or is another folder called `.claude`) refuses. `restart.sh` reads the old
  Claude Code agent's folder from its process (`herdr-task launch folder PID`, C1's rule), looks
  for its log there instead of a fixed `~/.claude`, and carries it into a Claude Code agent it
  starts. Unreadable refuses before any change, unless the restart switches to another CLI.
  The export lasts in the person's shell that stays after the agent exits, so a `claude` typed
  there uses the same folder. A task start now carries no `CLAUDE_CONFIG_DIR=` word in its argv,
  so C1's lost-session refusal (which looks for that word) doesn't see these folders; a lost
  session's fresh restart from Chat reads the live shell instead, and on macOS, where a shell's
  environment can't be read, it starts on that shell's exported folder, the agent's own. The Assistant's other start sites start fresh and pass
  none. L2 owns the rest: native revive and resume reconstructing the folder (`T/revive.py`,
  `service/watch.ts`), and recording sessions found under it (`session_of()` still records only
  `~/.claude` ones, so a resume there starts with a handoff).

## Identities, revisions and the journal

- Identity: `task:<list>#<n>` (a reviewer's adds `/reviewer`), `coordinator:<machine>/<space>`, or
  `agent:<machine>/<space>/<tab>`. `<machine>` is `local` unless `hc run --on` names one.
- Revision: a digest of what the start was admitted on (route and plan fingerprint, the CLI or hc
  words it will run, its space and role), recomputed from settings. It is independent of the launch
  id, which is new for every attempt. It is content, not a counter: settings changed away and back
  to the same words read as unchanged, since the settings file keeps no counter. Unrelated settings
  edits never refuse a start.
- Journal: `~/.herdr/tasks/.launches.json` (with `HERDR_TASK_STORE`, that folder's), one per
  machine, under its own lock apart from any task list's. Each change is written whole, synced and
  renamed into place. A journal that can't be read refuses every start: it is never read as empty.
  Closed starts are kept 30 days; an open one is never dropped.

## Commands

```sh
herdr-task launch status [IDENTITY] [--json]
herdr-task launch reconcile IDENTITY LAUNCH [--json]
herdr-task launch recover IDENTITY LAUNCH [--json]
herdr-task launch folder PID [--json]
herdr-task launch run --role coordinator|agent --space SPACE [--slot TAB] [--config-dir DIR] [--check] [--json] -- <hc run words>
```

- `reconcile` confirms a `submission-uncertain` start only when exactly one terminal carries its
  launch id, and puts a task's agent on its task. An empty or failed lookup keeps it, since it
  doesn't prove the start never happened.
- `recover` releases only a `never-submitted` start (its herdr-task ended before sending): its claim
  is revoked, so if its sender is still running it sends nothing when it reaches submit. A
  `submission-uncertain` start refuses.
- `status` marks each start that is still unresolved as held and lists those first: never
  submitted, uncertain, confirmed but not on its task (it names the `reconcile` that records it;
  one its task list already holds isn't held), and a claim whose record is gone (shown as unknown).
- Each command points at the other when it is the one that helps: `recover` on a confirmed start
  its task doesn't hold names `reconcile`; `reconcile` on a claimed, never-submitted start names
  `recover`; a second `recover` says it was released earlier and releases nothing.
- `run --check` refuses what the run would refuse from its words (its own launch label, an
  `--on` machine name that isn't one word).
- hc's own reply is never repeated in a refusal or the journal (it could carry an argv word or an
  environment value): only "hc exited N".
- Nothing calls `recover` or `reconcile` by itself. No automatic recovery exists.

## Held, not invented

- herdr-core gives no receipt, idempotency key or revocation for an `hc run` it may have been sent.
  So nothing releases a `submission-uncertain` start without a terminal carrying its id, and its
  identity stays blocked: a definite hc failure (herdr-core down, an unreachable machine) never
  clears. Releasing one on any other evidence, a person's word included, is the held decision
  `manual-recovery` in the migration inventory: this version has no command for it, and only a
  later, separately approved change can add one. Every refusal says so.
- The journal fences this application's own senders, on this machine. It cannot stop an unknown
  process that already runs, and it does not reach another machine's journal.
- Content revisions don't detect settings changed away and back to the same words.
- An Assistant started on another machine (`--on`) is checked against this machine's settings only;
  that machine's own settings are not read.
- A space-less Assistant (a chat with no space) shares the identity `coordinator:local/unplaced`.

## Proof

`test/test_launch_admission.py` drives `herdr-task` and `restart.sh` as processes against a
stateful `hc` stand-in, reopening the journal and the task list as files: competing starts, a
shutdown and a crash before dispatch, a crash after it, lost and unconfirmed replies (start, tick
and resume), a delayed sender fenced after recovery, its Assistant changing, settings changed before
recording and before submission, unrelated edits, a refused tick start, and corrupt, unreadable and
missing settings. Switch, backup and automation starts share the same owner calls but have no
journal case of their own.
`service/launch-sites.test.ts` proves the service's two sites start through `herdr-task launch run`
and say a refusal: the first message's start refuses with the owner's words, and a web-only New
space keeps the space and reports the refusal to its caller (`/api/spaces` answers `assistantError`;
the page doesn't show it yet). A source gate in the Python file keeps the five sites from running `hc run`
for an agent themselves. The chat mod's start and the window's paths are source-inspected only.
None of this proves herdr-core's behaviour, a real host crash or reboot, or an agent's sign-in.
