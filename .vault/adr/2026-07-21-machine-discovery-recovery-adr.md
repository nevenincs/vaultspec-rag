---
tags:
  - '#adr'
  - '#machine-discovery-recovery'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:ea820b438c3048df276f21e303a12dc60b020b34140a2eb7b4e3f810d6a520fd'
related:
  - "[[2026-07-21-machine-discovery-recovery-research]]"
  - "[[2026-07-21-machine-discovery-recovery-reference]]"
  - "[[2026-06-11-service-status-convergence-adr]]"
  - "[[2026-06-24-service-discovery-schema-adr]]"
  - "[[2026-06-24-service-hardware-singleton-adr]]"
  - "[[2026-06-27-rag-broker-affordances-adr]]"
  - "[[2026-06-30-mcp-conformance-adr]]"
  - '[[2026-07-21-machine-discovery-recovery-s01-test-isolation-audit]]'
---

# `machine-discovery-recovery` adr: `owner-authenticated, self-healing service discovery` | (**status:** `accepted`)

## Problem Statement

The machine-singleton service has two discovery views: a machine-global pointer used to
locate the resident service and a storage-specific status record used for operator detail.
The live OS lock is the authority for service ownership, but current publication and
resolution do not preserve that authority consistently.

A heartbeat stops publishing both views when the storage-specific record is missing.
Machine-pointer writes and deletion do not prove that the caller owns the singleton lock.
Resolution detects a live lock holder but does not require the pointer PID to match it, and
it collapses missing, malformed, stale, or foreign pointers to ordinary absence. The
canonical status surface can consequently report `stopped` while a live owner exists.

The incident also exposed a test-isolation regression and alleged that a losing daemon
continued subordinate work. The isolation defect is established. The losing-daemon
mechanism is not: current startup ordering acquires the singleton lock before components
start, and the reported command does not establish that the observed process was an HTTP
daemon. This ADR decides discovery ownership and recovery, while bounding B5 as corrective
work and B6 as reproduction-first work.

## Considerations

- The OS-held machine lock remains the only authority for ownership and permission to start
  a resident service.
- The machine pointer is the authoritative address record once its identity matches the live
  holder; it is not an independent ownership primitive.
- The storage-specific record is an operator and compatibility view. Its deletion or
  corruption must not prevent canonical publication.
- A PID in a file is evidence, not proof that the current process owns the OS lock. Pointer
  mutation needs a process-local capability derived from successful lock acquisition.
- A client cannot safely reconstruct a missing or foreign pointer because it has no
  independently trustworthy owner address. Repair must initially be owner-driven.
- A live holder with an unusable pointer is materially different from no holder. The
  service-domain status model must preserve that distinction for every adapter.
- Compatibility with an older non-locking service may still require the storage-specific
  record, but that record must never override evidence from a live machine lock.
- Self-healing publication must be ordered with shutdown so a late heartbeat cannot
  recreate discovery after intentional teardown.
- B5 is already governed by the managed-singleton isolation rule. B6 source changes require
  PID-attributed real-process evidence because static inspection contradicts the allegation.

## Considered options

- **Patch only the heartbeat early return.** Rejected: it restores one recovery path but
  leaves unauthenticated mutation, PID-mismatch acceptance, ambiguous fallback, and false
  stopped outcomes.
- **Let clients reconstruct or rewrite machine discovery.** Rejected: a client cannot derive
  the real owner's port without trusting the corrupt record.
- **Put a recovery address in lock metadata and permit active client repair.** Deferred: it
  changes the lock contract and requires a trustworthy address and generation model.
- **Owner-authenticated publication, typed resolution, and bounded observation.** Chosen: the
  retained owner republishes independently, consumers preserve degraded evidence, and
  reconcile waits for owner repair without inventing identity.

## Constraints

- Lock acquisition, owner proof, atomic replacement, and holder probing retain equivalent
  semantics on Windows and POSIX.
- Pointer ownership cannot be established by comparing file PIDs alone. Mutations require
  the active process-local lease or equivalent retained capability, plus payload agreement.
- The accepted discovery schema continues to govern versioning, timestamps, heartbeat
  cadence, and staleness fields.
- Publication cannot weaken the one-service-per-machine rule or let a pointer gate startup.
- Status-directory compatibility cannot mask a live-holder discovery fault.
- Reconcile is bounded and non-destructive: it cannot terminate, reclaim, remove a pointer,
  or publish identity from client-observed data.
- Shutdown quiesces heartbeat publication before deleting discovery and retains ownership
  until owner-only cleanup completes.
- Tests force both singleton paths beneath a session-owned temporary root regardless of
  ambient variables, and fail before mutation or process control if either resolves to the
  operator's managed root.
- Acceptance coverage uses production entry points, real files, real OS locks, and real
  subprocesses without fakes, mocks, patches, skips, or expected failures.
- The singleton, discovery-schema, broker, MCP, and canonical-status parent features are
  stable. This decision changes their convergence and error classification, not their
  ownership or transport foundations.

## Implementation

**D1 — Machine-pointer mutation is owner-only.** The machine-lock domain owns publication
and deletion primitives. A caller may mutate the pointer only while presenting the active
lease or equivalent retained capability created by successful singleton acquisition. The
primitive verifies that the current process still holds that lease and that a published
payload names the same PID. A holder probe or PID read is insufficient authorization.
Publication uses a unique temporary file in the destination directory followed by atomic
replacement. Shutdown deletes through the same primitive while the lease remains held.

**D2 — Heartbeat publication is independent and self-healing.** Each heartbeat constructs
one canonical snapshot from daemon-owned runtime identity and configuration rather than
requiring an existing storage-specific record. While ownership remains valid, it may
recreate an invalid or missing operator record and publish the machine pointer from the same
snapshot. Failure to read or merge the operator view cannot suppress pointer publication.
Shutdown first marks publication as stopping, quiesces and joins heartbeat work, performs
owner-only cleanup, and releases the singleton lease last. Deleting a status file is no
longer interpreted as a stop request.

**D3 — Discovery returns a typed service-domain resolution.** Resolution preserves at least
the live holder PID, pointer PID, candidate port, source, freshness, and reason. Required
states are `absent`, `ready`, `pointer_missing`, `pointer_invalid`, `pointer_stale`, and
`pointer_foreign_pid`; transport readiness is a separate health observation. A fresh,
schema-valid pointer is ready only when its PID matches the live holder. With a live holder,
every unusable-pointer state is degraded: it is never collapsed to `None`, reported as
stopped, or replaced by a storage-specific candidate.

**D4 — Compatibility fallback is legal only without a live holder.** If no machine lock is
held, a storage-specific record may be considered solely as a labelled legacy candidate. It
must pass schema, freshness, PID-liveness, and service-identity checks before yielding an
address. It cannot mutate the machine pointer or imply lock ownership. This path is never
consulted when a live holder exists and remains visible in structured output as a
compatibility source.

**D5 — Canonical status and reconcile consume the same resolution.** The service-domain
status model renders `ready`, `degraded`, and `absent` distinctly and includes holder and
pointer evidence with an actionable reason. CLI, HTTP, and MCP adapters consume that model.
Service-dependent operations fail fast on degraded resolution; read-only status returns the
complete observation. Reconcile performs bounded re-resolution across owner heartbeat
opportunities and succeeds only after holder PID, pointer PID, freshness, address, token
identity, and health agree. On timeout it returns the remaining degraded evidence. It never
mutates discovery or terminates a process.

**D6 — B5 is corrective; B6 is reproduction-only until disproved.** Singleton-path
isolation becomes unconditional for the test session, ambient values return only after the
session, cached configuration resets at each transition, and a fail-closed guard precedes
singleton writes or process control. For B6, the first executable artifact holds an isolated
machine lock and starts a competing real HTTP daemon. The loser must exit nonzero within a
bound and create no listener, Qdrant child identity, pointer mutation, watcher, or maintenance
activity. If current code passes, B6 closes as a missing regression test. Production
lifecycle changes require a failed reproduction identifying a concrete boundary defect.

## Rationale

The approved research and reference establish an authority-convergence defect: ownership is
correctly represented by the OS lock, but publication, resolution, and status discard or
bypass that evidence. Extending the retained owner capability to pointer mutation is the
smallest trustworthy authorization model. Independent heartbeat snapshots restore
convergence without granting repair authority to clients. Typed resolution retains
definitive evidence that optional-port discovery loses, and bounded observation lets the
owner repair itself without adding a destructive control path.

This ADR supersedes no prior record wholesale. It extends singleton lock ownership to
discovery mutation, applies the discovery schema to independently recreated views, makes the
broker pointer owner-authenticated, and extends canonical status with degraded discovery.
It narrowly replaces the MCP-conformance SD4 classification that treated every invalidated
stale pointer as absence: when a live holder exists, missing, stale, invalid, or foreign
pointer state is degraded. The remainder of MCP conformance stays accepted.

## Consequences

- A live owner repairs deleted or corrupted discovery views on the next successful
  heartbeat without restart.
- A non-holder cannot overwrite or remove canonical discovery even if it reproduces the
  owner PID.
- Operators and adapters distinguish no service from a live but undiscoverable service.
- Recovery is bounded by heartbeat convergence. A wedged owner may remain degraded; clients
  expose that state but do not guess an address or kill a process.
- The lock API becomes explicit because pointer mutation requires a retained ownership
  capability.
- Shutdown ordering becomes load-bearing and requires real race coverage.
- Explicit legacy fallback preserves temporary compatibility complexity without masking
  corruption under a live singleton.
- Status consumers migrate from optional-port semantics to typed resolution.
- B5 may expose tests that depended on ambient managed state; those tests must be corrected.
- B6 may produce no production-code change, which is correct if the real-process contract
  already holds.
- Future active repair requires a separately approved trustworthy recovery-address contract.
