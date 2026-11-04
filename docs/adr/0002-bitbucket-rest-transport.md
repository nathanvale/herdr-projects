---
status: proposed
---

# Bitbucket REST transport belongs to the forge adapter

## Context and problem

Shepherdr needs Bitbucket PR operations through the same task contract as GitHub.
GitHub already delegates its provider operations and authentication to gh.
Bitbucket needs a portable transport without adding an organization-specific runtime dependency.

The selected direction is direct REST transport inside Shepherdr.
This ADR remains proposed for maintainer review of the implementation contract.

## Decision drivers

- Installation works without an organization-specific plugin, fixed account, or custom credential store.
- GitHub behavior and existing execution boundaries remain compatible.
- PR identity, complete checks, and uncertain writes have explicit meanings.
- Shared source has verified reuse terms and attribution.

## Considered options

| Option | Portable installation | Execution boundaries | Workflow guarantees | Source reuse |
| --- | --- | --- | --- | --- |
| Depend on an additional Bitbucket CLI | Adds a distribution prerequisite | Adds another executable and credential route | Depends on its output contract | Reuses an external executable |
| Embed a third-party CLI | Removes the executable prerequisite | Imports another credential implementation | Still requires adapter-specific reconciliation | Requires compatible licence terms and attribution |
| Implement REST inside the adapter | Ships with Shepherdr | Uses an explicitly admitted route | Adapter owns interpretation and reconciliation | Official API contracts support an independent implementation |

## Decision

Use direct Bitbucket Cloud REST transport inside the forge module.
Keep GitHub on its existing gh transport.
Keep local Git, approval, durable delivery, and resource cleanup with their existing owners.

The adapter implements the shared `RepositoryForge` contract.
HTTP details remain private to the Bitbucket implementation.
The transport does not create a general HTTP proxy or borrow another worker's credential grant.

This choice avoids an additional CLI dependency. It makes Shepherdr responsible for authentication delivery, response validation, pagination, and uncertain writes.
The bounded requirements are in the [adapter reference](../forge-adapter-reference.md).

## Source licensing

This documentation change includes no third-party implementation source.
The Bitbucket implementation follows official API contracts.
Any future source reuse requires compatible licence terms and preserved attribution before the code enters the package.

## Consequences

- Shepherdr users do not need another provider CLI.
- Shepherdr maintains its own Bitbucket transport and provider tests.
- Existing host credential tools remain independent of Shepherdr.
- Native Bitbucket merge remains refused when exact source-commit enforcement is unavailable.
- External merge observation and later completion remain separate from requesting a merge.

The [authentication and execution design](../forge-bitbucket-transport.md) specifies host-managed Git credential lookup and a helper on the repository's execution host.
It selects existing core machine execution and immutable helper provisioning. It refuses contained execution until a checked REST operation exists.
The proposed helper needs implementation and qualification. No new app authentication settings are added. No live configuration or remote-execution fallback is enabled by this decision.

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
