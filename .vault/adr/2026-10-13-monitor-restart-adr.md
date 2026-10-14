---
tags:
  - '#adr'
  - '#monitor-restart'
date: '2026-10-13'
modified: '2026-10-13'
body_schema: 'body-v2'
body_hash: 'sha256:0c8fd437bc9f500f0df8b727fe55cb59151519f904be9f326b2fd5da0b64a4a3'
related:
  - "[[2026-10-02-monitor-lifecycle-adr]]"
  - "[[2026-10-04-monitor-capability-adr]]"
  - "[[2026-10-02-monitor-lifecycle-reference]]"
---

# `monitor-restart` adr: `Restart keeps the monitor through a daemon handoff` | (**status:** `accepted`)

## Problem Statement

The managed monitor is a child of the daemon and exits on parent-pipe EOF (`2026-10-02-monitor-lifecycle-adr`), and every monitor incarnation mints a fresh capability (`2026-10-04-monitor-capability-adr`). A monitor therefore cannot start a stopped service, and any restart kills the open page and invalidates its access link. Operators need to restart the service from the monitor and keep watching it while it comes back. Evidence: `2026-10-02-monitor-lifecycle-reference` and the supervisor in `src/vaultspec_rag/monitor_process.py`.

## Considerations

- The capability boundary stays as accepted: per-incarnation, minted by the monitor, never sent to the backend. The user confirmed on 2026-10-13 that the access link stays.
- The bridge already re-reads service discovery on every call (`src/monitor/server/local-service.ts`), so a surviving monitor follows a new daemon's port and token without change.
- Shutdown currently closes the monitor's stdin, then kills it after five seconds; CLI stop reaps any monitor whose recorded owner is dead (`src/vaultspec_rag/monitor_process.py`). Both would destroy a monitor meant to survive.

## Considered options

- The monitor outlives a restart and the next daemon adopts it. Chosen by the user on 2026-10-13: same process, same capability, so an open page keeps working.
- The new monitor reuses the previous capability from discovery. Rejected: amends the per-incarnation capability and leaves a window where the page is unreachable.
- A fully independent monitor lifecycle. Rejected: reverses coupled start/stop and needs its own lifecycle owner.

## Constraints

Authorization: the user's 2026-10-13 choice of option (a), after the trade-offs above were presented. This is a scoped exception to `2026-10-02-monitor-lifecycle-adr`; every other lifecycle commitment there remains in force.

Restart is a service lifecycle verb, `server restart`, with the same single-envelope and exit-code contract as start and stop. The monitor's lifecycle bridge admits it as an exact operation.

A handoff happens only inside a restart. Before stopping, the daemon writes a handoff line down the monitor's ownership pipe and records the handoff, with a bounded deadline, in the monitor identity record. It then releases the monitor without closing or killing it. Parent-pipe EOF without a preceding handoff line still closes the monitor, and so does a handoff that is not adopted before its deadline.

The next daemon adopts only a monitor whose recorded process and start time verify, whose handoff is unexpired, whose backend port matches its own, and whose recorded executable SHA256 equals the digest of the executable this daemon would itself launch for the running release, so a restart across an upgrade or onto a replaced binary never adopts. The handoff record carries the executable path and that digest, taken when the monitor was spawned. It records itself as the owner and publishes the monitor's existing port and access link. Otherwise it reaps the handed-off monitor and spawns a fresh one as today.

An adopted monitor has no ownership pipe. It closes when the identity record no longer names a live owner, when the record names a different monitor process, or when an unadopted handoff expires. `server stop`, daemon crash and orphan cleanup end it exactly as they end a spawned monitor, except that they leave a verified, unexpired handoff alone; that monitor closes itself when its handoff expires unadopted, and a later stop reaps anything left.

The access link is held only where it already is: the monitor's memory, protected same-user discovery, and the identity record in the same protected managed status directory. It is never logged.

## Implementation

We will add the handoff and adoption to the existing supervisor and a `server restart` verb that hands off, stops while preserving the handoff, and starts. The monitor gains a handoff mode on its ownership pipe and an owner watch after adoption. The frontend replaces Start with Restart while the service is up, and shows a restarting state until the service answers again. Hypotheses that may change within the constraints: the handoff line spelling, the deadline length, the owner-watch interval, and the restart verb composing the canonical stop and start verbs as subprocesses.

## Rationale

Adoption keeps the one process that holds the capability, so the open page needs no new link and the capability ruling is untouched. The pipe still decides the common case, and the handoff line makes the exception explicit rather than inferred from timing.

## Consequences

Operators restart from the monitor and keep the same page. A monitor can briefly outlive its daemon during a restart, bounded by the handoff deadline. An adopted monitor detects owner death by polling, not by pipe EOF, so it can outlive a crashed owner by up to one poll interval. Reconsider if the monitor gains an independent lifecycle or a multi-user mode.
