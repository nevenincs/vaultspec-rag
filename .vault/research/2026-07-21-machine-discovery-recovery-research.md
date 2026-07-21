---
tags:
  - '#research'
  - '#machine-discovery-recovery'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-machine-discovery-recovery-reference]]"
  - "[[2026-06-11-service-status-convergence-adr]]"
  - "[[2026-06-24-service-discovery-schema-adr]]"
  - "[[2026-06-24-service-hardware-singleton-adr]]"
  - "[[2026-06-27-rag-broker-affordances-adr]]"
---

# `machine-discovery-recovery` research: `self-healing owner-authenticated discovery`

The incident reports a healthy daemon becoming undiscoverable after a unit test removed
its storage-specific status record, followed by a poisoned machine pointer and an
apparently live losing process. This research separates established mechanisms from
unverified process attribution and defines the decision boundary for repair.

Primary incident evidence is
`C:/Users/hello/AppData/Local/Temp/claude/copy.markdown:42-131`, with B1 through B6 at
lines 56, 62, 68, 75, 79, and 88.

## Findings

### F1. Publication depends on the wrong record

The heartbeat's early return and `require_existing=True` merge make the canonical
machine pointer depend on a less-authoritative storage-specific file. Once the latter is
deleted, the live owner cannot recreate either record. This is a direct implementation
regression against the accepted independent-publication intent.

### F2. Pointer writes are unauthenticated

Any in-process caller can replace or delete the machine pointer without proving it owns
the OS lock. A fixed temporary filename also creates avoidable collisions. Ownership is
therefore enforced for service startup but not for the record that tells every client
which service to contact.

### F3. Resolution loses definitive evidence

The resolver already obtains the holder PID, then discards it. A live holder combined
with no pointer, a stale pointer, or a different pointer PID is not equivalent to no
service. Collapsing all states to `None` lets compatibility fallback and CLI rendering
misreport a degraded live service as stopped.

### F4. Safe client-side active repair is not currently possible

A client holding only a missing or foreign pointer has no trustworthy port on which to
contact the real daemon. Rewriting from the poisoned record would bless the exact state
that needs rejection. Owner-driven heartbeat repair can converge without this risk.
Active reconcile would first require independently trustworthy address data in the lock
record or another recovery channel.

### F5. Test isolation is a corrective regression, not a new decision

The existing suite fixture preserves ambient path variables and only rearms missing
ones. That violates the accepted machine-singleton isolation rule and the completed
index-backpressure plan. B5 should reopen corrective plan work, not produce another ADR.

### F6. The reported losing-daemon mechanism is unproven

Current startup ordering takes the authoritative lock before Qdrant, watcher, heartbeat,
or maintenance startup. The incident command shown without `--port` selects the stdio
MCP shim, not an HTTP daemon. B6 requires a PID-attributed, real-subprocess reproduction
before source changes; otherwise process-mode confusion is at least as plausible as the
reported mechanism.

## Options considered

### Keep optional-port discovery and patch the heartbeat

This is small, but leaves unauthenticated writes, PID mismatch blindness, misleading
status, and ambiguous fallback. It treats the initiating symptom while retaining the
failed authority model.

### Let clients reconstruct and rewrite the pointer

This can look self-healing but is unsafe with current metadata. A client cannot know the
real owner's port when the pointer is absent or foreign, and must not derive authority
from the record it is repairing.

### Owner-only publication plus typed degraded resolution

This is the recommended direction. The live lock owner independently republishes both
records; every mutation verifies ownership and identity; resolution preserves the
holder/pointer relationship; status renders that service-domain state. A bounded
reconcile initially observes owner-driven convergence and verifies health rather than
inventing identity.

## Recommended decision boundary

The ADR should decide:

- the owner proof required for pointer publish and delete;
- atomic, collision-free pointer replacement;
- heartbeat recreation semantics and the shutdown/tombstone ordering;
- typed discovery states and when storage-directory fallback is legal;
- service-domain status and structured degraded output;
- bounded owner-driven reconcile behavior and the prerequisites for any future active
  repair;
- real-process acceptance tests for heartbeat recovery, foreign writers, mismatch,
  degraded status, and the loser boundary.

The ADR should not redesign job control or index retry policy, infer a B6 fix without a
reproduction, or add a lifecycle action to storage maintenance.

## Acceptance floor

- A live owner repairs a deleted storage-specific record and machine pointer on the next
  heartbeat without restarting.
- A non-holder cannot overwrite or remove the canonical pointer.
- A live holder plus foreign, stale, missing, or invalid pointer is degraded, never
  stopped and never accepted through compatibility fallback.
- Reconcile never terminates a process and never rewrites identity from untrusted data.
- Tests prove both singleton paths are isolated from the operator's managed directory.
- A losing real HTTP daemon exits nonzero before subordinate work; if current code
  already passes, B6 is closed as a regression-test gap rather than a code defect.

## Remaining unknowns

- The exact shutdown/tombstone race to prevent heartbeat resurrection.
- Whether lock metadata should carry a trustworthy recovery port in a later extension.
- The exit-code contract for degraded status.
- PID, argv, and log evidence for the alleged B6 loser.
