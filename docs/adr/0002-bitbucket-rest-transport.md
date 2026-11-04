---
status: proposed
---

# Bitbucket REST transport belongs to the forge adapter

## Context and problem

Shepherdr needs Bitbucket PR operations through the same task contract as GitHub.
The earlier plan depended on the private Monash `bb` CLI.
That package has no verified standalone distribution contract for other Shepherdr users.

Nathan selected direct REST transport inside Shepherdr on 4 November 2026.
That dependency choice is settled. This ADR remains proposed for maintainer review of the implementation contract.

## Decision drivers

- Installation works without a Monash plugin, account, endpoint configuration, or credential store.
- GitHub behavior and existing execution boundaries remain compatible.
- PR identity, complete checks, and uncertain writes have explicit meanings.
- Shared source has verified reuse terms and attribution.

## Considered options

| Option | Portable installation | Execution boundaries | Workflow guarantees | Source reuse |
| --- | --- | --- | --- | --- |
| Depend on the private bb CLI | No verified public distribution | Adds another executable and credential route | Depends on its evolving output contract | No copying, but creates a private dependency |
| Embed the existing CLI source | Removes the executable prerequisite | Imports unrelated credential assumptions | Still requires adapter-specific reconciliation | Reuse permission not established |
| Implement REST inside the adapter | Ships with Shepherdr | Uses an explicitly admitted route | Adapter owns interpretation and reconciliation | Official API contracts support an independent implementation |

## Decision

Use direct Bitbucket Cloud REST transport inside the forge module.
Keep GitHub on its existing gh transport.
Keep local Git, approval, durable delivery, and resource cleanup with their existing owners.

The adapter implements the shared `RepositoryForge` contract.
HTTP details remain private to the Bitbucket implementation.
The transport does not create a general HTTP proxy or borrow another worker's credential grant.

This choice removes the private distribution dependency. It makes Shepherdr responsible for authentication delivery, response validation, pagination, and uncertain writes.
The bounded requirements are in the [adapter reference](../forge-adapter-reference.md).

## Licence inspection

The installed `monash-tools` 1.6.4 package contains no discovered LICENSE, COPYING, or NOTICE file.
Its Bitbucket package declares `private: true` and no licence field.
The inspected `monash-plugins` tree at `9ee5fcea82af9b0feff83f4335f6db6e367d3d6b` has no such licence file either.

These observations do not establish permission to redistribute its source.
No source is copied by this documentation change.
Implementation proceeds from official API contracts unless reuse permission and attribution requirements are established for specific files.

## Consequences

- Shepherdr users do not need to install the Monash tooling.
- Shepherdr maintains its own Bitbucket transport and provider tests.
- The private tooling can evolve independently.
- Native Bitbucket merge remains refused when exact source-commit enforcement is unavailable.
- External merge observation and later completion remain separate from requesting a merge.

The credential-reference configuration and admitted execution route need concrete implementation review.
No new setting, launcher, credential store, or remote-execution fallback is implied by this decision.

## Confirmation

FORG-2 proves publication and checks through public task entry points.
FORG-3 proves paginated feedback and commit-bound base health.
FORG-4 proves external merge evidence without a second merge request.
FORG-7 records required CI, independent review, and separately authorized native qualification.

The dependency graph and existing holds remain unchanged.
Neither documentation nor a successful HTTP fixture admits the preceding GitHub extraction or authorizes deployment.

Revisit the native merge refusal only when official provider semantics establish an enforceable source-commit condition.
Revisit source reuse only when the relevant permission is documented.

## References

- [Forge execution contract](../forge-adapters.md).
- [Bitbucket authentication and pagination](https://developer.atlassian.com/cloud/bitbucket/rest/intro/).
- [Bitbucket pull request API](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/).
