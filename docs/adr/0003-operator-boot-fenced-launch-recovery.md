---
status: proposed
---

# Settle uncertain local execution across an operator-observed host reboot

## Context and Problem

An uncertain `terminal.run` can leave no terminal to reconcile. Core 0.1.16 and
the current 0.1.18 schema expose neither durable caller launch receipts nor
an operation that proves cancellation of that exact request. `spawn_failed`
also covers failures cloning PTY descriptors after a child starts. The failed
terminal record and its scope can be removed before shutdown; stopping core
does not establish cleanup of that unretained child. An empty inventory,
application restart, error text or changed application boot ID is insufficient.

Nathan authorized preparation of a bounded application remedy, retaining the
existing conversations and worktrees. That does not authorize activation or a
host reboot. This decision and its implementation remain proposed for review.

## Decision Drivers

- Prevent simultaneous old and replacement execution.
- Preserve uncertainty about past effects and submitted messages.
- Preserve the actual native conversation, provider, model, effort and speed.
- Keep recovery human-operated and isolated from HTTP and agent commands.
- Use existing application ownership and persistence; change no third-party core.

## Considered Options

| Option | Duplicate prevention | Past effects | Conversation | Authority | Dependencies |
| --- | --- | --- | --- | --- | --- |
| Retain the hold until a matching terminal appears | Preserves the current guard | Remain unknown | Preserved but blocked | Existing controls | No new mechanism; may never resolve |
| Release on error, reconnect or empty inventory | Cannot exclude unretained execution | Falsely implies non-submission | Can duplicate it | Broadens ordinary failure handling | Assumes an unsupported core guarantee |
| Explicit operator hold and verified different host boot | Ends old host execution before replacement admission | Remain unknown | Retains current bindings | Private operator only | macOS kernel/platform identity and separately authorized reboot |

## Decision

Propose the third option for a regular conversation executing on the application
host. A dedicated module reads macOS `kern.bootsessionuuid` and the platform
UUID using fixed native executables, bounded to one second each. It hashes the
platform UUID before persistence. It accepts no caller, environment or HTTP
override. Other operating systems and remote execution refuse.

`recover-launch arm CHAT LAUNCH` binds the exact application installation,
core-local machine, hardware identity, kernel boot, launch claim and native
conversation/provider fields. It refuses an in-flight application sender or
action and durably holds the chat's dispatch. Existing launch admission and its
final check enforce the hold, including after reload. A late legitimate terminal
confirmation or transcript observation is retained; the prior agent snapshot is
not restored. A changed native session/provider/host refuses recovery.

`settle` requires a different kernel boot on that same hardware. A full reboot
ends the old sender and its processes, including a child core failed to retain.
The new state is `execution-ended-after-host-reboot`, never `never-submitted`.
Submitted messages and past effects remain unknown. Core startup does not replay
`terminal.run`; non-kept terminals whose holders are gone become finished.

Grants and application records occupy separate SQLite files. Settlement revokes
only the exact old grant first, then commits application state. A crash between
those steps leaves an armed durable hold and can repeat exact revocation. This
is safe ordering, not a claim of cross-store atomicity.

`resume CHAT LAUNCH --cancel-queued` explicitly cancels the queued messages with
durable notices, clears provider retry intent and releases the dispatch hold.
It does not replay uncertain messages or start a process. Automatic task queue
starts remain blocked for this ended execution. A later ordinary human send or
restart may continue the same native session; the first continuation keeps its
recorded agent/model/effort/speed and provider. Restart validates and pins that
selection during preflight, before browser, checkout or task-binding changes,
and validates again at dispatch. The new record retains recovery provenance.
If native resume cannot find that session, failed-start handling reports a hold
with the same binding; it cannot clear the session and silently dispatch a
fresh conversation. Ordinary missing-session fallback remains unchanged for
conversations without that provenance. No ordinary default changes.

Recovery alone uses a newline-framed private operator request. Its caller keeps
the write side open until the response; peer FIN/close while host observation
awaits aborts authority. EOF-framed recovery requests refuse before observation.
Secret and protected-stop clients retain their existing EOF protocol. Each
connection admits at most one bounded request. Request expiry and disconnect
are rechecked after host observation and immediately before durable mutation.

## Consequences and Limits

- Positive: no unsupported inference about non-submission; no fabricated terminal
  and no raw database recovery are needed.
- Positive: refusal leaves state intact; exact repeated operator operations are
  idempotent, and a lost reply is reconciled with status for that same launch.
- Negative: a reboot interrupts every process on the execution host. Arming does
  not authorize, request or perform it. The operator must obtain separate
  whole-host authority and coordinate shared services first.
- Negative: the boot/platform reader needs native macOS acceptance. Tests with
  an injected OS adapter prove the application protocol, not an actual reboot.
- Neutral: one application owner per home remains the concurrency boundary.
  Copied homes on different hardware refuse. VM snapshot restoration, malicious
  OS identity substitution and other independent application writers are outside
  this bounded contract.

Retain a verified private pre-arm backup. Older application versions do not
understand the new recovery hold/state; an armed or settled hold prohibits a
transparent downgrade or deleting recovery records. Before a code rollback,
finish the hold through the supported operator route and independently establish
an ordinary safe native identity. Restoring an earlier database is not proof
that an old process cannot run. Existing protected-update admission continues to
refuse unknown work; this proposal supplies no bypass.

## Confirmation

`test/core-operator.test.ts` crosses the real private socket, temporary application
stores, actual launch admission and task/coordinator actions, with a core protocol
double and injected internal OS adapter. An independent reader verifies persisted
outcomes. Cases cover same-boot refusal, reload, changed host/launch/session/
provider, active senders, final dispatch fencing, interrupted grant revocation,
late confirmation, explicit queue disposition and no automatic native launch.
Real socket cases close a framed peer during a blocked host observation and
independently verify unchanged SQLite state. Public Restart cases preserve
bindings on selection refusal; native missing-session cases permit no second
dispatch from a recovered continuation.
Subprocess and HTTP cases check human routing and absence of a recovery action.
CI owns tests, sensitivity controls and builds; only typecheck runs locally.

Activation, actual host reboot and same-session native acceptance remain unrun
and require their respective authority. Revisit this temporary remedy when core
offers durable exact-launch reconciliation and cleanup receipts, or another
platform is requested. See the [operator runbook](../core/launch-recovery.md).

## References

- [Existing launch admission](../azure-foundry.md#launch-admission-and-recovery-boundaries).
- [Core 0.1.16 holder spawn](https://github.com/herdrdev/herdr-core/blob/v0.1.16/crates/herdr-core/src/holder.rs#L336).
- [Core 0.1.16 failure record removal](https://github.com/herdrdev/herdr-core/blob/v0.1.16/crates/herdr-core/src/api/run.rs#L165).
- [Core 0.1.18 schema](https://github.com/herdrdev/herdr-core/blob/v0.1.18/schema/hc.openrpc.json).
