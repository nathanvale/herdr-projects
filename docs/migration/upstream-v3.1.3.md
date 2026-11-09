# Full 3.x source migration

S0 is a source-only foundation; A1 adds provider launch plans and deployment discovery
owners on it, with Azure dispatch held, N1 adds native pull request adoption and
fail-closed publication, C1 finds a Claude Code session under its own agent's
folder, W1 keeps a web page's chat flag apart from background work, H1 adds an
opt-in private custom-domain listener, S1 routes pull requests through the forge
seam with GitHub as its first adapter, B1 reads a saved Bitbucket pull request and
its head's complete checks through a second, B2 publishes a Bitbucket folder's task on
Ready (a push on a frozen route, a draft, then ready for review) under durable claims, and L1
admits every task and Assistant start through one owner with a durable launch journal.
Required Azure and lifecycle ports are pending, and no Bitbucket or lifecycle port is qualified. This checkpoint is not deployable or ready for application use. Check's
`candidate-readiness` job intentionally refuses it even when native source checks
pass. Imported installer/service code is source input, not authority to run it.

## Inputs and source ownership

| Input | Exact commit |
| --- | --- |
| F, reserved fork parent | `4f0236f03a88c5e9fa344475d90d3a20ef418481` |
| U, upstream v3.1.16 parent (since its merge) | `57302497117183a1772464b31751da12a1c03e4a` |
| Upstream v3.1.3, S0's U (history) | `dc018f2a42f3a1d8562f7b23a3bcd3988f347bdc` |
| P, required Bitbucket contract source | `074dec5ea0bf0a057f520fa50497bf9e1b696ad9` |
| B, actual common ancestor | `de8e17957efb4aa016d7e4d652f397aaa95f0880` |

S0 merges U into private `integrate/upstream-v3.1.3` rooted at F. P is not a merge
parent. Its behavior is required regardless of the old-architecture PR decision.
Native runtime sources use exact U. Git's suggested relocation of old server
modules into `service/hc` was rejected; core transport is not their product owner.
The upstream README and existing version/release text are imported provenance,
not a newly authored landing-page design or a fork release.

[Behavior inventory](upstream-v3.1.3.json) binds the pending requirements.
[File dispositions](upstream-v3.1.3-files.json) enumerate every changed B..F and
F..P path, original hashes and static test declarations. Fixed Git objects retain
removed implementation and test bodies. Historical docs remain labelled references.
Deleting an old test file does not discharge its regression obligation.

## Source phases

`T/` means `mods/tasks/bin/herdr_task/`. New paths are proposed dependent-phase
owners, not implemented interfaces.

| Phase | Dependencies | Owner and exit |
| --- | --- | --- |
| S0 | This source admission | Exact U, F/P dispositions and blocked readiness; Root review and CI before dependent work. |
| N1 | S0, separately authorized | `T/github.py`, commands and CLI; adopt an existing pull request, fail closed on GitHub, separate gh and git failures. Not a port. |
| S1 | Reviewed S0 | New `T/forge.py`, existing `T/github.py`, commands/proof/worktree consumers; preserve GitHub defaults. Smallest next customization. |
| A1 | Reviewed S0 | New `T/providers.py` and `service/azure-deployments.ts`; nonsecret bindings, supported authentication and discovery custody. |
| C1 | S0, separately authorized | `core/chat-log.js` FIND and `T/sessions.py`; a Claude Code session is found under its own process's folder, for reading only, and nothing starts such an agent again. Not a port. |
| W1 | S0, separately authorized | `service/jobs.ts`; a chat a web page follows keeps its ask flag with background work off, and nothing else runs. Not a port. |
| H1 | S0, separately authorized | `service/private-domain.ts`, `service/auth.ts`, `service/main.ts`; an opt-in HTTPS listener for a domain you control, admitting Tailscale peers by owner. Not a port. |
| B1 | S1 | New `T/bitbucket.py`, `T/bitbucket_http.py`; qualified identity, host credentials and complete exact-head reads. |
| B2 | B1 | New `T/publications.py`, commands/output/CLI; durable claims, publication/readiness and current admission. |
| A2 | A1 | Shared settings/agents, desktop/web controls, `T/settings.py`, launch/resume; discovery, selectors and binding parity. |
| L1 | A1 | New `T/launch_admission.py`; one dispatch authority with durable uncertainty and sender fencing. |
| L2 | A2, L1 | Native revive/watch/manual restart through that owner; independent qualification and conditional retirement. |
| Q | B2, A2, L2 | Exact candidate CI/public process proof; all required ports and old proof obligations resolved. |
| R | Q, human state choices | Separately admitted rehearsal and matching executable/state rollback. |

### Upstream v3.1.16 merge

The local candidate `integrate/upstream-v3.1.16` starts at `83417614`, merges PRs 19 to
22 and the private HTTPS commits (H1), each with `--no-ff`, then merges upstream v3.1.16
(`57302497`, from the annotated tag `e6c52e6b`, which is unsigned) the way S0 merged
v3.1.3. No published commit is rebased. U now names v3.1.16: every U path outside the
phase table and the overrides is byte-identical to it, and each row's `upstream_blob` is
its v3.1.16 blob. The file names keep `v3.1.3`, as every reference names them; F, P and B
and the file dispositions don't change. The gate's checks are unchanged.

Where the two sides met:

- SHEP-59 (a squash-merged pull request is done, never a second one) goes through N1's
  `finish()`: the branch goes only at the head gh says merged (`headRefOid == tip`). Its
  bare base names are read as branches (`local_base()`, a `refs/heads/` fetch). A squash
  with no pull request to read keeps the branch and worktree, and its note says the work
  landed. `ready` takes SHEP-59's step after nothing-to-merge and before publishing.
- The tick now reads a running task's pull request too (SHEP-8, `2a3c5e13`); N1's adopted-head check
  stays for a Ready task, as a working agent's commits move the branch.
- SHEP-86's clean-environment start is on every start path C1 guards (launch, revive,
  `restart.sh`, the one-off templates); C1 only refuses before them.
  `mods/chat-models/core/agents.js`, a copy new in v3.1.16, carries C1's `core/agents.js`
  and is admitted under C1.
- SHEP-33 removed secret serving from the service's jobs; W1's flags-first start and its
  test follow that.
- H1's listener shares the service's handlers; the main listener takes SHEP-93's
  `idleTimeout: 180`, and the private listener keeps Bun's default (not changed here).
- Taken as they are and held before any activation: SHEP-33's automatic vault move,
  SHEP-78's feedback issues (on by default, filed to upstream's repository on a yes) and
  SHEP-79's star card. SHEP-26's lost-log search reads only the default `~/.claude`.
- Our `AGENTS.md` and `docs/develop.md` stay overrides.

### A1 provider checkpoint

`bin/check-migration` names each phase's admitted owner paths; the manifest's
`source_deltas` pins each one's content hash and exact-U blob. The gate proves two
things: every U path outside that table and outside the three overrides is
byte-identical to U with U's mode, and each admitted path matches its pin (an
admitted U path keeps exact U's mode; an admitted added path is a plain file). A
symbolic link at an admitted path or at a U path outside the overrides refuses, even
to identical content. The three overrides (`AGENTS.md`, `docs/develop.md`, `.github/workflows/check.yml`) are
skipped whole, content and mode. They, the checker, the manifest and the added files
the shared table names (below) are not pinned by content and rely on review. Since S1
(PR 19 decision D5, issue #7), a path outside that table refuses. Candidate readiness
stays blocked.

- `T/providers.py` owns nonsecret bindings, the four supported launch plans and the
  admission gate. Start, queue, resume, switch, backup, the tick's queue and an
  automation's run consult it. A valid Azure plan is held, not dispatched.
- `service/azure-deployments.ts` owns explicit read-only discovery. Nothing calls it yet.
- Hard A2 prerequisite: coordinator launch sites (`service/actions.ts`,
  `service/spaces.ts`, `service/agents.ts`, `mods/chat/main.js`,
  `mods/coordinator/restart.sh`) do not read the binding. No control, command or
  selector may set an Azure route until each refuses or plans through the provider owner.
- Carried to L1: binding the execution machine. A pushed settings copy refuses Azure,
  but a Serve-from host's file is its own. Done in L1: a Serve-from client's copy refuses
  Azure too (see the L1 checkpoint).
- Carried to Q: empty settings `env` values are documented as unset for provider
  selection only; the same treatment of endpoint, credential and model variables is unproved.
  The backup's gate has in-module proof only; its public-process proof is Q's.
- Detail, official sources and authored regressions: [Azure launch plans](../azure-launch-plans.md).

### N1 native publication checkpoint

`bin/check-migration` names each phase's admitted owner paths; the manifest's
`source_deltas` pins each one's content hash and exact-U blob. What it enforces: each
admitted owner matches its pin, and every U path outside that table and the three
overrides is byte-identical to U with U's mode. So a phase can't change a U path it
doesn't own, or an owner away from its pin. Naming an earlier phase over its deltas
refuses, and dropping the deltas as well refuses because the admitted paths then
differ from exact U. Under D5, a path a phase added outside the table relied on review
until S1 enumerated tracked paths in the shared table (issue #7); the checker also refuses
files under the retired `server/` and `helper/` owners and new files in `service/hc`.
Candidate readiness stays blocked.

- `T/github.py` owns adoption (`adopt_existing()`), reached by `herdr-task adopt`.
  Base equivalence is proved from commits: the task's start commit is the one merge
  base of its tip and the commit GitHub's base branch holds now, read through gh, and
  the recorded base (`main` when none is recorded) is in that commit. Adoption records
  the head it verified; Accept and the tick refuse unless the pull request's base is
  unchanged and its head and the branch here are both that head. Only adopting again
  records another. S1 moves this behind the forge.
- Finishing removes a task's branch and worktree only when the branch tip is the commit
  that merged (the head GitHub merged, or with no pull request a tip in the base
  branch) and nothing is uncommitted there; otherwise both stay with a note. A base
  that is only a commit refuses adoption and a local merge, and the base is fetched as
  a branch. A saved "not on GitHub" is asked again once before a local merge.
- Known gap: a retarget between Accept's read and `gh pr merge` isn't caught. The head
  stays guarded by `--match-head-commit`; gh offers no such guard for the base.
- A repo with no remotes, or only remotes on another named forge, stays local without
  asking gh. Otherwise only gh's own word that it knows no such host is a saved no, and
  a github.com remote or a name saved for the same remotes overrules it. Any other gh
  failure refuses and never reaches a local merge. gh not installed refuses for a
  recognised GitHub remote; whether that holds is an open human decision.
- Credential custody is unchanged: [Pull requests and credentials](../install.md#pull-requests-and-credentials).
- This phase, A1 and S1 each add one row to `PHASES` and their rows to `source_deltas`.
  They merge into one table, and whichever merges second re-pins every path they share.
- This fix is not a required port. No inventory requirement changes status.

### C1 chat profile checkpoint

`core/chat-log.js` (FIND, copied to `mods/chat/core/` by `bin/sync-shared`) and
`T/sessions.py` (`session_of()`) find an agent's Claude Code session, each by one rule,
for each candidate process and never for the caller:

- That process's `CLAUDE_CONFIG_DIR` set to an absolute path: exactly that folder.
- Its environment readable and the variable unset: `$HOME/.claude`.
- Unreadable, an empty environment, or a value that isn't an exact absolute path: nothing
  for that process, and no other folder is tried. macOS shows a system binary's environment
  as empty, so empty is no evidence.
- Metadata whose `pid` isn't that process's selects nothing. A session with no log stays
  pending under `~/.claude`. Nothing scans across folders.
- Under another folder a session with no log prints nothing, and FIND stops at that process,
  as pending has no path for a guard to read and would open a chat that could restart it. The cost: a fresh custom-folder
  agent shows "Can't find this conversation" until its first log line, as today. Both chats
  look again while they have no path, so it opens then.
- A reused pid isn't caught: a crashed agent's metadata names the same pid as a new process
  under that folder, so it can match until the new process rewrites the file. The `pid`
  check catches metadata for another pid and no other stale metadata.
- Only that one variable is taken from a process. Linux reads `/proc/<pid>/environ`; macOS
  reads `KERN_PROCARGS2` through python3, as `ps eww` is flat text. Any other platform
  finds nothing. Both read the environment the process started with.
- macOS reads live memory, and `argc` no longer marks where the environment starts once a
  process sets its title (Node's `process.title` rewrites argv). A short title zero-fills argv
  past itself, so with `argc` of 2 or more and every word after `argv[0]` empty the
  environment starts at the next word, and a Node agent reads as usual. A title that fills
  argv collapses it: the variable seen anywhere but in the counted environment refuses, and
  so does an empty count, so a set variable reads as unset only if a process overwrites its
  own environment memory. An argument shaped like the variable, with the variable unset,
  refuses too.
- Behaviour change: on macOS FIND now needs python3 on its PATH. Without it every Claude
  agent there loses Chat, including default ones that work today. `session_of()` runs in
  python already and doesn't.
- A session under another folder is for reading only. Revive and a fork carry no
  `CLAUDE_CONFIG_DIR` (since L1 a task's resume and `restart.sh` do), so continuing it there
  would start on another profile, perhaps another account. `session_of()` returns such a session only to `any_folder=True`, which
  `T/news.py` alone asks for, so for a non-default folder nothing records it and no path
  that starts an agent gains anything. A default agent whose environment can't be read
  does change: it gets no record, so a resume starts fresh. `sessionOf()` in `core/agents.js`
  gives a session under another folder no id. Carrying the folder belongs to L1 and L2. L1
  carries it into task starts and `restart.sh` (see the L1 checkpoint); revive, `service/watch.ts`
  and sessions recorded under another folder stay L2's.
- What would start an agent again asks its process, not a found log: FIND prints nothing for
  a custom-folder agent with no log, and a reader can be gone or have no path yet. `FOLDER`
  in `core/chat-log.js` runs on the agent's machine and prints `default`, `other` or nothing.
  The process with its own session is the agent; with none yet, another folder in the process
  or a child counts, and the process itself must be readable. It shares FIND's process
  reading, and FIND's arguments and output don't change.
- A running agent: `restartRefusal()` in `core/agents.js`, called by the window's picker, its
  task switch and `service/agents.ts` `restart()` before anything ends. Another folder and
  unreadable both refuse, each in its own words, so that also changes a default agent whose
  process can't be read: it no longer restarts. The live list lacks another machine's
  foreground program, so the service asks `hc get`. Codex isn't asked.
- A lost session: `lostRefusal()`, called by the window's `lostSession()` and
  `service/watch.ts`. The agent has gone, so it has no process to ask. Refused: a
  `CLAUDE_CONFIG_DIR=` word before the agent's in the launch's argv, which `freshArgv()` drops
  (any value, even `~/.claude` written out; since L1 a task start exports its folder inside its
  shell instead, so no such word is there and the shell keeps that folder); a live shell that reads another folder; in the
  window, a log it had found under another folder. Not refused, as the two rules conflict
  here and each departs from "unreadable refuses": a shell that can't be read, since macOS
  shows no environment for a system binary such as `/bin/zsh`, and what's typed inherits that
  shell as the agent that left did; and an ended terminal with no assignment, which leaves
  nothing to read, as refusing would end recovery for every default agent. So an ended agent
  whose variable arrived any other way can still start fresh on another folder. That a
  terminal gets the core's environment plus its caller's overrides is read from `hc`'s own
  description of its record, not proved here.
- A fork refused for another folder says so, in both the window and `service/actions.ts`.
- Still open: a tab's Restart and Switch agent (`tab-switch` in `service/actions.ts`) and
  `mods/coordinator/restart.sh`'s fixed `~/.claude` lookup don't ask.
- `sessionOf()` knows ~/.claude by its shape, as the agent's machine's home isn't known
  there, so FIND finds nothing for another folder called `.claude`, and so does `session_of()`.
- The macOS reader has no CI: `core/chat-find.test.js` and `test/test_session_discovery.py`
  take it only when run on macOS.
- This fix is not a required port. No inventory requirement changes status.

### W1 web chat flag checkpoint

Claude Code's question hook (`mods/chat/ask-hook.sh`) asks a chat only while
`data/chat-asks/open/<terminal>` is under 15 s old. On the web only `service/jobs.ts`
touched it, and only with background work on, so with `SHEPHERDR_JOBS=off`, or a 3.0
window keeping that work, a web page got no cards. W1 starts that flag's round before
the background work's gate. Nothing else moves.

- Background work keeps its gate: the task tick, `scheduler --ensure` and other machines'
  ticks run only as before. `/api/health`'s `jobs` is unchanged. (v3.1.16's SHEP-33 removed
  secret serving from the service's jobs.)
- The flag is kept only for a live Claude agent's chat that a page follows, as before.
  Another machine's agent keeps its flag there through `machine.exec`, the same one
  `touch` with background work on or off; the cards there are already read and answered
  through that link (`service/asks.ts`).
- While herdr-core is away, flags here are touched from its last list as before: they and
  the answers are files, so an outage doesn't affect them. Behaviour change, with background
  work on too: another machine's flag isn't touched then, where each touch used to wait and
  land once the core was back, perhaps for a terminal gone since; the first round after it's
  back sends one (at its usual 8 s spacing) instead of a queued touch landing at once, so an
  outage ending 12 to 15 s after the last touch now lets that flag go stale where it didn't
  before. An outage covering the round that would refresh it is enough, however short; one
  over about 12 s always is.
- Existing limitation, the same with background work on: a window closing an agent's chat
  on that agent's own machine (`close()` in `mods/chat/main.js`; a window showing another
  machine's agent leaves its flag alone) deletes the flag and empties every request waiting
  on that terminal, so a card about to be answered on a page goes to the terminal instead.
  The service makes the flag again for the next request: within 4 s for an agent on the
  service's machine, and for another machine's agent at its next remote touch, up to about
  12 s later with the 8 s spacing, plus the link's delay. While the window and
  a page show one chat, both can answer one request; the hook takes the first answer file
  it sees.
- With background work off and a window there, a request from an agent whose chat a page
  follows now waits for a chat's answer instead of going straight to the terminal, as it
  already did with background work on. The window's own flag code is unchanged.
- Untouched: `mods/chat/ask-hook.sh`, `service/asks.ts`, request identity, the answer
  path, `service/main.ts` and every permission restriction.
- `service/jobs-flags.test.ts` runs `service/jobs.ts` in a child process with stand-ins for
  herdr-task, herdr-secret and the hub. A real Claude, its hook and a real page are not run.
- This fix is not a required port. No inventory requirement changes status.

### H1 private custom-domain checkpoint

The private HTTPS commits (`f8c43a60` to `c8217c0b`, kept at
`refs/archive/private-https-c8217c0b`) were made on v3.1.3 and are what the live release runs.
H1 admits them unchanged: `service/private-domain.ts` and its test, the listener's
wiring in `service/auth.ts` and `service/main.ts`, `docs/private-domain.md`, ADR 0004,
`scripts/private-domain-proof.ts`, a line in `docs/web.md` and the workflow
`.github/workflows/private-domain.yml`.

- Set only through `SHEPHERDR_PRIVATE_DOMAIN` (a local JSON file outside synchronized
  settings). Unset, there is no listener and no extra lookup, and Tailscale Serve and
  local token access keep their defaults ([Private custom domains](../private-domain.md)).
- `docs/web.md` is W1's too: one row, under H1, pins its combined content.
- The workflow runs only on pushes to `feat/private-custom-domain` or by hand, so it
  doesn't run for this branch; its owner and sensitivity checks need a reviewer's look.
  `service/private-domain.test.ts` runs with the service suite in Check.
- This fix is not a required port. No inventory requirement changes status.

### S1 forge checkpoint

S1 is re-applied on this candidate after H1 as its own row in `PHASES`. Its owners are
`T/__init__.py`, `T/commands.py`, `T/forge.py`, `T/github.py`, `T/proof.py`, `T/tick.py`,
`test/test_forge.py`, `test/test_herdr_task.py` and `test/test_native_publication.py`;
those earlier phases admitted are S1's from here, and their pins are S1's.

- `T/forge.py` is the single route from Ready, review, Accept, merge, adopt, the tick and
  the Accept card to a task's pull request and its folder's repository. `T/github.py` is
  the GitHub adapter; its N1 functions keep their behaviour: Ready means published
  (any publication failure refuses Ready, with no "ready, but" state), D3 cleanup,
  adopted-head checks, the saved-no recheck (gh asked once per command) and fail-closed
  reads. Local Git, task state, approval and cleanup keep their owners.
- An unqualified saved record is GitHub's. The adapter still writes that legacy shape;
  no record is qualified on read or write.
- A saved record naming a provider without an adapter, or saved for a host other than
  the one herdr-task reaches GitHub at, is refused before any gh call. That host is
  where gh sends `--repo owner/name`: `GH_HOST`, else github.com. A gh configuration
  whose default is another host without `GH_HOST` isn't known before a call; there the
  answered-identity check below still refuses before any write.
- Publication reads a saved pull request first, before any push, comment or new pull
  request. No answer refuses, as N1 does, and an answer whose link, host, repository or
  number differs from the record refuses. Reads for Ready's SHEP-59 check, Accept,
  merge, the tick and the Accept card refuse the same way; nothing reads a refused view
  as merged, open or checked. A pull request from a list, open (adoption) or merged
  (SHEP-59's `pr_merged()`), counts only when its own link is in the folder's repository
  on that host; `adopt` refuses a link or answer on another host.
- The folder's host is gh's own: `gh repo view --json nameWithOwner,url` in the folder,
  the one lookup `github()` makes, gives the link on the host gh resolves from the remote,
  SSH aliases included. `forge.reach()` is the one owner of comparing it with the host
  `--repo owner/name` reaches: a different host, or none given, refuses with nothing
  changed and says to set `GH_HOST`. Publication calls it before any push; adopt, Accept's
  already-exists adoption, every merge (`merge_now()` from merge, Accept, Ready's and the
  tick's auto merge) and the tick's merged read (`squash_merged()`, which skips the task
  for that pass) call it before any call about a pull request. gh failing to place the
  folder at a merge reads as gh failing to reach the pull request, as N1 words it.
- Not covered: read-only presentation in `service/worktree.ts` and `mods/task-pr/main.js`,
  and GitHub news (`T/ghnews.py`), still read the saved `repo` (B1/B2). Host-qualified
  GitHub transport is not added.
- The tick's read of a recorded pull request (`facts()`) passes `reach()` for the
  folder's repository first, so a record saved before S1 (never checked) is held to it
  too. Otherwise nothing is read as the task's and nothing finishes: the record and the
  worktree stay, the next look comes after `PR_EVERY` as when gh doesn't answer, and
  the tick goes on.
- SHEP-59's completion read (`already_merged()`, from Ready and from the tick for a
  Ready task) makes its pull request queries, the saved one's view and the merged list,
  only once `reach()` passes for the folder's repository. Otherwise none is merged:
  nothing is recorded or raised, and local Git alone (`merged_here()`, `landed()`)
  says whether the work is in its base, as for a folder not on GitHub. Ready then
  reaches publication, which refuses on that host.
- Regression: `test/test_forge.py` runs `ready`, `merge` and `tick` as processes on the N1
  fixture. Existing assertions are unchanged; `test_herdr_task.py`'s patch points moved
  to the seam, and the merge fake answers only `gh pr merge`. Fixtures answer as gh does:
  merged-list links in the fixture repository, a pull request view naming itself, the
  folder's link on the host gh resolves, and `GH_HOST` set where an Enterprise remote
  publishes.
- The shared table (PR 19 decision D5's deferred enumeration, issue #7): every path a
  commit could hold, tracked or new and not ignored, must be U's, an admitted phase
  owner's (A1, N1, C1, W1, H1, S1) or an addition named in `NAMED` by the accepted change
  that added it: S0's foundation documents and checker, A1's `docs/azure-launch-plans.md`,
  and PR 20's checkout access (`.claude/.gitignore`, `.claude/checkout-access.json`,
  `bin/checkout-access`, `test/test_checkout_access.py`). Named additions are admitted by
  name only; their content relies on review. Any other path refuses by name, a document
  as much as source; ignored paths are no commit and pass.
- This is not a required port. No inventory requirement changes status.

### B1 Bitbucket reads checkpoint

B1 is its own row in `PHASES` after S1. Its owners are `T/__init__.py`, `T/bitbucket.py`,
`T/bitbucket_http.py`, `T/commands.py`, `T/forge.py`, `T/github.py`, `T/proof.py`, `T/tick.py`,
`mods/task-pr/main.js`, `service/worktree.ts` and `test/test_bitbucket.py`; those S1 admitted
are B1's from here, and their pins are B1's.

- What is read: a task's saved Bitbucket pull request, `{provider: "bitbucket", host:
  "bitbucket.org", repo, number, url}`, through `forge.pr_read()` like GitHub's. A legacy
  unqualified record stays GitHub's, and a folder's repository (`forge.repository()`) is still
  GitHub's or none: a Bitbucket-only folder still merges locally as N1 decided, and nothing
  writes a Bitbucket record yet. B2 makes Bitbucket folders publish and record one.
- Binding: the read goes from the task's own checkout. Its remote (`origin`, else its first)
  must name that same `workspace/repo` in every view git has of it: each configured `url` and
  `pushurl` line, which must be on bitbucket.org itself, and the fetch and push URLs git derives
  from them, which a rewrite (`url.*.insteadOf`) may take through an SSH alias of the same path. An
  HTTPS view must be bitbucket.org with no password, query or port other than 443. Otherwise nothing
  is sent, and the view is refused. The pull request read must then be from the task's branch into
  its base (none recorded is `main`): another source or destination is a refused view, so nothing
  finishes on it and no card counts its checks.
- Credential custody: the execution host's own Git credential helper, through `git credential
  fill` in the checkout, with prompts off (`GIT_TERMINAL_PROMPT=0`, a failing askpass,
  `GCM_INTERACTIVE=never`) and a 5 s bound. The request carries `protocol=https`,
  `host=bitbucket.org`, the HTTPS path (else `<repo>.git`) and only a username written in an
  HTTPS URL; git's own configuration decides whether the path takes part (`credential.useHttpPath`).
  Only an ordinary username and password answer counts, and its password is sent as the Bearer
  token, so the helper must hold a REST-capable Bitbucket API or access token there: herdr-task
  can't tell a token from any other password. It refuses before any request a missing answer, a
  password that isn't 1 to 8192 printable ASCII characters, a username other than one written in
  the URL, any `authtype`/`credential` answer that reaches it (git itself drops those for a caller
  that didn't ask for them), and a remote that changed since it was bound. Bitbucket refuses
  anything else that isn't a token it accepts (`permission-refused`). No other account, store,
  setting or Basic fallback. herdr-task never approves, rejects or stores a credential.
- Remote and contained execution: Bitbucket is reached only by herdr-task itself, on the machine
  holding the checkout (`herdr-task --on <machine>` runs it there, with that machine's helper).
  Native 3.x has no contained-repository owner, so nothing here claims one. The service's and the
  window's Pull request views (`service/worktree.ts`, `mods/task-pr/main.js`) ask gh, so for any
  record not GitHub's they now say why there is nothing to show there, without a call, instead of
  reading its name as GitHub's. This is source-inspected: no test runs those two views, and their
  sentence is a copy in each rather than in `core/worktree.js`'s `VIEW_WORDS`, which B1 doesn't own.
- Transport (`T/bitbucket_http.py`): fixed GETs under
  `https://api.bitbucket.org/2.0/repositories/<repo>`: the repository (`full_name` and its link),
  the pull request (this repository's own source and destination, its number and link), the
  commit its (often abbreviated) head resolves to, that full commit's statuses page by page, and
  the pull request again. A head, branch or state that moved meanwhile refuses. Pagination
  stays in the same collection on that origin; a foreign, repeated or out-of-collection link,
  a redirect, a disagreeing `size`, 20 pages, 1000 rows, 1 MiB per body, a timeout (8 s per socket
  wait, with the body's reads also held to 8 s of wall clock) and a 45 s budget checked before each
  request each make the read incomplete. Connecting, the tunnel and TLS have only the socket timeout. TLS uses the system's default verification; proxies
  from the environment are honoured as urllib does.
- Outcomes kept apart: no complete read is no view at all, and `show --evidence` (the Accept
  card) says why in `checks.result`: `missing` (no such pull request, or one the token can't
  see), `refused` (nothing sent), or a transport category (`missing-credentials`,
  `permission-refused`, `rate-limited`, `malformed-response`, `incomplete-read`,
  `identity-changed`, `unavailable`). A complete read is `empty`, `pending`, `failed`
  (`FAILED` or `STOPPED`) or `passed`, with `checks.head` the full commit; checks for a head other
  than the branch here are `other-head`. The card's `state` keeps its existing five values. For
  the tick and Accept, failed checks and a declined pull request are problems in GitHub's words,
  and running or no checks are pending: empty is never green.
- Merge refusal: Accept (also while checks run, so no `auto_merge` is set), merge and the tick's auto
  merge send Bitbucket nothing that merges and merge no other way (no GitHub, local or agent route);
  the refusal stays on the task for the person. A failed read's repair names a credential only when
  that is what failed; `--json` carries no `cause` for Bitbucket (`cause` stays gh's and git's).
- `adopt` on a task that already records a Bitbucket pull request refuses before any call.
  A pull request merged on Bitbucket by hand finishes its task through the tick or Accept, with
  `merged_head` taken from that very read, so the branch goes only at that head (`finish()`
  never asks gh about another forge's record). GitHub news and the base watch stay GitHub's.
- Ready with a saved Bitbucket record refuses first, before any read, fetch, push or finish
  (`forge.publication()` at the top of `cmd_ready`), and the task stays as it was.
- Regression: `test/test_bitbucket.py` runs `show --evidence`, `tick`, `accept`, `merge` and
  `ready` as processes on the N1 fixture with its remote on bitbucket.org. Bitbucket is a
  test-owned answerer behind a local CONNECT proxy that opens only `api.bitbucket.org:443`, with a
  certificate from a throwaway CA (`SSL_CERT_FILE`); the credential is a recording helper in the
  repository's config, with global and system config emptied. No real provider request is made
  or possible, and the shipped transport has no test seam. It needs `openssl` on CI.
- Not covered: Bitbucket's real answers (abbreviated hashes, the commit's `repository` field and
  status fields are read as its documentation shows them), a real helper or account, and both
  execution hosts, all native qualification. Merged-list reads (SHEP-59 for a Bitbucket branch
  with no record), adoption, publication, readiness and claims are B2's. Python checks and the
  regression are authored here and run only in Root's CI.
- This is not a required port's completion: `bitbucket-credentials`, `bitbucket-reads` and
  `forge-identity` stay pending until Root CI and native qualification.

### B2 Bitbucket publication checkpoint

B2 is its own row in `PHASES` after B1. Its owners are `T/__init__.py`, `T/bitbucket.py`,
`T/bitbucket_http.py`, `T/cli.py`, `T/commands.py`, `T/forge.py`, `T/publications.py`,
`test/test_bitbucket.py`, `test/test_bitbucket_publication.py` and `test/test_native_publication.py`;
those earlier phases admitted are B2's from here, and their pins are B2's.

- Which folders publish: Ready asks `forge.publishing_repository()`, GitHub's first, unchanged, else
  the Bitbucket repository the folder's remote (origin, else its first) binds when that remote is
  written on bitbucket.org. One written there whose views don't bind one repository refuses with
  nothing pushed or sent. Reads (`forge.repository()`), the tick, Accept's adoption and GitHub's
  folders are unchanged. Behaviour change: such a folder no longer merges here. Accept and merge
  refuse a local or agent merge there (`bitbucket.no_local_merge()`), and
  N1's "another forge stays local" tests now use GitLab remotes.
- Ready on Bitbucket (`T/publications.py`, `publish()`), each step only after the one before it:
  1. Zero-effect preflight: branch names Bitbucket's query and git take, the branch here at the commit
     ready was run at, every remote view binding the folder's repository, and one frozen push route:
     the single push URL git derives, which no `insteadOf`/`pushInsteadOf` rule rewrites again when
     pushed to as written. Then this host's claim (below), then one credential ask and reads: the
     repository, the base branch on Bitbucket, the task branch there and every open pull request from
     it, each read in full.
  2. An uncertain step from before is reconciled now, before anything else is sent (below).
  3. Refused with nothing sent: two pull requests open from the branch, one into another base (no
     second pull request), one whose description carries another operation's id, or this task's own
     not open from the branch into its base now.
  4. Branch ownership, read-only, from the branch as git reads it on the frozen route (`ls-remote`, the
     view the push's expectation is checked against): a branch that exists where this host never pushed
     it (no recorded push of its own) refuses, never pushed over and with no pull request opened; one
     moved since this host's own last push, or removed since, refuses too.
     The push, unless Bitbucket's branch holds the commit already: one atomic ref update on the
     server, `git push --porcelain --force-with-lease=refs/heads/<branch>:<expect>` to the frozen URL,
     prompts off. The first push is create-if-absent (`<expect>` empty: the ref must not exist), so
     exactly one push ever creates the branch; later ones expect this host's own last push (as P leases
     on its own pushed head). Its operation id, commit and expectation are saved in the claim before
     git runs. git's own line for the ref decides: moved (done); `[rejected]`, `[remote rejected]` with
     the branch now holding something else, or already there when it had to be absent (lost: another
     push got there first, refused); `[remote rejected]` with the branch as expected (declined: a branch
     permission or hook, refused as that); a remote failure or no line (`uncertain`, kept). An uncertain
     push is settled from git's view of the branch next time: as its expectation, it didn't land and may
     go again; at its commit as an update of this host's branch, it landed; at its commit as the first
     push, held, as another host's push of the same commit looks the same. A confirmed push is saved in the
     claim at once.
  5. The draft: the task's saved record (only reached once this host's own push owns the branch, so a
     task whose claims file is lost, or whose folder moved to another host, can't publish its pull
     request again), or one opened by hand at exactly that head carrying no
     operation id (adopted, as GitHub's SHEP-13), or a new one: `POST` with `draft: true`,
     `close_source_branch: false`, the source branch at exactly that commit, the title
     `<ref> <title>` and the brief as description, ending with `Herdr-Operation: <uuid>`.
  6. Ready for review: the pull request read again with its head's complete checks (B1's read; any
     result, empty included, as P), at exactly the pushed commit; then read once more and `PUT` with
     `draft: false`, the summary (and details) as description with its own operation line, and the
     title, reviewers, destination and `close_source_branch` exactly as that read gave them. The answer
     must give the same back.
- Revalidation: the remote's views are read again as the last check before the push and before each
  write (`Reader.still()`), and the branch here and Bitbucket's head are checked before each.
- Claims: `STORE/.publications.json`, under its own `flock`, written to a temporary file, synced and
  renamed (and its folder synced) before what it covers is sent. One claim per repository branch, with
  its owner (task key, folder, checkout, machine name), its route and three stages: `pushed`, `draft`
  and `ready`, each with an operation UUID and `uncertain` or `confirmed`. A claim another task, folder
  or machine holds refuses before anything is sent; a done or removed task's claim in the same folder
  passes on only when nothing in it is uncertain. A claim taken for a command that then changed nothing
  is let go. The task's own record is saved only when Ready completes; the claim keeps what happened
  whatever fails later, and a later Ready takes its record from there.
- Writes and uncertainty (`bitbucket_http.send()`): sent once. 401 or 403 is `write-refused`: nothing
  happened, and the stage is cleared. A budget too short for the request is `not-sent`, before any
  byte. Anything else short of the exact, complete answer (a timeout, a dropped connection, another
  status, an answer that doesn't read or doesn't match) is `uncertain-write`. Then one look follows, for
  positive evidence only. Without it the stage stays uncertain: Ready then sends nothing that changes
  anything (no push, no second pull request, no preparation) until Bitbucket shows exactly one open
  pull request from the branch into its base, at the head that step was sent for, whose description
  carries that same id (for ready, also no longer a draft); another open beside it is refused right
  after, with that one confirmed. That confirms it under the same id. An
  empty or failed lookup or a changed remote keeps it uncertain. Nothing releases it automatically; the
  refusal names the id and the line, so the person can open or mark it on Bitbucket by hand.
- Output: a Ready refused in publication's own steps gives `--json` `publication` (a remote on
  bitbucket.org that doesn't bind refuses before them, with `error` alone): `result` is `refused` (nothing changed on
  Bitbucket in that command), `changed` (with `changed`: `pushed`, `draft`, each confirmed),
  `uncertain` (a write it sent may have happened) or `held` (an earlier one still is uncertain),
  with the claim's facts; the text names what was done before it stopped. `show` (and
  `show --evidence`) carries the same facts as `publication` (or `unreadable` with why), and one text
  line. Ready on a pull request herdr-task never merges says so, whatever the merge setting, and sets
  no auto merge.
- Concurrency, as it actually is: exclusion holds per Bitbucket repository and task branch, through
  the server's ref transaction. herdr-task keeps no shared store between machines (each host has its
  own claims file), so two execution hosts publishing the same task both may read the branch as
  absent, but only one create-if-absent push can create it. Only the branch's owner opens, adopts or
  prepares its pull request, so exactly one opens; the other refuses saying another push created the
  branch first, holding no claim. Within one host the claims file's lock also refuses a second task,
  folder or command before anything is sent. A third party pushing the branch first (someone's own
  push, before Ready) blocks publication until the person removes or renames it. This relies on git's
  receive-pack checking each update's old id, not on Bitbucket refusing a second pull request, and no
  shared store, service or core document is used. A fork's branch of the same name is another branch
  and is left out of the open pull requests read.
- Merge: B1's refusal is unchanged for every published record. Nothing sends a Bitbucket merge or
  merges another way.
- Regression: `test/test_bitbucket_publication.py` runs `ready`, `show`, `accept` and `merge` as
  processes. Bitbucket is B1's test-owned API, answered by a model of one repository whose branches
  are a bare repository's, reached by git through the remote's rewrite to an SSH alias and a test SSH
  transport. It covers the happy path with fields people set kept, lost replies found at once and on
  reopening (no second `POST`, same id), an empty lookup that never releases, an uncertain preparation,
  a refused write that keeps its push, zero-effect refusals, a branch this host never pushed never
  pushed over, its own last push the only one rewritten, a push git doesn't answer for, two simulated
  hosts publishing the same task (one branch creation, one pull request, the other refused: after the
  first, and racing with the same or another commit, where the second's push waits in the server's
  `pre-receive` hook while the first's whole ready runs, so the server's own ref update refuses it), a
  push the server declines, merge settings that promise nothing, a fork's branch
  left out, a remote changed before the push and before the write, a push URL git would rewrite,
  claims of another task or machine, and an unreadable claims file.
- Not covered: Bitbucket's real answers (the list query's `q`, a `/` in `refs/branches/<name>`
  sent as `%2F`, draft and reviewer fields, the 255-character title bound and the 32000-character
  description bound are as P and its documentation give them), Bitbucket's own git server applying
  `--force-with-lease` as git's receive-pack does, a real helper, account and push, two real hosts,
  and a delayed write landing after its reconciliation. All are native qualification.
  Python checks and the regression are authored here and run only in Root's CI.
- Not a required port's completion: every `bitbucket-*` requirement, `public-cli-outcomes` and the
  B2 part of `request-replay` stay pending until Root CI and native qualification.

### L1 launch admission checkpoint

`T/launch_admission.py` is the one owner every agent start on a machine goes through: a task's
agent from each `herdr-task` start path, and an Assistant's or a tab agent's from its five start
sites (`service/spaces.ts`, `service/actions.ts`, `mods/chat/main.js`, `mods/coordinator/restart.sh`,
and `service/agents.ts` through `restart.sh` or `herdr-task switch`), which now run
`herdr-task launch run`. Detail: [launch admission](../launch-admission.md).

- Owner moved to L1 in the repair pass: `service/main.ts` (H1's until then). `/api/spaces` must
  answer a web-only New space's refused Assistant start (`assistantError`), as the approved repair
  item asked; no other line of it changed, and its H1 listener wiring is untouched.

- Preflight before any effect: the settings file read strictly (there but unreadable refuses,
  missing keeps Personal), the provider route (a task's Azure plan stays held; an Assistant admits
  Personal only, here or on another machine), the task's Assistant, and an open start of the same
  identity.
- A durable journal (`~/.herdr/tasks/.launches.json`): `never-submitted` before the first effect,
  `submission-uncertain` in one locked step that rechecks the claim and the revision, then `hc run`
  next, then `confirmed` from the reply or from exactly one terminal labelled with its launch id.
  Revisions are content digests, independent of the launch id.
- Fencing: `launch recover` revokes only a never-submitted claim, and a delayed sender then sends
  nothing. A submission-uncertain start is never released or retried; `launch reconcile` confirms
  it on positive evidence only and puts a task's agent on its task. Releasing one without that
  evidence is the held `manual-recovery` decision: no command does it, and only a later, separately
  approved change can.
- Carried from A1 and done here in source: Claude Code `--settings` followed by another flag
  refuses with the missing-value message; `provider plan` names the layers that can outrank a plan,
  with each one's evidence; a corrupt or unreadable settings file refuses a start and a plan (P17-7).
- Carried to L1 and done here in source: a Serve-from client's settings copy refuses Azure (its
  herdr-core node record says another machine serves; unreadable refuses), and a task's Claude Code
  start carries its `CLAUDE_CONFIG_DIR` folder explicitly (the previous agent's for switch, resume
  and backup) and records it; `restart.sh` reads the old agent's folder, finds its log there and
  carries it, closing C1's open fixed `~/.claude` lookup. L2 keeps native revive and resume
  reconstructing the folder, and sessions recorded under it.
- A confirmed task start holds its claim until its task list records the agent, so a herdr-task
  that ends before saving never leaves a task to start twice.
- Held, not invented: herdr-core gives no receipt or revocation for a sent `hc run`; the journal
  fences only this application's senders on one machine; no automatic recovery is chosen; revival
  that types into a kept or live terminal (`T/revive.py`, `service/watch.ts`'s live case) does not
  go through the owner yet (L2), while watch.ts's restart behind a chat does, through `restart.sh`; planning an Assistant's Azure start and
  credential-presence preflight move with the first Azure dispatch (A2, L2); the settings file
  keeps no counter, so a change away and back reads as unchanged.
- Authored regressions: `test/test_launch_admission.py` (processes, a stateful `hc` stand-in,
  reopened journal and task list) and `service/launch-sites.test.ts`. CI pending; native
  qualification pending. The chat mod's start is source-inspected only.

### Bitbucket contract

Port P's behavior into native owners, not its old server paths. GitHub retains
its transport. Keep local Git, approval, task state and cleanup outside the adapter.
Preserve provider-qualified identity, host-owned credentials without fallback,
frozen push routes, preflight before effects and current exact-candidate admission.
Preserve persistent draft publication, readiness preparation and current title,
reviewers, destination and `close_source_branch`. Create sets that flag to false;
preparation preserves its current value. True requests source-branch closure.
Exact-commit checks retain complete pagination and distinct missing/incomplete/
pending/failed/passed outcomes. Empty checks cannot establish readiness.

Persist an operation UUID before uncertain dispatch. Lost reply, empty lookup or
changed context cannot justify retry or replacement. Positive exact reconciliation
retains the same UUID. Preserve confirmed push facts and truthful typed unknown
CLI outcomes. `ready`, `show --evidence` and `accept` cross the native workflow;
readiness needs a durable draft/preparation stage instead of apparent success
despite uncertain publication. Keep Bitbucket native merge refused absent an
official expected-source-head guarantee. No GitHub/local/agent merge fallback.
Feedback, base health and extra provider features stay outside this scope.

### Azure contract

Personal remains the default, preserving native CLI configuration and sign-in;
it does not force a personal account. Use general-purpose fields without a fixed
tenant/account or organization. Provider connection, endpoint/resource, authentication
and discovery subscription remain human-owned at every scope.

Port existing explicit Refresh and manual deployment entry for both CLIs in
desktop/web settings and task/coordinator new-start selectors. Inventories are
scope-specific and memory-only. Keep explicit subscription reads, unique resource
matching, public-cloud/local-only bounds and Everywhere's single-machine rule.
Offer only Succeeded Anthropic/chatCompletion or OpenAI/responses deployments;
exclude missing capability metadata. Display deployment IDs separately from model
names/versions. Retain saved/manual choices and Default effort for unknown models.
Coalesce refreshes, clear failed/stale results and reject in-flight responses after
endpoint/resource/subscription changes. Sanitize errors. No automatic selection
or replacement. Refresh never starts an agent, signs in or sends inference.
Inventory and credential presence do not prove account, inference, tool or effort support.

Re-ground the following existing authentication inputs against official exact-version
CLI/Azure docs at implementation admission. Do not infer other combinations.

| CLI/authentication | Fresh launch and resume reconstruction |
| --- | --- |
| Claude Entra ID | Native Foundry resource/deployment environment; execution-host SDK default credential chain; blank inactive credentials/competing routes. |
| Claude API key | Same routing; inherit `ANTHROPIC_FOUNDRY_API_KEY`, blank inactive token/competing routes. |
| Claude supplied bearer token | Same routing; inherit `ANTHROPIC_FOUNDRY_AUTH_TOKEN`, blank inactive key/competing routes; host owner renews it. |
| Codex API key | Azure `/openai/v1` Responses route; stable reserved provider table with `env_key=AZURE_OPENAI_API_KEY`. |

The same provider owner plans fresh launch and resume from the admitted nonsecret
binding. Reconstruct Claude environment because native `env_of()` only recreates
browser-task metadata. Independently verify Codex provider/model/effort/Fast retention.
Values remain in the admitted execution-host environment, never argv, settings,
labels, logs, stored records or persisted core environment overrides.

Resume retains recorded routing, deployment, authentication, native session and
hooks. New defaults do not rewrite it; changed retained routing refuses before
interruption or authority replacement. Model selection does not choose an account;
configuration fingerprints do not attest account identity. Credential rotation alone
does not change the fingerprint. Save-only new-start choices remain revision-bound,
send no prompt and preserve task holds. A stopped recorded chat is not unstarted.
No silent Personal fallback, remote Azure expansion, new cloud or cross-CLI reuse
of an Azure conversation. Deployment discovery is unrelated to the separately
owned LogTape/JSON/command-discovery research.

### Recovery disposition

All evidence here is source-inspected, not runtime-qualified.

| Behavior | Chosen disposition/owner | Independent qualification or gap |
| --- | --- | --- |
| Ordinary crash/manual resume | Reuse native `T/revive.py` and resume through one admission owner. | Same session/history/provider, one execution; restart is not reboot. |
| Kept terminal/screen reconnect | Reuse native hub/screens/attach. | Current execution and screen identity; reconnect is not dispatch proof. |
| Convenience failed starts | Reuse native where qualified; conditional retirement. | Bounded handling without duplicate launch; exact convenience gaps remain human choices. |
| Missing history | Native fresh fallback remains a gap decision. | Explicit new-session identity; allow fresh fallback or retain hold per case. |
| Provider/model/effort/Fast | Port binding enforcement; reuse qualified parsing. | Both CLI resumes after defaults change; labels do not prove provider/account. |
| Unknown core submission | Port journal guarantee into `T/launch_admission.py`. | Never-submitted versus submission-uncertain; no inventory-based release/retry. |
| Late old sender/replacement | Port application fence; native process authority remains a gap. | Delayed sender cannot regain dispatch; journal alone cannot fence unknown PTY execution. |
| Manual uncertain recovery/reboot | Retain old-state custody; port demonstrated requirements only. | Exact identity/revocation, reboot evidence and past-effect uncertainty remain separate. |
| Provider retries/queued delivery | Reuse qualified native retry; port missing guards/receipts. | No replay after uncertain effect or changed binding. |
| Task cleanup/approval/lifecycle holds | Reuse native owners; port uncovered guarantees. | Exact approval head, owned descendants, no unrelated-worker effects. |
| Protected update | Retain operational hold; cutover admission separate. | Native restart is not idle-safe update proof. |
| Plugins/public persisted state | Required Q/R compatibility review. | Registry/failure isolation, last-good behavior, outbox/drafts, labels/state formats; no automatic import. |

Use one revival/admission owner for task and coordinator dispatch. No competing
revival loops. Native receipt/revocation gaps remain held until independently proved
or Nathan chooses the exact tradeoff. Do not automatically port all old lifecycle code.

## Verification contract

Check retains native tagged suites. Old Foundry/core-rewrite workflow bodies and
their test/sensitivity obligations remain fixed F sources, recorded by hash in the
inventory. Q must port or explicitly reconcile every obligation. Default native
tests do not establish fork parity. Old optional production-plugin proof is not
silently considered covered by default tests.

Root runs `python3 bin/check-migration`, its public-CLI checkpoint tests
(`test/test_migration.py`), the A1 provider and discovery tests (`test/test_providers.py`,
`service/azure-deployments.test.ts`), the N1 publication tests (`test/test_native_publication.py`),
the C1 discovery tests (`core/chat-find.test.js`, `test/test_session_discovery.py`),
the W1 flag tests (`service/jobs-flags.test.ts`), the H1 listener tests
(`service/private-domain.test.ts`), the S1 forge tests (`test/test_forge.py`), the B1
Bitbucket read tests (`test/test_bitbucket.py`), the B2 publication tests
(`test/test_bitbucket_publication.py`), the L1 launch admission tests
(`test/test_launch_admission.py`, `service/launch-sites.test.ts`) and every native Check command. CI owns
frozen dependency installation, web
generation, shared-copy/parser checks, typecheck, Bun service/core/web tests,
Python tests and production build. Locally run only `bun run typecheck`.
Missing dependencies/generated web sources are prerequisite blockers, not authority
to install or build. Static declaration counts are not executed test counts.

Dependent proof crosses public commands and actual process/durable-state interfaces.
Bitbucket covers zero-effect preflight, complete exact checks, current fields, lost
responses, reopen/no retry, same-UUID reconciliation, two-machine exclusion and merge
refusal. Azure covers both filters, scopes/subscriptions, stale responses, sanitized
manual fallback, save-only effects, each admitted authentication route and bound resume.
Recovery separately covers crash, missing history, uncertain launch and late sender.
Task locks and core document CAS do not inherently establish receipts or idempotency.

## State and cutover

No live state conversion occurs in S0. Separate service data does not isolate HOME,
core, task ownership, shared helpers/hooks or synchronization. No installer/service/
mod init or real-home parity command is admitted. Existing conversations, worktrees,
credentials and runtimes are preserved and are not source fixtures.

Hold state carryover, conversation migration, genuine fresh-session gaps, manual
recovery, costs, rehearsal budgets, shared merges and deployment for named decisions.
Rollback pairs exact executable/core versions with matching state/configuration,
templates, helpers, links and hooks. Unknown effects/claims cannot disappear during
conversion. Independently stop authorized new writers before restoration; restoring
a database does not prove an old process ended.

Preserve F/U/P. After PR3's recorded decision, qualify main/integration composition
explicitly without rebasing F or silently folding P into ancestry. Source admission
does not authorize installation, native requests, shared merge, state import or cutover.
Root's S0 inspection and CI precede every dependent phase.

## Implementation and review handoff

Implementation and independent review are separate assignments. Root qualifies S0
and owns the isolated source handoff. Review uses the exact committed candidate
and its scoped brief; an implementer does not independently approve its own work.
Operational assignments and trust/readiness receipts belong to the native
conversation and runtime handback, not this portable repository contract.

Azure implementation and independent review require
`my-second-brain-playground:cli-design`, maintain/extend existing-project route.
Each execution harness resolves and reads its active installed SKILL.md and required
references first. Resolve that harness's active registration rather than a fixed
cache path or version. Do not refresh/install plugins or borrow another machine's paths.
Use the complex profile because authentication, authority, ordered effects and
uncertain submissions are involved. Preserve native Python task CLI ownership and
host output/exit/serialization contracts; do not bootstrap, compose, replatform,
install Fallow or change dependencies/tooling to satisfy a template.

Capture affected commands/entry points, inputs, effect classes, public results and
current contracts. Trace source help, exact argv/environment construction, official
Claude/Codex Azure contracts, authenticated mailbox results, persisted provider/session
bindings, launch journals and existing process regressions. Prove secret redaction,
unsupported-route refusal before effects, revision/fencing/uncertainty and truthful
repair hints through public entry points with reopened persistence. Return scoped
code/help/tests where affected, expected-versus-observed matrices and exact-candidate
Root CI evidence. Local verification stays typecheck-only.

Contract Core 2.0 JSON envelopes, LogTape and command discovery remain separate,
unapproved adoption work. Record compatibility gaps rather than claim full Contract
Core conformance or silently alter defaults. Autonomous recovery, breaking defaults,
extra clouds and remote execution remain human choices. This requirement starts no
Azure phase, new agent, provider probe, runtime change or external write in S0.
