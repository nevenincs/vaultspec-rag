---
tags:
  - '#adr'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-13-storage-autoprune-safety-research]]"
  - "[[2026-06-18-storage-lifecycle-adr]]"
  - "[[2026-07-13-control-plane-affordances-adr]]"
---

# `storage-autoprune-safety` adr: `scheduled in-daemon auto-prune with a grace-window safety contract` | (**status:** `accepted`)

## Problem Statement

The shared machine Qdrant store accumulates dangling namespaces structurally:
every throwaway root (test temp dirs, livetests, temp worktrees) costs ~2.1GB
of preallocated mmaps even at zero points, and nothing reclaims it without an
operator remembering `server storage prune`. On 2026-07-13 the store had
grown to 300.8GB with 79 orphans (167.9GB, all empty) and the host disk was
down to 677MB free - disk exhaustion then surfaced as opaque qdrant 500s.
Separately, tracing a same-day service shutdown cost hours because the
shutdown audit line records only the terminated pid, never the initiator.
Reclamation must become periodic, service-owned, and provably safe: automated
deletion may only ever touch data that is 100% confirmed dangling, because a
single-scan "root path does not exist" observation can be a transiently
unmounted drive or offline share holding perfectly valid semantic data.

## Considerations

- `service-domain-owns-operability`: the reclamation behavior belongs to the
  service domain; CLI and MCP adapt to it. An in-daemon schedule also removes
  the cross-session stop choreography that caused the 2026-07-13 scare.
- The `2026-06-18-storage-lifecycle-adr` established the primitives this
  builds on: the prefix-to-root manifest, survey classification
  (live/orphaned/unknown/unverifiable), and the prune discipline (never
  touch `unknown`, dry-run-first for operators).
- Research F4: orphan classification is a single-scan existence check - NOT
  sufficient proof of death for automation. The human in the manual prune
  loop must be replaced by time, not removed.
- Research F5: the daemon already owns the needed primitives - the
  lifespan-owned `_heartbeat_loop` pattern (crash-proof periodic task), the
  `_qdrant_liveness_tick` precedent for maintenance riding a cadence, and
  the jobs registry with its `source`/`trigger` taxonomy and bounded
  operator views.
- Research F3/F6: the dominant waste (empty preallocated namespaces) is
  riskless to drop; point-bearing namespaces are semantic data and deserve a
  stronger destruction bar.
- All maintenance work is pure storage IO: it must never touch the GPU, the
  `gpu_lock`, or block the search path (`storage-locks-are-backend-aware`).
- Research F2: the maintenance path must be lifecycle-inert, and shutdown
  events need initiator attribution.

## Considered options

- **O1 - in-daemon scheduled maintenance task (chosen).** A dedicated
  lifespan asyncio task on an hourly cadence dispatching through the jobs
  registry. Service-owned, observable, no external scheduler dependency.
- **O2 - OS-level scheduler (cron / Task Scheduler) driving the CLI.**
  Rejected: unobservable from `server jobs`, needs per-machine setup, races
  the daemon (CLI-direct client against a live server), and reintroduces
  cross-process choreography.
- **O3 - piggyback the 15s heartbeat with a divider.** Rejected as primary:
  couples an hour-scale destructive job to the liveness heartbeat; a slow
  survey/drop cycle inside the heartbeat worker thread would delay liveness
  ticks. A dedicated task with the same crash-proof wrapper is one small
  block of code and isolates failure domains.
- **Point-bearing orphans: archive-then-drop (chosen) vs surface-only.**
  Surface-only would leave point-bearing dangling data on disk forever -
  exactly the accumulation this ADR exists to stop. Archive-then-drop keeps
  a recovery path: after the long grace window, write per-collection qdrant
  snapshots into a bounded archive dir, then drop; archives age out on their
  own retention. Rejected middle option (drop without archive) fails the
  data-safety mandate for semantic data.
- **Empty-orphan handling: drop after grace (chosen)** vs archive-everything:
  archiving zero-point collections wastes the very disk being reclaimed.

## Constraints

- Server mode only (the local store has one namespace and no manifest);
  the tick is a no-op in local-only mode.
- `unknown` and `unverifiable` namespaces are NEVER auto-touched - unchanged
  from the storage-lifecycle ADR. Only manifest-attributed `orphaned`
  entries qualify.
- The grace clock persists in the storage manifest (schema addition:
  `first_seen_orphaned` per prefix, cleared when the root reappears); a
  daemon restart must not reset it, and a reappearing root must.
- The maintenance task must reuse `prune_orphaned`/`delete_prefix` -
  one destruction implementation shared with the CLI, per
  `service-domain-owns-operability`.
- Lifecycle inertness: no code reachable from the maintenance tick may
  import or call the stop/terminate/reclaim helpers; enforced by a
  regression test on the import graph.
- The tick is bounded: per-cycle deletion cap, one jobs-registry entry and
  one log rollup line per cycle (`operator-views-are-bounded`).
- GPU-free: storage IO only; never acquires `gpu_lock`.

## Implementation

**Schedule.** The daemon lifespan starts a `_maintenance_loop()` asyncio task
alongside `_heartbeat_loop()`, same crash-proof shape (never raises out,
cancelled in the lifespan finally). Default interval 60 minutes; first run
delayed one interval after startup (a freshly started daemon should serve
before it sweeps).

**Cycle.** Each tick registers a jobs-registry job (`source="maintenance"`,
`trigger="schedule"`) and runs: (1) survey via the shared classifier;
(2) manifest grace bookkeeping - stamp `first_seen_orphaned` on newly
orphaned prefixes, clear it for reappeared roots; (3) reclamation -
empty orphans (0 points across the prefix) past `grace_hours` (default 24)
are dropped via `delete_prefix`; point-bearing orphans past
`grace_hours_data` (default 168 = 7 days) are snapshotted per-collection
into `{storage_parent}/archive/` and then dropped; (4) archive retention -
archives older than `archive_retention_days` (default 30) are deleted, and
the archive dir is capped by total bytes (oldest evicted first);
(5) health rollup - one structured log line + `/metrics` gauges: disk free
(warn under a threshold), namespace counts by status, dangling bytes,
pending-grace counts. Per-cycle deletions are capped
(`max_reclaims_per_cycle`, default 16); the remainder waits for the next
tick.

**Safety gates stacked per prefix**: canonical-prefix regex, manifest
attribution, `orphaned` classification, grace-window age, empty-vs-data
tier, per-cycle cap. Any gate failing skips the prefix and reports why.

**Config knobs** (env + config file, following existing naming):
`storage_autoprune` (default on), `storage_autoprune_interval_minutes` (60),
`storage_autoprune_grace_hours` (24), `storage_autoprune_grace_hours_data`
(168), `storage_autoprune_archive_retention_days` (30),
`storage_autoprune_max_per_cycle` (16). Manual `server storage prune` keeps
its immediate human-in-the-loop semantics (no grace) - the operator IS the
confirmation - but gains a `--respect-grace` flag for parity scripting.

**Shutdown attribution.** `_terminate_and_confirm`'s audit event (and the
stop `--json` envelopes) gain initiator fields: the terminating process' pid,
its command line (argv joined), and cwd - so "who stopped the machine
service" is answerable from one log line. Purely additive to the envelope
`data`.

**Surfaces.** `server status` shows the last maintenance cycle summary and
next-run ETA; `/metrics` exports the gauges; `server jobs` lists cycles like
any other job. MCP inherits via the existing read-only surfaces.

## Rationale

The service is the only actor that is always present, already owns the
manifest and classifier, and can schedule without cross-process choreography
(research F1/F2/F5) - in-daemon scheduling is both the operability answer
(`service-domain-owns-operability`) and the safety answer. Time replaces the
human: a 24h continuous-orphan window converts "path missing right now" into
"confirmed dangling" for the riskless empty tier, and a 7-day window plus a
recoverable archive protects the point-bearing tier (F4/F6), honoring the
mandate that automation must never destroy data with a valid claim while
still guaranteeing dangling data cannot occupy disk forever. The two-tier
split matches the measured waste profile: 100% of the 2026-07-13 reclaim was
zero-point namespaces (F3). Attribution closes the forensic gap that made a
routine deliberate stop look like a prune bug for hours (F1/F2a).

## Consequences

- **Gains.** Disk exhaustion from dangling namespaces becomes structurally
  impossible (bounded by grace windows and cadence); the service self-reports
  its storage health; shutdowns become attributable; the dashboard and other
  consumers inherit a store that no longer silently bloats.
- **Honest difficulties.** The manifest schema grows a field (migration for
  existing manifests: absent field = stamp on next tick, so the first
  reclaim happens no earlier than one grace window after upgrade). Archives
  consume disk until retention expires - bounded, but nonzero. A root on a
  drive unplugged longer than the data grace window will have its index
  archived-then-dropped; reindexing recreates it, and the archive covers the
  window in between.
- **Pathways opened.** The maintenance tick is the natural home for future
  hygiene (log-rotation checks, snapshot verification, manifest compaction);
  the `--since` survey filter completes trivially on top.
- **Pitfalls to avoid.** Running destruction inside the heartbeat worker;
  a second destruction implementation diverging from `delete_prefix`;
  auto-touching `unknown`; resetting grace clocks on daemon restart;
  unbounded archive growth; any import path from maintenance into the
  lifecycle stop helpers.

## Codification candidates

- **Rule slug:** `storage-maintenance-is-lifecycle-inert`.
  **Rule:** No storage-maintenance code path (survey, prune, delete,
  scheduled auto-prune) may reach a service stop, terminate, or
  machine-singleton reclaim helper; maintenance is read/drop only, and the
  import graph is regression-tested.
- **Rule slug:** `automated-destruction-requires-time-confirmed-danglingness`.
  **Rule:** Automated deletion of indexed data requires classification AND a
  persisted continuous grace window; a single-scan existence check is never
  sufficient, and data-bearing namespaces additionally require a recoverable
  archive before destruction.
