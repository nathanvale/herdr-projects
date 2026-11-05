> Historical 2.x contract reference from fixed F/P. Old implementation paths refer
> to those Git trees, not this native foundation. See the [migration contract](migration/upstream-v3.1.3.md).

# Bitbucket authentication and execution design

This is the FORG-2 implementation design. The helper below is proposed code, not an installed capability.
The [forge contract](forge-adapters.md) retains its task order and completion criteria.
The [adapter reference](forge-adapter-reference.md) defines the task-facing interface.

## Existing owners

| Existing code | Relevant contract |
| --- | --- |
| `CoreTasks` in `server/core/tasks.ts` | Constructs `CoreGit` and `CoreForge`. Owns task changes, publication, and saved PR records. |
| `CoreSource.route` in `server/core/source.ts` | Resolves a machine ID to the current core route. Disconnected or unknown machines refuse. |
| `CoreFiles.exec` in `server/core/files.ts` | Calls `machine.exec` with arguments, working directory, input, and timeout. It exposes no per-call environment option. |
| `CoreRemotes.prepare` in `server/core/remote.ts` | Provisions versioned helper files through core and verifies the remote core identity. |
| `CoreAgents.browserRuntime` in `server/core/agents.ts` | Returns the existing local or provisioned remote runtime. It starts no agent. |
| `CorePilotRepositories.context` in `server/core/pilot-repositories.ts` | Identifies retained contained-repository ownership. |
| `CoreSecrets.use` in `server/core/secrets.ts` | Resolves secrets for an authenticated agent. It is not an observer credential interface. |

The current checked Git helper permits only `git` and `gh`. It does not provide a checked HTTP operation.
The design does not extend that helper into a general command or HTTP dispatcher.

## Authentication follows the host tooling

Authentication follows the existing gh ownership model. Shepherdr does not acquire a second account selector, token setting, environment-variable mapping, or credential store for this adapter.
GitHub continues to let gh resolve its own credentials on the repository's execution host.
The [gh authentication contract](https://cli.github.com/manual/gh_auth_login) owns GitHub login and storage.

Bitbucket REST uses the execution host's configured Git credential helper through `git credential fill`.
This matches host-managed authentication, not the GitHub-specific gh command.
The [Git credential interface](https://git-scm.com/docs/git-credential) supports clients that need credentials from existing helpers.
Git Credential Manager is one possible owner, not a required new dependency.

The Bitbucket helper privately starts `git credential fill` in the admitted regular repository context.
It supplies a credential description for HTTPS, `bitbucket.org`, and the admitted repository path, preserving an explicit HTTPS username when present.
SSH transport usernames such as `git` are not account identities. An SSH origin alone does not provide a REST credential.
Git's existing credential configuration selects the account and whether the path participates in lookup.
The adapter does not rewrite that configuration, widen a failed lookup, or try another account.

Credential output stays inside the host helper. It never becomes a `CoreFiles.exec` result or product record.
The initial supported response is Git's ordinary username and password form, where the password is a Bitbucket API, access, or OAuth token.
The adapter sends that token as Bearer authentication to the fixed Bitbucket Cloud API.
Atlassian documents [API-token Bearer authentication](https://support.atlassian.com/bitbucket-cloud/docs/using-api-tokens/#Using-Bearer-authentication) and [access-token Bearer authentication](https://support.atlassian.com/bitbucket-cloud/docs/using-access-tokens/#Using-access-tokens-for-a-repository-with-Bitbucket-APIs).
Plain account passwords, expired app passwords, and unsupported credential response formats are not supported authentication routes.
A missing or rejected credential causes a bounded setup error, not a Basic-auth fallback.

Git prompts are disabled with `GIT_TERMINAL_PROMPT=0` and a noninteractive askpass command.
GCM prompts are disabled with `GCM_INTERACTIVE=0`, as its [environment contract](https://github.com/git-ecosystem/git-credential-manager/blob/main/docs/environment.md#gcm_interactive) specifies.
The child has a bounded duration and output size. Helper stderr and credential output are never forwarded.
Qualification must identify the installed helper and prove its noninteractive behavior. These controls do not establish that every third-party helper obeys them.

Login, keychain unlock, account switching, and token refresh remain with the installed credential owner.
Shepherdr does not implement an OAuth flow or call `git credential approve` or `reject` to change shared credentials.
The selected helper may refresh its own credentials during `fill`; that is owner behavior, so lookup is not claimed to be a side-effect-free operation.
A Git token may lack PR permissions even when clone and push work. A permission failure identifies the operation that needs access without exposing the token.
An SSH-only user needs to configure a REST-capable token through their chosen host credential helper before using Bitbucket PR operations.

The helper captures one credential for each bounded REST operation and releases it afterward.
It does not persist the token or its refresh token. A host account change can affect the next operation, just as it can with gh.
Shepherdr does not claim an account revision or cross-operation account lock that the host credential owner does not supply.

## Execution host

Each adapter binds one `RepoLocation`, one provider-qualified repository identity, and the admitted Git credential context.
The context contains the lookup host, repository path, and any explicit username, never credential values.

The proposed stateless `helper/core-bitbucket.ts` runs through `CoreFiles.exec` on `RepoLocation.machine`.
It runs on the same core-selected host as repository Git operations, including when that host is remote.
There is no application-server fetch fallback, extra SSH launcher, terminal, or background service.

The helper belongs to the existing immutable helper bundle. Its source and runtime imports are included in `CoreRemotes.PARTS`.
The runtime uses the existing provisioning and remote identity checks. Existing helper versions remain untouched.
The first remote operation can provision a new private helper bundle, which is a filesystem effect, not a read-only probe.
Runtime provisioning requires a separate, explicit activation step.

The child starts from the admitted helper directory, with Bun's automatic dotenv loading disabled.
Its working directory is never the task checkout. Repository-local Bun configuration cannot supply a preload.
Qualification must verify that the selected host's configured credential helper is available to the child without printing credential values.
Missing host credentials produce a setup refusal. The application never restarts core or changes login configuration to acquire them.

### Contained repositories

FORG-2 refuses Bitbucket REST for any repository with a `CorePilotRepositories.context` result.
That refusal applies to task commands, observers, and presentation, including retained ownership after a contained worker exits.
It happens before runtime provisioning, HTTP requests, or worktree preparation.
The current task's `pilot` flag alone is not sufficient evidence that a repository is regular.

Contained Bitbucket support needs a separately reviewed checked HTTP operation and credential policy.
It is not provided by invoking this regular-host helper outside the container.

## Internal request and response contract

The helper accepts a versioned, bounded request on stdin. Core request data contains no token or authorization header.
Arguments contain only the admitted Bun executable, flags, and helper path.

The request identifies an operation, repository, the admitted credential context, and operation-specific input.
FORG-2 operations are PR lookup, matching-PR discovery, draft creation, readiness update, and commit-bound checks.
The adapter maps these operations to fixed methods and endpoint templates.
There is no caller-supplied URL, header map, arbitrary HTTP method, or executable.

Production HTTP targets only `https://api.bitbucket.org/2.0` on the standard HTTPS port.
Repository names and identifiers are encoded as path segments.
Pagination links must remain inside the admitted repository and expected collection.
Redirects are rejected in this slice. No FORG-2 operation requires the redirecting diff endpoints.

Successful responses contain validated provider data needed by the adapter.
Failures contain stable categories such as missing credentials, permission refused, rate limited, malformed response, incomplete read, or uncertain write.
Raw HTTP bodies, request headers, and fetch exception objects do not enter stderr, logs, snapshots, or task messages.
The helper removes credential values and their constructed authorization representation before returning diagnostics or provider text.

The implementation pins finite request, body-size, page, and total-duration limits in one internal transport owner.
Reaching a bound cannot produce a complete check set or advance feedback delivery.
Timeout and retry policy distinguish read-only operations from potentially submitted writes.

## Admission and uncertain writes

The existing task change guard serializes publication within one task, not every task in a repository.
The Bitbucket implementation also needs a shared publication guard for the repository, source branch, and destination.
Two different task records must not create the same PR concurrently.

Preflight resolves the execution host, repository identity, containment status, runtime, and credential-owner readiness before a publish can push a branch.
Immediately before dispatch, the application revalidates the saved task identity, repository binding, containment status, and core route.
A stale snapshot refuses and requires a new preflight.
An admitted request uses its frozen host, repository, and credential context. A response cannot redirect credential lookup to another repository or account.

The application persists a publication operation identity before dispatch.
The record binds the task, machine, repository, source branch, destination, source commit, credential context, and any saved PR.
It contains no credential values.

| Observation | Durable meaning | Permitted continuation |
| --- | --- | --- |
| Local validation refused before dispatch | No request submitted by this operation. | Fresh validation after the cause is fixed. |
| Request dispatch recorded, reply missing | Submission uncertain. | Read and reconcile the same operation. No new create. |
| Matching PR confirmed | PR identity and source commit verified. | Save that PR and continue through existing task checks. |

Recording before dispatch can conservatively leave an uncertain operation after a crash that occurred before any HTTP request.
An empty PR list does not resolve that uncertainty or prove that an old helper cannot still submit.
No new remote revocation or idempotency capability is assumed.
Recovery uses positive matching evidence. Unresolved cases remain held rather than reissuing create.

The proposed dispatch change is an optional synchronous admission callback in `CoreFiles.exec`.
It runs after awaited route resolution and immediately before `CoreSession.call`, without another await between the callback and the call.
The callback rechecks the owned task and route, then records uncertain dispatch in the same synchronous store transaction.
The existing `CoreSession.call` and `CoreClient.call` path serializes and writes the request without another application-level await.
A thrown admission refusal prevents submission. Existing callers keep their current behavior when no callback is supplied.
This is proposed application code, not an assumed new core capability.

Regressions must hold route resolution pending, change the task or route, and prove that the callback refuses before the core write.
Core errors after attempted submission remain uncertain unless the existing `CoreNotSubmitted` contract positively establishes otherwise.
A core timeout cannot revoke an old helper or prove that the provider received no request.

## Focused acceptance

The public task tests cover publication and checks with independent expected identities.
Transport fixtures supplement those tests and never use real tokens or real Bitbucket writes.

| Scenario | Required observation |
| --- | --- |
| Credential helper returns a supported token | Bearer authentication reaches the fixture. Token values appear in no returned record or diagnostic. |
| Missing, malformed, or rejected credentials | No unauthenticated write or account fallback occurs. A preflight failure precedes branch push. |
| Two configured accounts | Git credential context selects the expected host credential. No Shepherdr override or fallback occurs. |
| Remote machine disconnected or replaced | No local fallback and no write on another machine. |
| Regular local and remote hosts | Same helper protocol and repository binding. No agent or terminal start. |
| Contained or retained contained ownership | Refusal precedes provisioning and other effects. |
| Hostile project dotenv or Bun preload | No repository Bun configuration executes in the helper. Regular Git credential configuration retains its existing authority. |
| Foreign next link, redirect, or repeated page | No credential leaves the fixed API origin. The read cannot pass as complete. |
| Concurrent publication, lost reply, or reopen after a crash | One original operation identity remains. No blind second create. |
| Task identity or route changes during awaited preparation | Refusal before dispatch, with no request on a stale repository binding. |
| Changed source commit or incomplete checks | Readiness cannot use the old or incomplete observation. |

Local verification remains typecheck only. Repository CI owns the authored test suites and builds.
Native qualification on both execution hosts remains distinct from fixture coverage.
FORG-2 implementation does not authorize deployment, credential installation, worker starts, or changes to running installations.
