# Develop

```text
layouts/shepherdr.json   the layout (two live blocks shipped blank: tasks-thread-term, artifacts-view-body)
mods/<name>/             the 29 mods, installed as they are (names fixed: data/<mod> state follows them)
lib/                     shared modules, one source each; bin/sync-shared copies them into the mods in lib/COPIES
lib/addons.json          the add-ons: mods, blocks, keys, helpers, needs, web plugins (docs/addons.md)
lib/features.json        every feature: its Herdr side, its web side and its shared logic (CI checks all three)
core/                    the logic the mods and the service share (plain JS; copied into mods by bin/sync-shared)
service/                 the always-on service (Bun): the web app's API, background work, tailnet sharing (docs/web.md)
web/                     the web app (React, Vite, Tailwind; 2.1's design): src/, plugins/, shared/
bin/shepherdr            the installer (install, update, uninstall, doctor); ./install.sh runs it
bin/                     herdr-secret, herdr-browser, herdr-browser-view, sync-shared (installed to the app's bin/)
mods/tasks/bin/          herdr-task (entry) and its herdr_task package
mods/artifacts/bin/      herdr-artifact
templates/               assistant.md, worker.md, reviewer.md (herdr-core templates)
guard/herdr-app          the window guard (--guard)
keys.json                Shepherdr's keys, merged into the person's
test/                    python tests: repo rules, the installer in throwaway roots, herdr-task
scripts/parity.py        a scratch install against this machine's live Herdr home, file by file
tools/fallow/            the pinned Fallow tool package; .fallowrc.json and fallow-baselines/ (docs/fallow.md)
RECIPE.md, preview.png   the herdr.dev listing (repo topic herdr-layout)
```

## Rules

- Edit `lib/<file>` or `core/<file>`, never a mod's copy, then run `bin/sync-shared`; `bin/sync-shared --check` must pass.
- A new mod: add it to an add-on in `lib/addons.json` (the tests fail otherwise), write its `mod.json` before or
  with `main.js`, and list it in `lib/COPIES` for each shared module it imports.
- Nothing personal: no absolute home paths (use `home()`, `appHome()`, `$HOME`), no machine or account names, no
  live terminal or artifact ids in the layout. `test/test_repo.py` checks.
- Version: `VERSION` in `bin/shepherdr`, the top of `CHANGELOG.md`, `RECIPE.md` and the README say the same.
- Maintainability: CI adds a report-only [Fallow](fallow.md) report to every check. A change to `lib/COPIES` must also
  change the three copy lists in `.fallowrc.json` (`test/test_fallow_config.py` checks).

## Fork verification and migration

Follow [AGENTS.md](../AGENTS.md). Local verification is only `bun run typecheck`.
CI owns the commands in [Check](../.github/workflows/check.yml), including shared
copies, parser checks, frozen dependencies, web generation, suites and builds.
Missing `node_modules` or `web/generated` is a prerequisite blocker, not permission
to install or build. See the [source migration contract](migration/upstream-v3.1.3.md).

This source checkpoint is not deployable. Do not run its installer, service, app/mod
initialization, scheduler or `scripts/parity.py` against a real home. Mod init can
push settings and remote task execution can spread this branch's code. Another
folder/home/port is not isolation proof. Runtime rehearsal is separately admitted.

## The herdr.dev listing (at release, with the person's yes)

- The repo root is the listed layout folder: `layouts/shepherdr.json`, `mods/`, `RECIPE.md`, `preview.png`,
  `keys.json`. herdr.dev reads the recipe's title and first paragraph.
- Repo topics: add `herdr-layout` (the listing), keep `herdr` and `shepherdr`, and drop `herdr-plugin` (the
  terminal-plugin card; `herdr-plugin.toml` is gone from main, 2.1 stays installable from `v2.1`).
- Tag `v3.0.0` and the GitHub release only after the person says yes; patch bumps after that.

## Claude Code checkout access

`.claude/checkout-access.json` names the folders every Claude Code session in this repository may reach, relative to the main checkout. `bin/checkout-access preview` shows the scope; `apply` writes their absolute paths to the main checkout's untracked `.claude/settings.local.json`, and `rollback` removes only what it added. Claude Code resolves relative `additionalDirectories` against each session's folder, so a tracked value can't be right everywhere. It reaches sessions under any Claude profile.
