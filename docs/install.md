# Install

Shepherdr 3.1.3 is a layout for the Herdr app plus its mods, helpers and role instructions, and a web app for your tailnet ([Web](web.md)). One script puts them in
place, never overwrites what you made yourself, and keeps a backup of anything it replaces.

## Requirements

- macOS or Linux, the Herdr app 0.1.12 or newer (`herdr-app --version`) with herdr-core 0.1.17 or newer
  (`hc --version`). Open Herdr once first, so it writes its home (`~/.config/herdr-app`).
- python3 3.8 or newer, git, and Claude Code or Codex, installed and signed in.
- bun (the service and the web app; the installer installs it from bun.sh when it's missing), and Tailscale for the
  web app.
- Optional, per add-on: `gh` (pull requests; a repo with a GitHub remote needs it, see
  [Pull requests and credentials](#pull-requests-and-credentials)), agent-browser 0.41.1, node and Chrome (the task
  browser), bun, `pw-record` and whisper.cpp (`whisper-cli`) for dictation, an ElevenLabs key for voice calls.

## Pull requests and credentials

In a repo with a GitHub remote, `herdr-task ready` publishes a worktree task and Accept merges it through its pull
request. A repo with no remotes merges locally, and so does one whose remotes are all on Bitbucket Cloud, GitLab.com or
Azure DevOps, without asking `gh`. So does one `gh` says has no remote on a host it knows, unless `gh` has confirmed that
repo on GitHub before with the same remotes, and one with no `gh` installed, no remote recognisably GitHub's and no
saved repo name.

- `gh` and `git push` sign in separately. `gh` reads and opens pull requests. `git push` uses whatever the remote's own
  configuration gives git. A refusal says which of the two failed, and with `--json` its `cause` is `gh` or `git`. Their
  own words are shown and kept without a URL's user and password.
- `herdr-task` runs `gh` from `PATH`, or the command named in `HERDR_TASK_GH`. Shepherdr holds no credential of its own
  for either.
- Any other failure of `gh` in a repo with a remote (signed out, no network) makes `ready` and Accept refuse and leave the
  task as it was, as does `gh` not installed or not on the caller's `PATH` when a remote is recognisably GitHub's. They
  never merge locally instead, because nobody can then say whether a pull request exists. Only the default `gh`, with
  nothing of that name on `PATH`, counts as not installed: a `gh` that can't run, or a `HERDR_TASK_GH` that can't run or
  doesn't exist, is that other failure, whatever the remote.
- An alias or Enterprise repo `gh` has never confirmed, with `gh` not knowing that host, takes `gh`'s no and merges
  locally: `gh` can't tell it from a host that isn't GitHub. A repo `gh` has confirmed keeps refusing. A saved no is
  asked again once before each local merge, so a repo `gh` now places on GitHub doesn't merge locally.
- A branch GitHub already holds at exactly its commit isn't pushed, so publishing it needs only `gh`'s access.
- `herdr-task adopt <task> --pr <number or link>` records a pull request that already exists on a started task, when
  its target differs from the base the task recorded. It reads and checks, and never creates, pushes or merges. The pull
  request must be this repo's own and open, for the task's branch, at exactly its tip. The task's start commit must be
  the one merge base of that tip and the commit GitHub's base branch holds now, and the recorded base's commit must be
  in that commit too (a task with no recorded base is checked against `main`; a base that is only a commit refuses).
  The task's base then becomes the pull request's, the old one is kept as `adopted_from`, the tip it verified is kept as
  `adopted_head`, and it merges only on the person's Accept. Accept refuses unless the pull request still targets that
  base and both its head and the branch here are still at `adopted_head`. `ready` never changes `adopted_head`; running
  `adopt` again after the branch has moved verifies it again and records the new tip. That works for a rewrite on the
  same start: after a rebase onto a base that has moved, the merge base is no longer the task's start, so `adopt`
  refuses. A retarget between Accept's read and the merge isn't caught. If it merges into any other branch anyway, the
  task isn't finished: Accept and the tick hold it, its worktree and branch stay, and `herdr-task done <task>` is the
  person's way out. The base commit must be in this clone: a `git fetch` first, if adopt asks for it, is the one step
  that uses git's own access.
- `ready` opens no second pull request for a branch. When the branch's open pull requests all target another base, it
  refuses before pushing and names the `adopt` command to run.
- A finished task's branch and worktree go only when the branch's tip is the commit that merged and the worktree holds
  nothing uncommitted (ignored files aside). For a pull request that's the head GitHub merged, never its squash commit;
  with none, a tip already in the base branch. Otherwise both stay, and the done task says why in `kept`, which Accept,
  merge and `show` print. That note is written when the task is finished; while an agent still runs in it, finishing
  leaves both and writes no note. `gh pr merge`, run with `--repo`, deletes only GitHub's copy of the branch (gh 2.101
  source, read, not run). A merge here into a base that is only a commit, not a branch, refuses.

## Install

```bash
git clone https://github.com/eliasstravik/shepherdr && cd shepherdr
./install.sh --dry-run      # what it would do; nothing is written
./install.sh                # do it
shepherdr doctor            # check it
```

Then in Herdr, `Ctrl+Shift+L` picks the Shepherdr layout.

A fresh clone has no web app built (`web/dist` isn't in git): the installer builds it with Bun (`bun install`,
`bun run build`) whenever it's missing or older than its sources, so nothing to do by hand. A build that fails stops
the install before anything is written.

What goes where:

| What | Where |
|---|---|
| The layout | `~/.config/herdr-app/layouts/shepherdr.json` |
| 29 mods (the add-ons, [Add-ons](addons.md)) | `~/.config/herdr-app/mods/<name>/`, one swap per mod so Herdr reloads each once |
| Shared modules, helpers | `~/.config/herdr-app/lib/`, `~/.config/herdr-app/bin/` |
| Keys | merged into `~/.config/herdr-app/keys.json`: free keys added; a key you already use is asked about (kept without a terminal; `--keys ours` takes Shepherdr's) |
| Role instructions | `~/.config/herdr-core/templates/{assistant,worker,reviewer}.md`; one you edited is kept, the new one goes beside it as `.new` |
| Helpers on the PATH | links in `~/.local/bin`: `herdr-task`, `herdr-artifact`, `herdr-secret`, `herdr-browser`, `shepherdr` |
| Question cards | hooks in `~/.claude/settings.json` (SessionStart, PermissionRequest) and `~/.codex/hooks.json` (SessionStart); `--no-hooks` leaves them out. Codex asks once to trust a new hook, and needs `hooks = true` in `~/.codex/config.toml` |
| The guard (`--guard`, opt-in) | `~/.local/bin/herdr-app`: refuses to open a window with another HOME, `HERDR_APP_HOME` or core session (it can overwrite every machine's spaces); subcommands pass through |

What it records: `~/.config/herdr-app/data/shepherdr/installed.json`, a sha256 per file it put there. Running it
again changes only what changed; a file you edited since is kept (the new copy goes beside it as `.new`).

What it backs up: anything it replaces or removes, in `~/.config/herdr-app/.shepherdr-backup/<time>/`, at the same
path under your home.

What it refuses: a mod, layout, lib or bin file by the same name that it didn't install and that differs (your own
mod called `chat`, say). Nothing is written then; it names each one. `--adopt` backs them up and takes them over.

## Options

```text
./install.sh [--root DIR] [--dry-run] [--adopt] [--guard] [--keys ask|keep|ours] [--no-hooks] [--no-build] [--yes] [--force]
./install.sh --web    the web app alone, without the Herdr window
shepherdr update      the same kind again (layout, or web only), from the checkout it was installed from (git pull it first)
shepherdr uninstall   [--root DIR] [--dry-run]: takes out what it installed and puts back what it replaced
shepherdr doctor      [--root DIR]: checks files, links, shared copies, herdr-task and the programs it needs, and says how to update
shepherdr whisper     downloads dictation's model (148 MB, checked by its sha256)
```

`--root DIR` installs under another folder instead of your home (it mirrors `.config/herdr-app`, `.local/bin`,
`.config/herdr-core/templates`, `.claude`, `.codex`): a scratch try you can look through and diff. It never starts
Herdr there.

## Other machines

Nothing to install by hand. herdr-task copies itself, `herdr-artifact`, `herdr-secret`, `herdr-browser` and the role
instructions to every connected machine (`herdr-task machines sync --check` shows what it would do). While an install
or update replaces one of those, `~/.herdr/sync-hold` stops every copy to another machine until `shepherdr doctor`
finds the install whole: the scheduler's sync, `herdr-task machines sync` (it says "held"), herdr-task's and
herdr-artifact's own copy when they run a command there (the copy already there runs instead), and
`herdr-secret install --on`. So a half-done copy never reaches every machine. Turning the Other machines add-on off stops the
sync too.

## Uninstall

`shepherdr uninstall` removes the files it installed that you haven't changed (a mod you changed stays whole), its
keys (putting back any it replaced), links, guard and hooks, and puts back what the install replaced. Your Herdr
`data/`, `~/.herdr` (tasks, worktrees, artifacts, secrets, settings) and your own mods stay. Switch Herdr to another
layout first if Shepherdr's is showing.
