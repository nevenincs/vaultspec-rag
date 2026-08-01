---
tags:
  - '#adr'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:aae56d75643ccc51b89b0f5bb913961c964720a9384bfeba13063b396d4f9a67'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-research]]"
  - "[[2026-07-21-index-backpressure-storage-hygiene-adr]]"
  - "[[2026-07-14-storage-autoprune-safety-adr]]"
---

# `storage-prealloc-reclaim` adr: `in-place collection geometry reconcile` | (**status:** `accepted`)

## Problem Statement

The index-backpressure decision bounds per-collection preallocation by capping
write-ahead log capacity and seeding two segments. That bound is applied in the
collection creation path, which returns early when the collection already
exists. No path reconciles an existing collection, so every collection created
before the change keeps its original geometry permanently and upgrading
reclaims nothing.

On the observed backend this is the dominant cost: roughly 84% of 38.0 GB is
fixed preallocation rather than data, with zero-point collections occupying
1.22 GB each (research F1, F2). The existing reclamation paths - orphan prune,
ephemeral tier, debris removal - together address roughly 7.5 GB, while
geometry reconcile addresses 25-30 GB (research F9).

This ADR decides how an existing collection's geometry is reconciled, what
convergence contract that reconcile obeys, and where it runs. It does not
revisit which geometry is correct; the create-time target stands.

## Considerations

- Research F4: `update_collection` accepts an optimizer configuration and not a
  write-ahead log configuration, so segment geometry is mutable in place while
  log capacity is fixed at creation.
- Research F7: in-place reconcile reclaimed 63-84% across populations from zero
  to 20,000 points, preserved point counts exactly, and returned identical
  dense search results. It also beat fresh bounded creation at every
  population, because the optimizer merges to one segment where creation seeds
  two.
- Research F8: the reconcile request returns immediately and the optimizer
  restructures in the background, during which both segment count and on-disk
  size rise above their starting values before falling. A naive measurement of
  the 20,000-point case reported 29% growth where the converged result was 63%
  reclamation.
- Research F9: the production distribution is weighted toward near-empty
  collections, where reclamation is highest.
- Research F10: debris removal already exists and needs no new work; the
  perceived gap was an artefact of the resident version predating it.
- Research F3 and F5: the resident service predates the shipped work entirely,
  so releasing it is a precondition for both the create-time bound and the
  ephemeral tier. That release is not a decision this record needs to make.
- Reconcile is non-destructive. It moves no points, deletes no namespace, and
  needs none of the grace-window machinery that governs destruction.
- The optimizer consumes CPU and disk bandwidth, not GPU. It cannot contend for
  the single GPU consumer or the embedding lock.
- Qdrant optimizes concurrently with reads and writes by design, so reconcile
  does not require quiescing the indexer.

## Considered options

- **Recreate each collection under the bounded configuration.** Rejected: it
  requires snapshotting or re-indexing every root, doubles peak storage during
  the swap, introduces a window where a collection is absent or partial, and
  buys nothing over in-place reconcile - which measured strictly better at
  every population.
- **Reconcile only zero-point collections.** Rejected: it forgoes the measured
  63% reclamation at 20,000 points for no safety gain, since point preservation
  and search equivalence were verified across the whole sweep.
- **Leave reconcile to a documented manual operator procedure.** Rejected: the
  condition is created by ordinary upgrade, affects every pre-existing
  collection on every installation, and silently costs gigabytes. A defect
  produced by our own change is ours to converge automatically.
- **Reconcile synchronously inside the creation path when geometry differs.**
  Rejected: it would make opening a store block on optimizer convergence,
  putting a multi-minute background operation on the latency path of search and
  indexing.
- **In-place optimizer reconcile, convergence-verified, run from the scheduled
  maintenance cycle and an explicit operator verb.** Chosen.

## Constraints

- Reconcile is non-destructive: it never drops a collection, deletes points, or
  removes a namespace. It is not a destruction path and does not consult grace
  windows, orphan stamps, or archive state.
- Reconcile never touches the GPU and never imports a CLI lifecycle helper. The
  lifecycle-inertness import guard extends to cover it unchanged.
- The reconcile decision reads collection configuration only. A collection
  whose geometry already matches target is skipped, making the operation
  idempotent and a no-op on a converged backend.
- Reported reclamation is measured after convergence or not reported at all. No
  operator view, metric, or structured result may carry a mid-flight size or
  segment count.
- Convergence waiting is bounded. A collection that does not settle within its
  budget is reported as still converging, never as failed and never as
  reclaimed, and is retried on a later cycle.
- Per-cycle work is capped so a backend with many drifted collections converges
  over several cycles rather than saturating disk in one.
- The operator verb obeys the structured-outcome contract: one envelope per
  exit path in JSON mode, an already-satisfied request is a success, and a
  dry run mutates nothing.
- Write-ahead log capacity remains at its created value on reconciled
  collections. This residue is accepted and documented, not worked around by
  recreation.
- Validation uses a real qdrant server with production collection geometry.
  Convergence and reclamation are asserted against measured directory size, not
  against a mocked optimizer or a fabricated size.

This ADR supersedes no prior record. It amends the index-backpressure decision
narrowly: the bounded geometry it introduced becomes a property the service
converges existing collections toward, rather than a property only new
collections receive.

## Implementation

**D1 - Geometry drift is readable without authorising a change.** The storage
domain gains a drift predicate that compares a live collection's optimizer
segment target against the configured target. Collections whose target differs
are reported as drifted, with their current segment count and on-disk
footprint. Drift is exposed two ways before any mutation: the reconcile verb's
preview, which mutates nothing, and the drifted gauge, which the maintenance
cycle publishes every tick. Drift is deliberately NOT added to the namespace
survey - the survey is namespace-scoped and cached for sub-second operator
reads, while geometry is per-collection and costs a `get_collection` per
entry; pushing it there would either double the survey's cost or serve stale
geometry from the snapshot cache.

Reconcile reads and mutates only canonically-prefixed namespaces this project
owns, the same guard every destructive verb applies. A shared Qdrant instance
may hold collections belonging to other applications, and triggering a
multi-gigabyte background merge on them is not ours to do.

**D2 - Reconcile is an optimizer configuration update plus a bounded
convergence wait.** Reconciling one collection issues an optimizer
configuration update setting the segment target, then waits for convergence.
Because restructuring transiently inflates both segment count and size
(research F8), stability - not a first reading, and not a monotonic decrease -
is the convergence signal.

Stability alone is insufficient, and this is the sharpest edge in the design.
A merge queued behind a saturated optimizer thread pool has not started, so
its segment count and size are also perfectly stable; measuring it would
publish an untouched footprint as a converged reclamation. The busy signal is
the collection status (green / yellow / grey / red), NOT the optimizer status,
which is an ok-or-error field with no busy state at all and would therefore
read settled on every healthy sample. The wait is consequently two-phase:
observe the collection leave green, then wait for it to return to green and
hold steady. A collection that never leaves green within a short start window
had no work to do, and its unchanged measurement is a truthful zero-reclaim
result.

Because a merge inflates before it shrinks, each reconcile pre-flights free
space against the collection's own footprint and is skipped rather than
started when the volume lacks headroom - these backends are reconciled
precisely because they are full, and pushing one into ENOSPC mid-optimize is
the wedge class the bounded-write work already hardened against.

The wait is bounded by a configurable budget. Convergence within budget yields
a reconciled outcome carrying before and after footprint and the reclaimed
delta. Budget expiry yields a converging outcome carrying the before footprint
and no reclaim figure; the collection is left in whatever state the optimizer
has reached, which is valid and self-healing, and a later cycle re-evaluates
it. Only an error from the update call itself yields a failed outcome.

**D3 - The scheduled maintenance cycle converges the backend.** The existing
storage maintenance cycle gains a reconcile stage that runs after reclamation,
so a convergence budget is never spent on a namespace the same cycle is about
to destroy. It targets drifted collections up to a per-cycle cap, and reports
reconciled, converging, skipped, and failed counts plus total reclaimed bytes
into the same maintenance result the jobs registry and metrics already consume.
The stage is knob-gated and enabled by default, dry-runs with the rest of the
cycle, and is subject to the same never-crash-the-service discipline as the
reclamation stages.

**D4 - An explicit operator verb.** The storage command group gains a reconcile
verb that surveys drift, applies reconcile to drifted collections, and renders
through the existing structured emitters. It supports a preview that reports
the drift set and projected work without mutating, a bound on how many
collections to reconcile, and a no-wait mode that issues updates and returns
the converging set rather than blocking. A backend with no drift is a success
reporting nothing to do.

**D5 - Observability.** Reconcile emits counters for collections reconciled and
bytes reclaimed, and a gauge for collections not yet converged, alongside the
existing maintenance metrics. Log lines record per-collection before and after
footprints on completion only.

The gauge counts both collections whose setting is still off-target and
collections already at target that are still merging. Setting-drift alone
would be a lie: the configuration update lands before the merge does, so a
gauge keyed on it would read zero while gigabytes were still in flight. With
the unsettled term included, the gauge reaching zero genuinely means the
backend has converged.

**Config knobs** (existing naming conventions): reconcile enable, per-cycle
collection cap, and convergence wait budget.

## Rationale

We will reconcile in place rather than recreate because measurement removed the
reason to recreate: in-place reconcile preserved every point, returned
identical search results, and produced a smaller collection than fresh bounded
creation at every population tested. Recreation would add a partial-collection
window and double peak storage to achieve a strictly worse result.

We will treat stability rather than a single reading as the convergence signal
because the optimizer transiently inflates what it is about to shrink. This is
the one finding most likely to be lost in implementation, and encoding it as a
constraint on what may be reported is what prevents a correct reclamation from
being recorded as a regression.

We will converge automatically from the maintenance cycle because the drift is
created by our own shipped change, applies to every collection on every
existing installation, and costs gigabytes silently. Leaving it to a manual
procedure would make the fix reach only operators who read release notes.

We will keep reconcile outside the creation path because convergence takes
minutes and the creation path is on the latency path of search and indexing.

We will accept the write-ahead log residue because it is fixed at creation,
immaterial against the floor it sits beside, and removing it would require
exactly the recreation this decision rejects.

## Consequences

- Existing backends converge toward bounded geometry over several maintenance
  cycles without operator action; the observed 38.0 GB backend is projected to
  reclaim 25-30 GB.
- Reclamation becomes visible before it is authorised, because drift is a
  survey property rather than an effect discovered afterwards.
- The first cycles after upgrade do sustained optimizer work, consuming CPU and
  disk bandwidth. The per-cycle cap bounds this; it does not eliminate it.
- Collections that do not settle within budget keep converging on their own -
  the setting has already landed, so no retry is needed to finish the merge.
  They continue to count toward the not-yet-converged gauge until they settle,
  but the bytes they eventually reclaim are not attributed to any cycle, so
  the reclaimed-bytes counter under-reports on a backend that regularly
  exceeds its convergence budget.
- Reconciled collections keep a 32 MiB write-ahead log where new collections
  take 16 MiB, leaving a small permanent asymmetry between reconciled and
  freshly created collections.
- The maintenance cycle now performs non-destructive mutation as well as
  destruction, so the lifecycle-inertness guard covers a broader surface while
  the storage-maintenance rule itself is unchanged.
- Reclamation figures depend on directory measurement, so a backend on a
  filesystem where size is not promptly reflected may under-report a reclaim
  that did occur.
