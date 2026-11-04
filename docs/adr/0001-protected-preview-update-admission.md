---
status: proposed
---

# Protected preview update admission belongs to the running application

## Context and Problem

The ordinary launcher stops the web application while core workers continue.
Application startup closes interrupted permissions and queues a notice to their
worker. A process inventory alone therefore cannot establish that a preview
update has no worker effects. New permissions, deliveries and launches can race
an external inspection.

Nathan selected refusal while any worker is live or unconfirmed, leaving the
current application running. This settles the policy. The protocol below remains
a maintainer-review proposal; it changes no ordinary start/stop default.

## Decision Drivers

- Refuse without cancelling permissions, sending prompts or signaling live work.
- Exclude application-owned starts and sends while checking current core state.
- Preserve existing installations and ordinary lifecycle semantics.
- Use the existing private operator socket and supported core interfaces.

## Considered Options

| Option | Worker effects | Race handling | Compatibility | Existing interfaces |
| --- | --- | --- | --- | --- |
| External read-only preflight, then ordinary stop | Cannot prevent startup cleanup | Inspection can become stale | Ordinary commands unchanged | Reuses status/store reads |
| Change ordinary stop/start to require idle work | Can refuse before stop | Still needs application-owned admission | Breaks established behavior | Broadens every lifecycle call |
| Opt-in application-owned protected stop and startup recheck | Refuses pending work without cleanup | Blocks app admission before fresh observation | Ordinary commands unchanged; older operators refuse | Reuses private socket and `terminal.list(all=true)` |

## Decision

Propose `--idle-only` on both stop and start. Protected stop targets the exact
running boot over its OS-owned private operator socket. Before closing admission,
it refuses cached live terminals, active public actions and retained pending work.
It then closes application admission, obtains current core inventory including
finished terminals, and checks again. The observation has a three-second RPC
budget within the operator request's five-second lifetime. Expiry or disconnect
revokes the request; a late inventory response cannot regain shutdown authority.
On refusal it releases only its own temporary admission hold. It cannot reopen
admission closed by an independent ordinary shutdown. Final checks and the
synchronous shutdown callback have no intervening await. Once admitted, the
running application owns its shutdown, including when the acknowledgement is
lost. The launcher never falls back to an ordinary signal.

Protected startup checks current core and persisted state before permission
cleanup, subscriptions or delivery. It requires an explicitly selected, already
reachable core. It does not start core to obtain a result. An already-running
application is not replaced by the start command.

## Consequences and Limits

The guard is conservative: all non-finished selected-core terminals, unmatched
retained worker identities, pending permissions/messages/launches, in-flight
commands, unfinished tasks, automations and Autopilot can refuse. It neither
resolves unknown launches nor changes holds. A stale home is not made safe by
clearing records or an empty terminal list.

The protocol assumes one application owner per home. Core offers no lease that
fences independent core clients or external SQLite writers; this proposal does
not guarantee safety against them. The first adoption from an older running
application cannot use a protocol that old application lacks. It must wait for
an independently authorized safe boundary, without falling back silently.

A lost stop acknowledgement requires inspecting the same app's status before
retrying. Stopping a used candidate does not make downgrading Azure-bound state
safe. No running preview update is authorized by this proposal.

## Confirmation

`test/core-protected-update.test.ts` crosses the launcher executable, private
operator socket and server startup entry point using temporary state and fake
core inventory. It verifies retained state on refusal, boot identity, delayed
permission/worker arrival, admission while public actions await, startup before
cleanup, idle shutdown ownership, expired observation, concurrent ordinary shutdown
and final validation/dispatch ordering. CI removes live-terminal refusal, request
lifetime binding and independent-shutdown protection to prove the regressions
detect unsafe stops, then restores the guards and runs the normal suite. Native
acceptance remains separately authorized and unperformed.

## References

- [Configuration, update limits and native acceptance](../azure-foundry.md)
- [Manual lifecycle controls](../core/start.md)
