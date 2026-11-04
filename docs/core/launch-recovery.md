# Proposed human operator recovery

This candidate is not an activated recovery and grants no host-reboot authority.
The [proposed decision](../adr/0003-operator-boot-fenced-launch-recovery.md) records
its evidence, limitations and rollback boundary.

Use only for an exact uncertain launch of an existing regular local conversation
with a retained native session. Preserve its conversation, worktree, current
native session, model, provider, effort and speed. Remote execution and systems
without the supported macOS kernel/platform identity reader refuse. Application
boot IDs, uptime, error text and empty inventories are not reboot proof.

The human CLI uses the existing OS-owned private operator socket. HTTP actions
and authenticated agent commands expose no recovery operation. These commands
accept no caller-supplied boot or host identity:

```sh
shepherdr recover-launch status CHAT LAUNCH --home PATH
shepherdr recover-launch arm CHAT LAUNCH --home PATH
```

Replace `CHAT`, `LAUNCH` and `PATH` with independently verified exact identities.
Keep the pre-arm private backup and candidate revision. `arm` creates a durable
dispatch hold, and starts or stops nothing. If any sender/action is in progress,
wait for it to settle and inspect the same identity before retrying.

A reboot affects the whole host and every shared service. Obtain separate
whole-host authorization and coordinate recovery before using the host's normal
reboot controls. No command here performs, requests or schedules a reboot.
Stopping only the application, core or holder does not satisfy this protocol.

After a separately authorized full host reboot, connect the application to its
original core and installation. Explicitly inspect and settle the same launch:

```sh
shepherdr recover-launch status CHAT LAUNCH --home PATH
shepherdr recover-launch settle CHAT LAUNCH --home PATH
```

Settlement requires a different kernel boot on the same hardware and unchanged
native binding. It records that old execution ended and revokes its grant.
It preserves the actual current agent record and any prior effects; it does not
declare that no submission occurred. Messages already submitted stay uncertain.
All dispatch for the chat remains held.

Review what may already have happened in the retained conversation and worktree.
Release only with an explicit disposition of the saved queue:

```sh
shepherdr recover-launch resume CHAT LAUNCH --cancel-queued --home PATH
```

This cancels queued messages with durable notices and clears their provider retry
intent. It leaves submitted messages uncertain and starts no process. Old task
queue work does not restart automatically. Use a fresh ordinary human send or
Restart action to continue the retained native conversation. The first recovered
continuation preserves its recorded CLI, deployment, effort and speed; it cannot
be used to switch that binding. Independently verify the resulting native
session and actual model/provider before reporting recovery as complete.

On a lost reply, ask `status` for the same chat and launch. Exact repeated arm,
settle and resume operations reconcile without duplicating effects. A refused
operation does not release the hold. Do not clear records or infer safety from
missing terminals.

Older versions do not understand recovery state. Do not downgrade while armed
or settled/held, and do not restore the pre-arm backup as a process-cleanup
shortcut. Complete the supported hold and establish an ordinary safe native
identity before considering a separately reviewed code rollback.
