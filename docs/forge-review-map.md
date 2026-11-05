> Historical 2.x contract reference from fixed F/P. Old implementation paths refer
> to those Git trees, not this native foundation. See the [migration contract](migration/upstream-v3.1.3.md).

# Forge terminology and review map

The [glossary](../GLOSSARY.md) defines domain terms without implementation details.
This page maps those terms to the reviewed source and the planned changes.
Definitions do not establish that a behavior has been implemented or qualified.

The source checkpoint is `9194764e7957d310e06d64be4c3c4ca3e0746f53`, based on `1b10d73434c203891bcf7cab12e9243b1fd0da93`.
Three design reviewers inspected that checkpoint and the working design documents without running tests or reading credentials.
The table records their combined findings. This documentation does not rename public types or change lifecycle rules.

## Owners and implementation status

| Terms | Source owner | Status and review distinction |
| --- | --- | --- |
| Forge adapter | [CoreForge](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/forge/index.ts), [RepositoryForge](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/forge/types.ts) | GitHub implementation exists. Bitbucket currently refuses. |
| Repository identity, pull request identity | [identity.ts](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/forge/identity.ts), [shared types](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/shared/types.ts) | Saved identity is provider-qualified. Legacy records keep their GitHub meaning. Effective and canonical hostnames can differ. |
| Candidate, source branch, destination, readiness | [CoreTasks](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/tasks.ts), [GitHubForge](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/forge/github.ts) | Readiness binds a candidate and destination. A ready PR, a ready task, and passed checks are separate claims. |
| Check observation | [GitHubForge checks](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/forge/github.ts), [forge tests](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/test/core-forge.test.ts) | The current GitHub adapter can mark a complete empty set green. The task's checks policy rejects zero checks. The Bitbucket contract does not treat empty checks as passed. |
| Approval evidence | [MergeEvidence](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/shared/types.ts), [task evidence](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/tasks.ts) | The existing type describes an integration decision card. Its name does not mean that integration already happened. |
| Publication, uncertain publication | [GitHub publication](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/forge/github.ts), [task publication](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/tasks.ts) | Current code reconciles a lost create reply by lookup. Durable Bitbucket same-operation recovery remains planned. |
| Dependency, hold | [dependencies](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/dependencies.ts), [task queue](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/tasks.ts) | Native dependencies release on merged or closed predecessors. Cleanup and prerequisite code availability remain separate checks. |
| Integration, external merge evidence | [observedMerge](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/tasks.ts), [CoreGit.syncBase](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/git.ts) | Current GitHub observation records merged before base synchronization verifies fetched history. The stronger external-evidence ordering is later FORG work. |
| Cleanup pending, held, complete | [task cleanup](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/tasks.ts), [process ownership](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/task-processes.ts) | Current cleanup can clear cleanupPending while retaining late work. An absent flag is not proof of the planned complete outcome. |
| Conversation, resource ownership | [task cleanup tests](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/test/core-tasks.test.ts), [process tests](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/test/core-task-processes.test.ts) | Later completion proof must verify both retained history and actual removal. Publication persistence tests do not prove full cleanup. |
| Execution host, application host | [CoreFiles](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/files.ts), [CoreSource.route](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/source.ts), [CoreRemotes](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/remote.ts) | Core routes commands. The route does not grant authentication or containment permission. |
| Host-managed authentication | [CoreGit](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/git.ts), [Bitbucket design](forge-bitbucket-transport.md) | GitHub delegates to gh. Bitbucket Git credential lookup and REST compatibility remain unimplemented and unqualified. |
| Secret vault, agent grant | [CoreSecrets](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/secrets.ts), [Mailbox](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/mailbox.ts) | Scoped agent secret access does not authorize background forge authentication. |
| Regular repository, contained repository, checked repository broker | [CorePilotRepositories](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/server/core/pilot-repositories.ts), [checked Git helper](https://github.com/nathanvale/herdr-projects/blob/074dec5ea0bf0a057f520fa50497bf9e1b696ad9/helper/core-pilot-git.ts) | Retained repository restrictions outlive an active worker. The existing broker supports Git and gh, not arbitrary HTTP. |

## Ambiguity cases

| Statement | Distinction required |
| --- | --- |
| The PR is ready. | Leaving draft state, task readiness, and settled checks are different observations. |
| The candidate changed. | A new source commit changes the candidate. A retargeted PR changes the destination even when the commit stays the same. |
| Merge evidence exists. | Approval evidence, a provider merge report, and fetched-history integration evidence establish different facts. |
| Publication failed, retry. | A lost reply can hide a successful create. A second create requires evidence that resolves the original outcome. |
| The task is merged, so cleanup finished. | Late files, later commits, or unconfirmed processes can hold cleanup after integration. |
| The predecessor finished, so its code is available. | Native dependency release does not prove that the dependent checkout contains the accepted prerequisite commit. |
| Use local authentication. | Authentication belongs to the execution host, which can differ from the application host. |
| The space is regular now. | Retained repository containment can still require the checked route. |
| Git authentication works. | A credential suitable for Git may lack REST compatibility or PR permissions. |
| It goes through core, so it is checked. | Core routing and checked-broker validation have different responsibilities. |

## Review boundaries

The bounded FORG-1 repair passed separate Spec and Standards source reviews and local typecheck.
Its authored public-panel regression covers direct Enterprise hosts, canonical links after SSH rewriting, strict task refusal, and Bitbucket refusal.
Tests were not executed locally. CI and native qualification remain separate evidence.

The glossary review adds no implementation task or new acceptance criterion.
The distinctions above explain the existing [forge and completion contract](forge-adapters.md).
Planned behavior belongs to its existing FORG ticket. It is not a new blocker against the bounded Enterprise presentation repair.
