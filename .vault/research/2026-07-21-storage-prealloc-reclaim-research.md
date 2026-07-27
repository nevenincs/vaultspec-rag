---
tags:
  - '#research'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-27'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-adr]]"
  - "[[2026-07-14-storage-autoprune-safety-adr]]"
---

# `storage-prealloc-reclaim` research: `reclaiming per-collection preallocation from existing collections`

An operator machine's managed backend reached 38.0 GB. Triage attributed the
growth to dead worktrees, ephemeral scratchpad roots, and unattributed
collections. Measurement contradicts that attribution: roughly 84% of the
footprint is fixed per-collection preallocation that no existing reclamation
path can reach, because the bound shipped by the index-backpressure decision
applies only at collection-creation time. This research establishes the real
cost model, tests whether existing collections can be reconciled in place,
and records the boundary conditions the decision needs.

## Findings

### F1 - Preallocation, not data, dominates the footprint

The backend held 33 collection directories, 28 live collections, 14
manifested roots, and roughly 820,000 points totalling 38.0 GB.

Per-collection size is almost independent of content. Two zero-point
collections occupied 1.22 GB each. A three-point collection occupied 1.03 GB.
A 174-point collection occupied 1.47 GB. Solving the size relation across the
two largest collections (419,511 points at 4.17 GB and 136,717 points at
2.14 GB) yields a marginal cost near 7.2 KB per point and a fixed floor near
1.16 GB. Real data therefore accounts for roughly 6 GB; the remaining ~32 GB
is floor.

### F2 - The floor is segment-multiplied mmap preallocation

Inside a zero-point collection, cost decomposes as a per-segment constant
multiplied by segment count. Each segment preallocates a 32 MiB payload
storage page and a 32 MiB sparse vector storage page. Each indexed payload
field preallocates its own page set per segment - roughly 40 MB per field
across eleven fields on a code collection - plus null and has-values bitmaps
at 88 MB each, plus 64 MB of write-ahead log.

The multiplier is the decisive term. Live collections reported
`default_segment_number: 0`, meaning automatic derivation from host CPU count;
on a 24-core host that produced 8 segments per collection.

### F3 - The shipped bound is create-time only and unreleased

The bound decided by the index-backpressure record caps write-ahead log
capacity at 16 MiB and seeds two segments. It is applied in the collection
creation path, which returns early when the collection already exists. No code
path reconciles an existing collection's configuration. Every collection
predating the change therefore keeps its original geometry permanently, and
upgrading alone reclaims nothing.

The resident service on the observed machine was version 0.3.2, which predates
the change entirely; the installed source contains no write-ahead log
configuration, no last-indexed stamping helper, and no ephemeral evaluation
tier. The unreleased state compounds F5.

### F4 - Segment count is mutable in place; log capacity is not

Against qdrant-client 1.18.0, `update_collection` accepts an optimizer
configuration and does not accept a write-ahead log configuration. Segment
geometry is therefore reconcilable on a live collection without recreation,
snapshot, or point movement. Log capacity is fixed at creation and remains at
32 MiB on reconciled collections - roughly 64 MB of residue per collection,
immaterial against a floor measured in gigabytes.

### F5 - The last-indexed stamp gates the ephemeral tier shut

All fourteen manifested roots carried an empty last-indexed value. The
ephemeral namespace tier keys its idle evaluation on that stamp and skips the
tier when the mapping is absent. Ephemeral scratchpad roots consuming roughly
2.5 GB were consequently never evaluated for reclamation. The cause is the
same as F3 - the stamping helper does not exist in the resident version - so
releasing the pending work also restores this tier without further change.

### F6 - Orphan grace is functioning, not stalled

Only two roots carried an orphan stamp, and both roots genuinely no longer
existed. One held 23,694 points, placing it in the data tier with a 168-hour
grace window that had not yet elapsed. This is the time-confirmed danglingness
contract behaving as specified, not a defect.

### F7 - In-place reconcile reclaims 63-84% and is data-safe

An isolated harness on the pinned qdrant 1.18.2, replicating production
geometry (1024-dimension dense vectors, sparse vectors, on-disk payload, and
the full production payload index set), measured legacy-configured collections
before and after an in-place optimizer reconcile to two segments, against a
control created under the shipped create-time bound.

| points | legacy before | after reconcile | reclaimed | fresh-bounded control |
| -----: | ------------: | --------------: | --------: | --------------------: |
|      0 |    1243.8 MiB |       211.5 MiB |     83.0% |             327.0 MiB |
|    100 |    1371.8 MiB |       243.5 MiB |     82.3% |             391.0 MiB |
|  2,000 |    1499.9 MiB |       243.5 MiB |     83.8% |             391.0 MiB |
| 20,000 |    1185.1 MiB |       439.6 MiB |     62.9% |             422.7 MiB |

The empty-collection figure of 1243.8 MiB reproduces the observed production
value of 1.22 GB, confirming the harness models production faithfully.

Point counts were preserved exactly at every population, verified by exact
count. Dense search results over five fixed probe queries were identical
before and after. Reconcile outperformed fresh bounded creation at every
population because the optimizer merged to a single segment where a fresh
collection seeds two.

### F8 - Convergence is asynchronous and transiently inflates

An initial measurement of the 20,000-point case reported growth from 1185.1
MiB to 1526.2 MiB with segment count rising from 7 to 8, and only a longer
quiescence window revealed the true converged value of 439.6 MiB. The
reconcile request returns immediately while the optimizer restructures in the
background, and during restructuring both segment count and on-disk size rise
above their starting values before falling.

Any implementation that samples size or segment count immediately after the
request will record a regression that does not exist, and any operator view
that reports mid-flight numbers will misreport reclamation as growth. A
correct implementation waits for both segment count and directory size to
stabilise with the optimizer reporting a settled status.

### F9 - Reclamation is dominated by near-empty collections

The production distribution is heavily weighted toward the high-reclaim end of
F7: of 28 live collections, three held zero points, eight held fewer than
6,000, and only three exceeded 100,000. Applying the measured reclaim rates to
the observed distribution projects roughly 25-30 GB recovered from the 37.5 GB
of manifested collections.

For comparison, the reclamation paths that already exist - reaping the dead
worktrees and the ephemeral scratchpad roots - together address roughly 7.5 GB.
Configuration reconcile is the larger lever by a factor of three to four.

### F10 - Debris reclamation already exists and is not the gap

Configuration-less collection directories, invisible to qdrant because it
never loads them, are already surfaced as debris entries by the survey and are
already removable through an explicit operator flag on the prune verb. The
five such directories observed accounted for 0.47 GB. The triage hypothesis
that no reaper can see them is correct only of the resident 0.3.2 service; the
pending release already closes it. No new work is required here.

## Sources

Evidence gap: the retained document body has no separately labelled Sources section.
