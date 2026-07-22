---
tags:
  - '#reference'
  - '#machine-discovery-recovery'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-06-11-service-status-convergence-adr]]"
  - "[[2026-06-24-service-discovery-schema-adr]]"
  - "[[2026-06-24-service-hardware-singleton-adr]]"
  - "[[2026-06-27-rag-broker-affordances-adr]]"
---

# `machine-discovery-recovery` reference: `ownership, resolution, and recovery seams`

This reference maps incident items B1 through B6 to the current dirty working tree. It
is descriptive, not proof that the reported process history is correct. No daemon was
started, storage was touched, or test was run during this trace.

## Current authority model

The accepted architecture makes the OS-held machine lock authoritative for the one live
service and the machine discovery pointer the canonical address record. The
storage-specific status file is an operator view, not the ownership primitive. Current
code only partially implements that separation:

- `src/vaultspec_rag/server/_lifecycle.py:139-244` builds a heartbeat from the
  storage-specific status file. If that file is missing at line 152, the tick returns;
  the `require_existing=True` merge at line 237 and machine-pointer publication at line
  244 are never reached.
- `src/vaultspec_rag/server/_lifecycle.py:247-264` publishes through a shared
  `service.tmp` and `os.replace` without checking the machine-lock holder or matching
  the payload PID to that holder.
- `src/vaultspec_rag/server/_lifecycle.py:93-137` also deletes the machine pointer
  without an ownership check.
- `src/vaultspec_rag/serviceclient/_discovery.py:349-380` obtains the live holder PID,
  reduces it to a boolean, and never compares it with the pointer PID. Missing, stale,
  malformed, and foreign pointers therefore collapse to absence.
- `src/vaultspec_rag/serviceclient/_discovery.py:383-410` may then fall back to a
  storage-specific record even though a live machine holder made pointer corruption a
  definitive degraded condition.
- `src/vaultspec_rag/cli/_status_render.py:800-885` reads the storage-specific record
  first and emits stopped when it is absent. It cannot render a live-holder discovery
  fault distinctly.

## Safe implementation seams

### Owner-checked publication

Centralize machine-pointer publish and delete beside the machine lock in
`src/vaultspec_rag/_machine_lock.py`. A mutating operation must prove
`machine_lock_live_holder() == os.getpid()` and, for publication, that the payload PID
equals that holder. Use a per-process, per-operation unique temporary file followed by
atomic replacement. Route heartbeat and shutdown through this primitive.

Do not reuse the looser storage-status merge policy directly. Its same-port
launcher-to-daemon PID preservation serves a different compatibility contract.

### Independent heartbeat repair

Refactor `_heartbeat_tick_sync` so daemon-owned identity fields can be assembled from
live service state independently of the storage-specific record. While ownership is
still held, each tick may recreate that record and publish the machine pointer. The
phase-stamping path in `src/vaultspec_rag/server/_lifespan.py:57` and the atomic status
merge in `src/vaultspec_rag/serviceclient/_discovery.py:221` are the nearest analogues.

An intentional-stop tombstone policy must be decided explicitly so self-healing cannot
resurrect a status record after shutdown has begun.

### Typed resolution and status

Replace the optional-port result with a service-domain resolution carrying at least the
holder PID, pointer PID, port, freshness, and a reasoned state. The minimum useful
states are `absent`, `ready`, `pointer_missing`, `pointer_invalid`, `pointer_stale`, and
`pointer_foreign_pid`. Compatibility fallback is valid only when no machine lock is
held. CLI and other adapters consume the same result.

A reconcile operation must not call destructive singleton-reclaim or maintenance code.
With the current files, a client cannot safely discover the owner's address when the
pointer is missing or foreign. The bounded initial behavior should wait for owner-driven
heartbeat repair and verify holder, pointer, and health coherence. Active repair needs
new independently trustworthy lock metadata or another recovery channel.

## B5 test isolation gap

The suite has an isolation fixture, but it is conditional:

- `src/vaultspec_rag/tests/conftest.py:31-60` preserves ambient status and Qdrant
  storage variables instead of overriding them for the session.
- `src/vaultspec_rag/tests/conftest.py:72-93` only rearms variables that are missing,
  not ones changed to a real managed path.
- `src/vaultspec_rag/tests/test_service_discovery_schema.py:55-67` isolates only the
  status directory, while its heartbeat calls at lines 86 and 227 also publish to the
  machine path derived from Qdrant storage.

Correct this under the accepted singleton-isolation rule: force both paths to one
session-owned temporary root, restore ambient values only after the suite, reset cached
configuration on every transition, and fail before any singleton write or termination
if a test resolves the real managed root.

## B6 process-boundary status

Current static ordering already rejects a losing singleton before components:

- `src/vaultspec_rag/server/_lifespan.py:41-54` raises on lock loss.
- `src/vaultspec_rag/server/_lifespan.py:237-258` claims before component startup.
- `src/vaultspec_rag/server/_lifespan.py:408-421` creates maintenance only after
  successful startup.
- `src/vaultspec_rag/server/_main.py:116-207` distinguishes HTTP mode from the no-port
  stdio MCP shim; the incident's quoted no-port command is not proof of a second HTTP
  daemon.

Existing tests cover lock races or idempotent CLI attach, not a real losing daemon.
Reproduce first with an isolated real lock holder and real HTTP subprocess. Require a
bounded nonzero loser exit, no listener, no Qdrant child identity, no pointer overwrite,
and no watcher or maintenance work. Only harden the process boundary if that test fails.

## Real-behavior regression matrix

- Delete only the isolated per-status file under a live real daemon; after a real
  heartbeat, both records must be coherent and health must remain ready.
- Hold a real isolated OS lock in one subprocess. A second process must be unable to
  publish or delete its pointer; the holder must succeed.
- Combine a live holder with fresh and stale foreign-PID pointers. Resolution must be
  degraded, must expose both PIDs, and must not accept status-directory fallback.
- Corrupt discovery for a real daemon, observe degraded rather than stopped, then wait
  for owner-driven repair and verify PID, token, port, and health without changing the
  daemon PID.
- Run the dangerous heartbeat writer in a child pytest session with ambient variables
  aimed at a test-owned trap. The trap must remain untouched.
- Race two real isolated HTTP daemons. Exactly one may remain alive, listen, and own the
  lock; the loser must start no subordinate work.

The public contract in `docs/service-discovery.md:9-14` documents only the status
directory. Any contract correction must use the required documentation pipeline after
the architecture decision is approved.
