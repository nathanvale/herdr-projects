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
| Restart or Switch agent of an Assistant or a tab agent | `mods/coordinator/restart.sh` (from the window, `service/actions.ts` and `service/agents.ts`) runs `herdr-task launch run` |

`service/agents.ts` starts nothing itself: a task's agent goes through `herdr-task switch`, anything
else through `restart.sh`. Not agent starts, so not here: the scheduler's own terminal, the task
browser's view and Add machine's `hc machine add`. Revival (`revive.py`) types an agent back into
its own kept terminal and is L2's: it does not go through this owner yet.

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

A task refused after its claim keeps its queue, hold and state, so a tick that saves it never drops
what was queued. A worktree the start made stays the task's.

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
herdr-task launch run --role coordinator|agent --space SPACE [--slot TAB] [--check] [--json] -- <hc run words>
```

- `reconcile` confirms a `submission-uncertain` start only when exactly one terminal carries its
  launch id. An empty or failed lookup keeps it, since it doesn't prove the start never happened.
- `recover` releases only a `never-submitted` start (its herdr-task ended before sending): its claim
  is revoked, so if its sender is still running it sends nothing when it reaches submit. A
  `submission-uncertain` start refuses.
- Nothing calls `recover` or `reconcile` by itself. No automatic recovery exists.

## Held, not invented

- herdr-core gives no receipt, idempotency key or revocation for an `hc run` it may have been sent.
  So nothing releases a `submission-uncertain` start without a terminal carrying its id. Releasing
  one on other evidence, or automatically, is a human decision this version does not make.
- The journal fences this application's own senders, on this machine. It cannot stop an unknown
  process that already runs, and it does not reach another machine's journal.
- Content revisions don't detect settings changed away and back to the same words.
- An Assistant started on another machine (`--on`) is checked against this machine's settings only;
  that machine's own settings are not read.
- A reconciled start is confirmed in the journal; a task's record of its agent is written only by
  the start that sent it.

## Proof

`test/test_launch_admission.py` drives `herdr-task` and `restart.sh` as processes against a
stateful `hc` stand-in, reopening the journal and the task list as files: competing starts, a
shutdown and a crash before dispatch, a crash after it, lost and unconfirmed replies, a delayed
sender fenced after recovery, its Assistant changing, settings changed before recording and before
submission, unrelated edits, a refused tick start, and corrupt, unreadable and missing settings.
`service/launch-sites.test.ts` proves the service's two sites start through `herdr-task launch run`
and show its refusal. A source gate in the Python file keeps the five sites from running `hc run`
for an agent themselves. The chat mod's start and the window's paths are source-inspected only.
None of this proves herdr-core's behaviour, a real host crash or reboot, or an agent's sign-in.
