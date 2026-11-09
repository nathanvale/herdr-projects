# Fallow maintainability report

[Fallow](https://fallow.tools/docs/) (MIT, [fallow-rs/fallow](https://github.com/fallow-rs/fallow)) reads the
JavaScript and TypeScript in this repository as one import graph. It reports unused code, broken imports,
copy-pasted code and complex functions. Here it is **report-only**: CI shows its findings and never fails on them.

## What it finds, and what it does not

It finds, in `mods/`, `lib/`, `core/`, `service/`, `web/` and `scripts/`:

- unresolved imports: a path or package that does not exist (a typical invented import)
- unused files, exports, types, class members and dependencies
- circular imports and duplicate exports
- copy-pasted blocks (clone groups)
- functions above the complexity limits (cyclomatic 20, cognitive 15) and maintainability hotspots

It does not read the Python task CLI, shell, Swift, Markdown or JSON. It does not run code, so it cannot find wrong
behaviour, logic errors or weak tests. Its default analysis is syntactic: no TypeScript type checking. Its
`security` command is not set up here. **A clean report does not prove that code is free of AI-generated
problems**; it covers the structural ones above. Fallow's own
[limitations page](https://fallow.tools/docs/analysis/limitations/) lists its known false positives.

## Run it

CI runs Fallow on every pull request, so running it yourself is optional. Fallow is pinned in its own tool
package, [tools/fallow](../tools/fallow/package.json), so the root `package.json` and `bun.lock` stay exact
upstream. Install it into the checkout (no global install):

```bash
bun install --cwd tools/fallow --frozen-lockfile
```

Fallow reads the root `node_modules` to classify dependencies and `web/generated` for the web app's plugin list,
the inputs CI builds before its Fallow step. Where they are missing, they are a prerequisite
([develop.md](develop.md)), not something to create for Fallow: without them its results differ from CI's, and
the CI report is the reference.

| Command | What it shows |
|:--|:--|
| `bun run --cwd tools/fallow report` | The whole repository: dead code, duplication and complexity |
| `bun run --cwd tools/fallow audit` | Only what your branch adds, compared with `origin/integrate/upstream-v3.1.3`. Set `FALLOW_AUDIT_BASE` to compare with another ref. |
| `bun run --cwd tools/fallow baselines` | Saves the three baselines again (see below) |

Add Fallow flags after the script name, for example `bun run --cwd tools/fallow report --format json`.
`fallow explain <issue-type>` (`tools/fallow/node_modules/.bin/fallow explain unused-export`) says what a finding
means and how to fix it. Fallow writes a local cache to `.fallow/`, which ignores itself in git.

Fallow's exit code: 0 or 1 is a finished analysis (1 means findings), and 2 or above means it could not run (for
example, an invalid config).

## In CI

The `check` job's "Fallow maintainability report" step runs after the service build:

- every run adds the whole-repository report to the job summary
- on a pull request it also adds the audit verdict for the changed files, and marks each new finding on its line
  as an annotation

Findings never fail the step. An annotation can show as an error, because it keeps the rule's own severity. A
Fallow failure to run (exit 2 or above) fails the step, so a broken setup cannot look like a clean report.

## Configuration: what is modelled and why

[.fallowrc.json](../.fallowrc.json) states facts about how this repository runs. It changes no rule severity or
threshold and holds no suppressions.

- `entry`: files that the runtime starts and nothing imports: each mod's `main.js` and TypeScript helpers, the
  `lib/` sources of shared copies, the web app's `main.tsx` and plugin clients (listed only in the git-ignored
  `web/generated/`), the service worker and the two services `bin/shepherdr` starts. `scripts/*.ts` are support
  entries (manual tools).
- `ignoreDependencies`: `gpui-base`, `gpui-kit` and `herdr`, which the Herdr runtime provides.
- Generated copies: `bin/sync-shared` copies each `lib/` and `core/` module into the mods that
  [lib/COPIES](../lib/COPIES) lists. The config names each copy so duplication and complexity are reported once,
  at the source, and so a shared module's exports are not reported unused in every copy.
  [test/test_fallow_config.py](../test/test_fallow_config.py) fails when this list differs from what
  `sync-shared` writes. When you edit `lib/COPIES`, edit the three copy lists in `.fallowrc.json` the same way.

Known noise left in the report: `lib/` sources import `./core/<file>.js` as their copies will, so those imports
show as unresolved in `lib/`. Binaries the machine provides (`hc`, `herdr-task`, `tailscale`) show as unlisted
binaries.

## Baselines

[fallow-baselines/](../fallow-baselines) holds the findings as they were when Fallow was adopted, saved with
Fallow's own `--save-baseline`. `fallow audit` loads them (the `audit` block of the config), so findings already
in a baseline are not counted as new. Save them again with the `baselines` script only after a deliberate cleanup
or on a fixed schedule, never to make a change look clean: a refreshed baseline hides what the change added.
Commit the refreshed files on their own, with the reason. When code is fixed, the old entries go stale and Fallow
says so; `fallow baselines prune` removes only stale entries.

## Open decisions

These belong to the maintainer and are not set here:

- whether the audit verdict should fail CI, and for which rules
- the complexity and duplication limits to enforce (1132 functions exceed the defaults today)
- whether to keep committed baselines, and how often to refresh them
- whether a Fallow failure to run should keep failing the step or only warn

## Upgrading Fallow

Change the exact version in `tools/fallow/package.json`, run `bun install --cwd tools/fallow`, and update the
`$schema` tag in `.fallowrc.json`. Read the [changelog](https://fallow.tools/changelog) first: a new release can
add finding types, which then show up as new findings.
