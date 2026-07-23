---
tags:
  - '#research'
  - '#storage-autoprune-safety'
date: '2026-07-13'
modified: '2026-07-23'
related:
  - '[[2026-06-18-storage-lifecycle-adr]]'
  - '[[2026-07-13-control-plane-affordances-adr]]'
  - '[[2026-07-13-control-plane-affordances-audit]]'
---

# `storage-autoprune-safety` research: `service-kill trace and scheduled auto-prune design`

Operating the storage surface today surfaced two problems. First, the resident
service was found terminated at the end of a `server storage prune --yes` run
(79 orphan drops) - a prune must never take the service down, and the causal
chain needs a definitive trace. Second, the prune itself was manual: 79
orphaned namespaces had silently accumulated 167.9GB (the machine store had
grown to 300.8GB, driving the host disk to 677MB free), because nothing in the
service periodically reclaims 100%-confirmed-dangling data. This research
traces the kill and grounds the design of a scheduled auto-prune with a hard
data-safety contract.

## Findings

### F1 - The service kill: RESOLVED - a concurrent session's deliberate stop, not the prune

Forensics from the resident `service.log`: the prune process' output completed
at 18:36:45 local; a CLI-direct survey's per-collection point counts logged at
18:37:05; the old daemon served `GET /health 200` moments before
`cli.lifecycle event=shutdown reason=cli_terminate pid=106160` at 18:37:25; a
fresh daemon (`Started server process [36460]`) began at 18:37:49. The only
production writer of that line is `_terminate_and_confirm`
(`src/vaultspec_rag/cli/_service_lifecycle.py`), reachable exclusively from
the `server stop` flows; `server storage prune|survey`, `server status`, and
`server start` contain no terminate path, the prune business logic
(`prune_orphaned`/`delete_prefix` in `src/vaultspec_rag/storage_ops.py`) is
pure Qdrant client calls plus manifest bookkeeping, and the daemon's
supervised qdrant child never died (no `qdrant_restart`/`qdrant_dead`
events). The verdict: a concurrent working session (the index-drift-hardening
feature, commits `3a75362`/`2d391f5` later that evening) deliberately ran
`server stop` around its full integration runs - its closeout record states
"full integration runs REQUIRE the resident machine service stopped
(delegation-sensitive CLI tests) - stop it first, restart after". Both
`cli_terminate` events (17:30:48 pid 33400 and 18:37:25 pid 106160) match
that stop-restart pattern; the second landed 40 seconds after the prune
finished, creating the false appearance that the prune killed the service.
The `/health 200` was the stop flow's identity probe, the stop unlinked
`service.json` (why the follow-up `server status` reported stopped), and the
machine lock was already free when the subsequent `server start` succeeded.
The prune is exonerated.

### F2 - The real defects the episode exposed: attribution and singleton coordination

The trace cost hours because the shutdown audit line records only the TARGET
(`pid=106160`) - nothing identifies the initiator. Defect (a): the
`cli_terminate` event (and the stop envelopes) should carry the initiating
process' pid, command line, and cwd, so "who stopped the machine service" is
answerable from one log line. Defect (b): the resident service is a machine
singleton that any session can silently stop while another depends on it -
the exact hazard a scheduled auto-prune inside the daemon removes (the daemon
prunes its own store; no cross-process stop choreography). As a defensive
invariant for that future in-daemon maintenance: no storage-maintenance code
path (survey, prune, delete, auto-prune) may reach `_terminate_and_confirm`,
`_reclaim_machine_singleton`, or any stop flow - maintenance is read/drop
only, and a regression test should assert the import/call graph
(codification candidate `storage-maintenance-is-lifecycle-inert`).

### F3 - The waste profile: empty preallocated namespaces dominate

The reclaimed 79 namespaces held **zero points** each yet ~2.1GB apiece -
qdrant 1.18.2 preallocates ~2.1GB of mmaps per collection pair at create.
Every throwaway root (test temp dirs, dashboard livetests, codex temp
worktrees) permanently costs ~2.1GB until pruned. The remaining 65 "live"
namespaces (132.8GB) include temp roots whose directories still exist; they
become orphans only when those dirs vanish. Dangling-data growth is
structural, not incidental - this is why reclamation must be periodic and
owned by the service (`service-domain-owns-operability`), not left to an
operator remembering a CLI verb.

### F4 - The safety gap in today's orphan classification: existence is not proof of death

`classify_root` calls a root orphaned when its manifest-recorded path no
longer exists. On Windows especially, a valid root can transiently
not-exist: an unmounted or unplugged drive, a network share that is offline,
a directory mid-rename, a git worktree being re-created. A single-scan
existence check is NOT "100% confirmed dangling" - an auto-prune acting on
one observation could delete real semantic data whose root reappears an hour
later. Manual prune has a human in the loop; scheduled prune must replace
that human with time: an orphan may only be auto-reclaimed after it has been
observed orphaned continuously for a grace window (first-seen-orphaned
persisted in the storage manifest), and a root that reappears mid-window
resets the clock.

### F5 - Existing periodic machinery to build on

The daemon already owns exactly the needed primitives
(`src/vaultspec_rag/server/_lifecycle.py`, `_lifespan.py`):

- `_heartbeat_loop` - a lifespan-owned asyncio task on a 15s cadence,
  cancelled in the lifespan finally, wrapped so it "must never crash the
  service".
- `_qdrant_liveness_tick` - a maintenance check deliberately riding the
  heartbeat cadence instead of adding a sweeper ("there is deliberately no
  background sweeper").
- The jobs registry (`src/vaultspec_rag/jobs.py`) records every unit of work
  with `source`/`trigger` (currently `tool`/`watcher`) and powers the bounded
  `server jobs` operator view.

An hourly auto-prune slots in as either a divider on the heartbeat (240 ticks
= 60min) or a second lifespan task, and MUST report through the jobs registry
(a new `trigger="schedule"`, `source="maintenance"`) so `server jobs` shows
every cycle and `server logs` carries a rollup line - the operator-visible
audit trail the `operator-views-are-bounded` rule expects.

### F6 - Data-bearing vs empty namespaces deserve different destruction rules

The dominant reclaim target (F3) is riskless: zero points, pure preallocated
emptiness. A namespace with points is semantic data. A two-tier destruction
policy follows: (a) empty orphans (0 points across all collections of the
prefix) - drop after the grace window, no archive; (b) point-bearing orphans -
require a longer grace window AND write a qdrant snapshot archive (or refuse
and only surface in health output, leaving the drop to the operator; the ADR
should decide). Qdrant supports per-collection snapshots; footprint is
filesystem-derived so archive cost is measurable before choosing.

### F7 - Health rollup belongs in the same tick

The user's requirement "the service must make sure it is always healthy"
folds naturally into the same periodic tick: disk-free-space check (the
gridstore/mmap failures of 2026-07-13 were disk-full failures that surfaced
as opaque 500s), orphan count and dangling bytes, quarantine/pending-reclaim
state - logged as one rollup line per cycle and exported through `/metrics`
and `server status`. The 60min cadence the user suggested fits: reclamation
urgency is hours, not seconds, and a slow cadence keeps the tick invisible
next to search/index load. All service-side work must respect the GPU rules:
the maintenance tick is pure storage IO and never touches the GPU or the
`gpu_lock`.

### F8 - Config surface

Following existing knob patterns (`VAULTSPEC_RAG_*` env plus config file):
`storage_autoprune` (bool), `storage_autoprune_interval_minutes` (default
60), `storage_autoprune_grace_hours` (default 24; longer default for
point-bearing namespaces), `storage_autoprune_max_per_cycle` (bound the blast
radius per tick). Manual `server storage prune` keeps its current immediate
semantics (human in the loop); only the scheduled path applies the grace
machinery - the ADR should confirm or unify.

## Recommendation

The prune needs no fix (F1). Take an ADR deciding: (1) shutdown-attribution -
enrich the `cli_terminate` audit event and stop envelopes with initiator pid,
command, and cwd (F2a, small and immediate); (2) the scheduled in-daemon
auto-prune - heartbeat-divider vs dedicated lifespan task (F5), the two-tier
destruction policy for point-bearing orphans (archive-then-drop vs
surface-only, F6), grace-window defaults and the manifest first-seen-orphaned
schema (F4), per-cycle caps and config knobs (F8), and the health rollup in
the same tick (F7); (3) whether manual prune adopts the grace gates; (4) the
lifecycle-inertness invariant as a codification candidate
(`storage-maintenance-is-lifecycle-inert`, F2b).

## Sources

- `C:\Users\user\.vaultspec-rag\service.log` lines ~29585, ~50086 (the two
  `cli_terminate` events), qdrant.log recovery window
- `src/vaultspec_rag/cli/_service_lifecycle.py` - `_terminate_and_confirm`
  and its three stop-flow callers
- `src/vaultspec_rag/storage_ops.py` - `gather_survey`, `delete_prefix`,
  `prune_orphaned`
- `src/vaultspec_rag/server/_lifecycle.py` - `_heartbeat_loop`,
  `_qdrant_liveness_tick`
- `src/vaultspec_rag/jobs.py` - job registry `trigger` taxonomy
- ADR `2026-06-18-storage-lifecycle-adr` (D2/D3/D5/D6 - manifest, survey,
  prune discipline)
- Prune run evidence 2026-07-13: 79 orphans, 167.9GB reclaimed, all 0 points
