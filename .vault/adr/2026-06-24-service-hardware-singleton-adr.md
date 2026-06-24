---
tags:
  - '#adr'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-service-hardware-singleton-research]]"
---

# `service-hardware-singleton` adr: `one service per machine with verified qdrant attach` | (**status:** `accepted`)

## Problem Statement

The resident RAG service manages one machine's hardware - one GPU and one managed Qdrant
server (fixed port, one shared single-writer RocksDB storage) - but the service-instance
architecture (keyed per port, token, status-dir, and root) permits several instances on that
machine, none of which arbitrates the shared hardware. The Qdrant supervisor spawns its child
unconditionally with no pre-flight check, and the `server start` guard is port-scoped only.
The sibling research reproduced the consequence: an orphaned Qdrant from a prior instance held
the port and storage so every new start failed its readiness wait, and a single corrupt
collection in the shared store panicked the whole server for every root - both surfacing as an
opaque 300s timeout because the child's panic was never logged. This ADR decides the rework
that makes the service a machine singleton and the Qdrant a verified, shared, attach-first
resource. It is grounded in `2026-06-24-service-hardware-singleton-research` (F1-F7, P1-P3,P6).

## Considerations

- The intended multi-tenancy is already multi-project within one service: a project-seat model
  (`service_max_projects`), per-root leases in the `ServiceRegistry`, idle eviction, and
  per-request `project_root`. "Many projects on one machine" is solved by one service, many
  seats - so a second resident process is the thing to prevent, not a capability to add.
- Qdrant's storage is single-writer; two children on one storage cannot coexist. Therefore a
  second instance must either attach to the running Qdrant or not run at all - never spawn a
  competitor.
- Attaching blind is unsafe: the process on the port might be a different service, a wrong
  Qdrant version, a Qdrant serving a different storage dir, or an unhealthy/half-loaded server.
  Attach must be gated on verification, not just "something answered on 8765".
- Discovery is only as reliable as the status-dir the caller reads (research F7); a
  machine-singleton guard needs a machine-scoped signal, not a per-status-dir status file.
- The current opaque failure (panic/stderr lost, 300s timeout) is itself a defect: the
  operator could not see "port held by pid N" or "collection X panicked".

## Constraints

- No frontier risk; all components (the supervisor, the service registry, the port/health
  probes) are in-tree and mature. The work is guarding and verifying existing paths.
- Cross-platform: the orphan-reap and machine-lock must work on Windows (Job Object) and
  POSIX; identity/ownership cannot rely on a single OS facility.
- Back-compat: hosts already running with overridden `--port`/status-dirs must get a clear
  migration path, not a silent break.
- Safe-attach requires an ownership/identity signal that a hostile or unrelated process on the
  port cannot trivially forge into a false "this is your managed Qdrant".

## Implementation

High-level and layered; a plan sequences it.

**D1 - One resident service per machine (P3).** `server start` becomes machine-scoped: before
starting, it detects any existing healthy service on the machine via a machine-scoped lock
(an OS-level named lock / lockfile under the machine-global managed dir, independent of the
overridable per-instance status dir) plus a health probe. If one is found, start refuses with
a clear pointer to the running instance (and its port), rather than spawning a second resident
that would contend for the GPU and Qdrant. The multi-project seat model remains the supported
way to serve many roots from that one instance.

**D2 - Qdrant attach-not-spawn, gated on health + capability + lock verification (P1).** Before
the supervisor spawns, it probes the configured Qdrant port and ATTACHES only when all gates
pass: (a) *healthy* - `/readyz` returns ready and `/healthz` is green; (b) *capable* - the
reported version matches the managed `QDRANT_SERVER_VERSION` and the server is serving the
expected machine-global storage path, so attaching cannot silently bind a foreign or
mis-storaged server; (c) *owned* - an ownership signal (D4) confirms it is our managed Qdrant.
On full pass the service uses the running Qdrant as the shared singleton (no spawn). If a
process holds the port but any gate fails, start does NOT spawn a competitor - it stops with a
clear error (D3).

**D3 - Orphan and lock detection with fast, clear, logged failure (P2).** Pre-flight: if the
Qdrant port is occupied or the storage lock is held, resolve the holder. A *provably-dead
managed orphan* (our storage lock held with a dead owner PID, or a stale managed child) is
reaped before spawning. A *live but unattachable* holder (foreign process, wrong version)
produces a fast failure (seconds, not 300s) naming the port and PID. The readiness path stops
waiting the moment the child dies and surfaces the cause.

**D4 - An ownership/identity signal for safe attach.** The supervisor records a machine-local
identity for the Qdrant it manages (e.g. a sidecar identity file in the managed dir capturing
the storage path, version, and owning service token, written when it brings Qdrant up), so a
later start can verify "this running Qdrant is the one this machine's service manages" rather
than trusting a version string alone. The signal must be local-trust (not network-forgeable)
and validated together with the health/capability gates of D2.

**D5 - Capture the child's failure output.** Fix the supervisor so the Qdrant child's
stdout/stderr (including a Rust panic) actually reaches `qdrant.log`, and a non-ready exit is
reported with the tail of that output. A bad collection or a bind failure must present as a
named cause, not an opaque timeout. (The shared-storage blast radius of a single corrupt
collection - research F6/P6 - is noted for a follow-on; this ADR's scope is the singleton and
attach contract, and making its failures legible.)

## Rationale

The research established the failure is structural: the Qdrant singleton (one port, one
single-writer storage) is contended by a service architecture that permits multiple instances
and spawns blindly. Attach-not-spawn (D2) is the smallest change that removes the contention -
a second instance reuses the one Qdrant instead of deadlocking on its storage lock - and the
machine singleton (D1) removes the deeper hazard of two residents fighting for the GPU. The
verification gates are non-negotiable per the owner's direction: attaching to an unhealthy,
wrong-version, wrong-storage, or unowned server would be worse than spawning, so health + lock
+ capability checks gate every attach. D3/D5 turn the current opaque 300s failure into a fast,
named one, which is what made the live incident hard to diagnose.

## Consequences

- Gains: a second start can no longer brick the machine's RAG; restart is graceful (attach to
  the still-running Qdrant or reap a dead orphan); failures name their cause in seconds; the
  GPU and Qdrant have one owner, matching what the rest of the architecture already assumes.
- Costs and risks: the ownership signal (D4) must be designed so it cannot be forged into a
  false-positive attach, and the machine-scoped lock (D1) must be released reliably on crash
  (the same orphan class it guards against). Attach introduces a new "someone else's Qdrant"
  trust boundary that the verification gates must hold.
- Pathways opened: once Qdrant is a verified shared singleton, the dashboard's separate
  instance can attach to it; bounded collection pruning (research P7) and per-collection
  load-isolation (P6) become natural follow-ons.

## Codification candidates

- **Rule slug:** `one-rag-service-per-machine`.
  **Rule:** The resident RAG service is a machine singleton; `server start` must detect an
  existing healthy service via a machine-scoped signal and refuse to spawn a second, because
  one GPU and one single-writer Qdrant storage cannot be co-owned. Many projects are served by
  one service's seats, never by many services.

- **Rule slug:** `qdrant-attach-not-spawn-when-verified`.
  **Rule:** Never spawn a Qdrant child when one is already serving the configured port; attach
  only after verifying health, matching managed version, the expected storage path, and an
  ownership signal, and fail fast with a named cause otherwise - never start a competing child
  on the shared single-writer storage.
