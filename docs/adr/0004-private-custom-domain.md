---
status: proposed
---

# Authenticate private custom HTTPS by the Tailscale socket peer

## Context and problem

Native v3 accepts its own Tailscale DNS name and trusted Serve identity headers.
A custom DNS alias does not satisfy its certificate, Host or Origin contracts.
The user authorized an isolated implementation and proof for a private custom
domain, preserving owner-only access and the existing runtime/hostname owner.

## Decision drivers

- Keep the application private and preserve native defaults and owner identity.
- Do not trust browser-supplied identity or rewrite browser Origin to bypass checks.
- Reuse native request/WebSocket handlers and avoid another credential store.
- Prove admission independently before any DNS or runtime cutover.

## Options and tradeoffs

| Option | Private access and identity | Compatibility | Operational cost | Proof |
| --- | --- | --- | --- | --- |
| DNS alias to Serve | Cannot satisfy custom TLS/Host; no usable custom origin | No source change | Low | Refused by native contracts |
| Public tunnel and a new proxy identity | Changes the chosen network/identity model | Requires a separate trusted proxy contract | Tunnel, access policy and proxy | Different acceptance scope |
| Private TLS listener and Tailscale whois | Socket identity, exact Host/Origin, owner only | Explicit opt-in; native paths remain | Custom certificate/DNS owner and reserved port | Isolated TLS process and real Tailscale qualification |

## Proposed decision

Use a private TLS listener authenticated by the local daemon's `whois` result
for the actual socket peer. Both transports call the same application handlers.
Caller headers cannot activate the additional gate path. Bind only a validated
local Tailscale address. Fail closed on identity uncertainty. Tagged devices
cannot claim human ownership.

The user approved implementing and proving this scope. This record remains
proposed for maintainer review; it does not approve deployment or DNS cutover.

## Consequences

Existing Serve, loopback access, shared settings and conversations are unchanged
when the option is absent. No new package is needed. A separate certificate
issuer/renewal owner and private DNS answer are required. A busy Serve port
must be resolved before activation. Daemon lookup failure blocks custom access.
Device ownership does not identify a particular OS user on an owned device.
Completed grants are not cached; concurrent lookups alone coalesce.

## Confirmation

`service/private-domain.test.ts` exercises actual TLS and WebSocket admission
with fixture daemon responses. CI's negative control removes owner refusal;
the other-identity request must fail the regression before restoring GREEN.
The read-only native proof imports no application scheduler or core and checks
the real daemon, exact interface, permitted owner and tagged-node refusal.
Trusted browser certificates, DNS, full application activation and rollback of
an eventual cutover remain separate qualification obligations.

See [configuration and qualification](../private-domain.md).
