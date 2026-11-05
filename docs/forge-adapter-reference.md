> Historical 2.x contract reference from fixed F/P. Old implementation paths refer
> to those Git trees, not this native foundation. See the [migration contract](migration/upstream-v3.1.3.md).

# Forge adapter reference

This page describes the FORG-1 candidate and the requirements for its Bitbucket extension.
The implementation is under review. Bitbucket operations still refuse in the current candidate.
This page is not a setup guide or a claim of native acceptance.

The [execution contract](forge-adapters.md) owns delivery scope and task order.
The [transport decision](adr/0002-bitbucket-rest-transport.md) explains the direct REST design.
The [authentication and execution design](forge-bitbucket-transport.md) specifies the proposed host helper and host-managed authentication.
The [glossary](../GLOSSARY.md) defines the shared vocabulary. The [review map](forge-review-map.md) connects those terms to source and qualification limits.

## Module ownership

| Owner | Responsibility |
| --- | --- |
| [CoreForge](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/forge/index.ts) | Resolve repository identity and select an adapter. |
| [RepositoryForge](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/forge/types.ts) | Define the shared task-facing operations and results. |
| [identity.ts](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/forge/identity.ts) | Compare written and effective origins, repository identity, and saved PR identity. |
| [GitHubForge](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/forge/github.ts) | Interpret GitHub PRs, checks, comments, and base health through the existing gh transport. |
| [CoreGit](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/git.ts) | Own local Git operations and the existing execution route. |
| [CoreTasks](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/tasks.ts) | Own task approval, state transitions, and task records. |

The planned Bitbucket adapter owns HTTP requests and Bitbucket response interpretation.
Task commands, observers, and worktree presentation consume the shared contract.
They do not parse provider JSON or select credentials.

The adapter does not own worker shutdown, conversation deletion, or worktree removal.
The later completion module consumes verified integration evidence and owns cleanup outcomes.

## Identity and results

`ForgeRepository` contains `provider`, `host`, and `repository`.
`ForgePrRecord` adds the PR number and URL. A PR number alone is not a repository identity.
Existing records without provider qualification retain their GitHub meaning.

`ForgePullRequest` contains the observed source commit, source branch, destination branch, state, and draft flag.
Its optional `mergeCommit` records the provider's reported merge commit.
That field alone does not establish membership in fetched destination history.

`ForgeChecks` binds checks to `head` and records whether the result is `complete`.
Missing, incomplete, pending, failed, and passed checks have different meanings.
The Bitbucket extension cannot treat an empty or truncated result as a passed check set.

`ForgeIntegration.state` admits `accepted`, `pending`, `uncertain`, and `merged`.
An accepted request is not confirmation that the PR merged.

## RepositoryForge operations

These are the current interface names. The guarantees below are required for each provider.

| Operation | Result or effect | Required boundary |
| --- | --- | --- |
| `read` | Read a PR and optional checks. | Match any saved identity against the observed repository and PR. |
| `publish` | Find or create the task PR. | Reconcile a lost create reply before considering another create. |
| `prepare` | Update the PR description and draft state. | Reject a changed source commit, source branch, or destination. |
| `integrate` | Request integration. | Enforce the approved source commit or refuse before a merge request. |
| `comments` | Return published feedback. | Complete pagination or fail without advancing delivery progress. |
| `observeBase` | Return base health and context. | Bind observations to commits and reject a changed base snapshot. |
| `presentation` | Return the worktree PR view. | Report unavailable checks without converting that view into approval evidence. |

## Bitbucket transport requirements

The approved scope is Bitbucket Cloud at `https://api.bitbucket.org/2.0`.
Bitbucket Server, Data Center, and arbitrary API base URLs are outside this change.
REST transport ships with Shepherdr. It requires no additional provider CLI.

Repository identity comes from the admitted Git origin and provider response.
The transport validates the scheme, host, port, path, and repository context before sending credentials.
Redirects and pagination links receive the same checks. A response URL cannot widen credential authority.

Requests execute within the admitted machine and containment boundary.
An unsupported route refuses before network writes or worktree preparation.
The proposed host helper and Git credential lookup are specified in the authentication and execution design. They remain unimplemented.

### Authentication

The proposed host helper obtains a token through Git's existing credential interface and uses Bearer authentication.
Atlassian documents Bearer support for API tokens, access tokens, and OAuth access tokens.
The [authentication documentation](https://developer.atlassian.com/cloud/bitbucket/rest/intro/#authentication-methods) defines provider credentials.
The [API token guide](https://support.atlassian.com/bitbucket-cloud/docs/using-api-tokens/) documents API-token Bearer authentication.
A credential that works for Git still requires REST compatibility and the permissions needed by the requested operation.

Shepherdr adds no Bitbucket authentication settings or credential store. The proposed helper uses the execution host's existing Git credential owner.
Credential values stay out of task records, PR bodies, command arguments, errors, logs, and browser snapshots.
The existing [secret-access contract](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/docs/secrets.md) remains authoritative.
Its agent mailbox does not automatically grant a background observer access to credentials.

The extension has no required account, workspace name, 1Password item, or operating-system keychain entry.
GitHub continues to use gh authentication. Bitbucket uses a host Git credential helper because gh does not authenticate to Bitbucket.

### Pagination and bounded reads

Atlassian supplies an opaque `next` URL. Absence of `next` marks the final page.
The transport follows validated links rather than constructing page numbers.
See the [pagination contract](https://developer.atlassian.com/cloud/bitbucket/rest/intro/#pagination).

Page, response-size, and time limits prevent unbounded reads.
A limit, malformed page, or repeated link produces an incomplete result or a refusal.
Incomplete checks cannot authorize integration. Incomplete feedback cannot advance the saved delivery position.

### Writes and uncertain outcomes

A lost create reply requires a read using the original repository, source, destination, and saved PR identity.
An ambiguous match stays unresolved. A timeout does not authorize a second create.
Rate limits and transport errors preserve the distinction between failed reads and uncertain writes.

The documented Bitbucket merge request has no expected-source-commit field.
The resulting design decision is to refuse native Bitbucket merge under the exact-commit approval requirement.
A preflight read cannot close the race before a later merge request.
The [merge API](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/#api-repositories-workspace-repo-slug-pullrequests-pull-request-id-merge-post) also permits a queued result with a polling location.
Queued acceptance is not completion evidence.

External merge observation remains in scope. It verifies repository and PR identity, source, destination, and merge commit against fetched history.
Cleanup does not repeat integration. Remote source-branch deletion remains outside scope.

## Compatibility and verification status

GitHub keeps its existing gh authentication and command execution route.
Legacy PR records, exact-commit approval, task holds, conversations, and lifecycle hooks remain compatibility requirements.
Adding Bitbucket preserves existing provider settings and running installations.

The current candidate exposes the shared interface and GitHub implementation.
Bitbucket transport, authentication setup, and native acceptance are not complete.
The Enterprise-host presentation repair passed bounded source review and local typecheck.
Its source checkpoint is `9194764e7957d310e06d64be4c3c4ca3e0746f53`. CI and dependent-task admission remain separate.

The acceptance boundary covers public task commands and observer behavior, not only HTTP helper tests.
Required cases include cross-repository responses, changed heads, incomplete pages, lost replies, credential redaction, and unsupported execution routes.
Persisted-state cases reopen the store before reconciliation.
The repository permits only `bun run typecheck` locally. Its CI owns test suites and builds.

Rollback retains task records and conversations. It does not erase provider-qualified identities to make an older binary accept them.
An older version's ability to reopen new records requires explicit qualification before rollback is claimed safe.
