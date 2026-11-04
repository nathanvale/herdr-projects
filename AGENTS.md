# Working on Shepherdr

- Code changes or review: read [CODING_STANDARDS.md](CODING_STANDARDS.md).
- Development or previews: read [docs/develop.md](docs/develop.md).
- Verification: run only `bun run typecheck` locally, including before
  merge. Reserve this machine's capacity for the application and agents.
  Leave test suites, browser tests and production builds to CI.
  Inspect UI changes manually in the shared browser.
- Plugin work: read [docs/plugins.md](docs/plugins.md).
  User-requested personal plugins belong in
  `~/.shepherdr/plugins/<name>/`, outside this repository.
- Deployment or state migration: read
  [docs/core/cutover.md](docs/core/cutover.md).
- Specialized workflows: follow [docs/agents/README.md](docs/agents/README.md).

## README and releases

- Changes to README design, layout, structure, hero or length require
  explicit user approval. Otherwise, correct false facts in place,
  preserving the voice. Put detailed documentation in `docs/`.
- "The previous README" means its version on main immediately before
  the change, never a release tag.
- Version bumps, tags, GitHub releases and publishing require explicit
  user approval. Use patch bumps unless minor or major is requested.

## Agent skills

### Issue tracker

Use GitHub Issues for new engineering-skill issues and specs.
Read [tracker routing](docs/agents/issue-tracker.md).

### Triage labels

Use the five default roles.
Read [label mappings](docs/agents/triage-labels.md) before triage.

### Domain docs

Use the existing single-context glossary and ADRs.
Read [domain guidance](docs/agents/domain.md) before exploration.
