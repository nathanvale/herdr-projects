# Working on Shepherdr

- Before work, read `$HOME/code/dotfiles/config/agents/global.md`.
- Code changes or review: read [CODING_STANDARDS.md](CODING_STANDARDS.md).
- Upstream migration or candidate readiness: read the [migration contract](docs/migration/upstream-v3.1.3.md).
- Architecture, development and CI: read [docs/develop.md](docs/develop.md).
- Specialized workflows: use [docs/agents/README.md](docs/agents/README.md).

## Verification and execution

- Run only `bun run typecheck` locally. CI owns suites, parser checks, shared-copy checks, browser tests, installer tests and builds.
- Missing dependencies or `web/generated` are prerequisite blockers. Do not install or generate them without the unit's authorization.
- Keep the migration source-only until required ports and qualification pass. A source checkpoint is not candidate deployment readiness.
- Native mod checks execute `init()`. Settings initialization can push to other machines. Run no app/mod initialization or real-home parity scripts.
- Another folder, home or port does not prove isolation. Running a branch's herdr-task remotely can distribute its code fleet-wide.
- Preserve unrelated workers, conversations, worktrees and credential owners. Installation, service changes and live state conversion need separate authority.

## Public contracts

- Preserve provider-qualified forge identities, exact-candidate admission, durable unknown outcomes and the approved Bitbucket merge refusal.
- Preserve Personal defaults, Azure discovery/manual entry and existing conversation bindings. Provider connection controls belong to the human.
- Use one revival/admission owner. Qualify ordinary resume, missing history, uncertain submission and late-sender exclusion separately.
- Edit shared `lib/` or `core/` sources rather than generated mod copies. Follow the source's generation owner within the permitted verification scope.

## README and releases

- Changes to README design, layout, structure, hero or length require explicit approval. Correct false facts in place; detailed documentation belongs in `docs/`.
- "The previous README" means its version on main immediately before the change.
- Version bumps, tags, releases and publication require explicit approval. The imported upstream version is source provenance, not a new fork release.
