# Coding standards

## Regression coverage

- Write meaningful regressions with changes. Follow [AGENTS.md](AGENTS.md)
  for local verification; CI runs the tests.
- Add browser cases to their topic's `layout-*.test.ts` file, using
  `test/layout.ts` for setup. Split files exceeding about 20 seconds.
- Core protocol fakes test boundaries. They do not replace native-agent
  or device acceptance.

## Plugin compatibility

- Treat client and server `definePlugin` and `Registry` slots as public
  contracts used by personal plugins.
- Keep existing names working where possible.
- When changing a contract, update [docs/plugins.md](docs/plugins.md) and
  identify the compatibility change in the completion summary.

## Review evidence

- Identify the reviewed revision and verification method.
- Distinguish authored tests, source review, executed checks, CI results
  and native acceptance. A fixture pass proves only its tested boundary.
- Treat proposed ADRs and planned behavior as proposals, not evidence
  of implementation.

See [review boundaries](docs/forge-review-map.md#review-boundaries).

## Module ownership and identity

- Put provider-specific repository, pull request, check and feedback
  interpretation in the forge module. Consumers use `RepositoryForge`.
- Keep local Git, approval, task state and cleanup with their existing
  owners.
- Preserve provider-qualified repository and pull request identities.
  Retain the GitHub meaning of legacy unqualified records.
- Before readiness or integration, revalidate the candidate, source
  branch, destination and saved pull request identity.
- Preserve the exact-commit approval guarantee when adding a provider.
- Keep incomplete or unavailable check observations distinct from
  approval evidence. Follow the task's checks policy for empty results.
- Use glossary terms consistently. Request acceptance, confirmed
  integration and completed cleanup describe different outcomes.

See [forge ownership](docs/forge-adapter-reference.md#module-ownership),
[identity and results](docs/forge-adapter-reference.md#identity-and-results)
and [domain guidance](docs/agents/domain.md).

## Launch lifecycle and recovery

- Preflight the worker and required coordinator before disrupting an
  existing worker or preparing its checkout.
- Preserve admitted configuration and parent identity across
  asynchronous preparation. Revalidate immediately before submission.
- Keep final validation, the transition to submission uncertainty and
  synchronous dispatch free of intervening asynchronous work.
- Persist the exact launch claim before dispatch. If submission may
  have occurred, reconcile that identity rather than launch again.
- Require authoritative non-submission evidence and revocation of the
  old sender's authority before recovering a never-submitted attempt.
  An empty process inventory does not establish either condition.
- State each concurrency guard's ownership boundary. Application
  guards do not establish core idempotency or multi-server safety.

See [launch admission and recovery boundaries](docs/azure-foundry.md#launch-admission-and-recovery-boundaries).
Automatic versus user-triggered recovery remains undecided.

## Authority and provider credentials

- Derive agent authority from the current server-issued grant,
  session and execution-machine identity. Request text and labels
  confer no authority.
- Keep provider routing in validated nonsecret configuration.
  Keep credential values outside provider settings and launch records.
- Preserve human ownership of provider credential destinations.
  Agent commands cannot redirect them.
- Check credential presence without exposing its value or claiming
  that presence proves authentication.
- For authenticated effectful requests, preserve the durable request
  identity and input binding. Interrupted execution must not silently
  redispatch the effect.

See [secret authority](docs/secrets.md#authority-and-transport),
[provider credential handling](docs/azure-foundry.md#credential-handling)
and the [mailbox implementation](server/core/mailbox.ts).

## Settings and plugin behavior

- Preserve settings scope identities and most-specific-value
  inheritance. An explicit empty value differs from Reset.
- Reject invalid settings before replacing saved choices.
- Preserve Personal defaults and recorded conversation bindings.
  A new-start selection must not silently reroute an existing chat.
- Isolate plugin failures. Preserve last-good code or the documented
  built-in fallback, and dispose failed setup and listeners.

See [settings](docs/settings.md),
[provider compatibility](docs/azure-foundry.md#compatibility)
and [plugin migration](docs/plugins.md#21-api-and-migration).

## Mechanical verification

Keep executable rules in their existing checks. Follow
[CI and merge checks](docs/develop.md#ci-and-merge-checks) for execution.

| Property | Check owner |
| --- | --- |
| TypeScript strictness and resolution | [TypeScript configuration](tsconfig.json) |
| Build validity and test execution | [Check workflow](.github/workflows/check.yml) |
| Stale admission, lost replies and delayed senders | [Launch regressions](test/core-launch-admission.test.ts) |
| Authenticated request replay | [Mailbox regressions](test/core-mailbox.test.ts) |
| Settings inheritance and reset | [Settings regressions](test/core-settings.test.ts), [settings layout regressions](test/layout-settings.test.ts) |
| Plugin failure isolation | [Plugin regressions](test/core-plugins.test.ts) |

The [production plugin test](test/core-plugin-production.test.ts) requires
explicit enablement in the [Core rewrite workflow](.github/workflows/core-rewrite.yml).
A green default Check run does not prove that this optional test ran.

## Proposed additions

These recommendations are not established repository requirements.

- Reuse shared presentation pieces and theme variables before adding
  parallel UI primitives. Extend the shared owner when the behavior
  is reusable. See [shared UI](src/ui.tsx) and [plugins](docs/plugins.md).
- Generalize same-operation reconciliation to other external writes
  only after their identity, persistence and retry contracts are
  defined. Current launch and GitHub publication behavior does not
  prove durable recovery for every provider.
- Consider broader pull-request coverage for the existing production
  plugin test. This requires a separate CI scope and cost decision.
