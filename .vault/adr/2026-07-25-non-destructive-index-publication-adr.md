---
tags:
  - '#adr'
  - '#non-destructive-index-publication'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-25-non-destructive-index-publication-research]]"
  - "[[2026-07-25-index-completeness-guard-adr]]"
  - "[[2026-07-25-index-completeness-guard-audit]]"
  - "[[2026-07-21-search-index-availability-adr]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
  - "[[2026-07-25-index-resume-drift-race-adr]]"
---

# `non-destructive-index-publication` adr: `publish a rebuilt index without destroying the served one` | (**status:** `proposed`)

## Problem Statement

A rebuild destroys the index it is replacing before it has anything to replace
it with. `2026-07-25-non-destructive-index-publication-research` establishes that
an unattended incremental run escalates itself into that rebuild (F1), that the
resulting zero-point window spans the whole repopulation rather than an instant,
and that an interrupted rebuild leaves a fragment which makes every later run
reconcile the entire tree (F3). Serving is not blocked by indexing; the points
are simply gone (F2).

A decision is needed because the two remedies already recorded are each
insufficient alone. `2026-07-25-index-completeness-guard-adr` detects the
truncation after the fact and explicitly defers removing the window;
its audit recommends closing it. Meanwhile the cheapest-looking fix - stop
escalating destructively - does not work, because superseded points survive a
non-destructive re-encode (F4). The question this record answers is how a rebuild
publishes without a destructive window, given that no alias primitive exists and
the two storage backends differ (F5).

## Considerations

- The escalation is unattended: the watcher requests a reconcile and the indexer
  chooses destruction (F1). No operator intent is present at the moment the data
  is dropped.
- Superseded points must still be removed, so "never delete" is not available as
  an answer (F4).
- No alias operation exists and aliases are server-mode only, so one uniform
  atomic swap is not reachable across backends (F5).
- Local mode survives its own collection delete on disk and re-reads it on
  same-name create (F5). A swap that reuses the served name there is not clean.
- Peak storage roughly doubles for the root under rebuild, on a backend where
  preallocation already dominates footprint (F6).
- A failed rebuild leaves no matching nonterminal job, so the 503 contract does
  not cover the fragment it leaves behind (F7).
- `2026-07-21-large-index-resilience-adr` fixes the surrounding invariants - one
  GPU consumer, no competing global lock, a checkpoint that may lag storage but
  never leads it. Publication changes must preserve all three.
- `2026-07-25-index-resume-drift-race-adr` is seaming the indexer now. Work here
  lands on the seamed structure, not beside it.

## Considered options

- **Escalate to failure-safe reconciliation instead of a rebuild.** Cheapest and
  removes the destructive window immediately. Rejected as a complete answer:
  superseded points survive and the mixed-regime degradation the gates exist to
  prevent persists (F4). Retained as the interim mitigation below.
- **Refuse to escalate unattended and require an operator rebuild.** Removes the
  surprise but leaves a knowingly-degraded index serving until a human acts, and
  converts a self-healing condition into an operational ticket. Rejected as the
  destination; acceptable only as a stopgap.
- **Build into a shadow collection and swap.** Removes the window by
  construction rather than detecting it, and is what the completeness-guard audit
  recommends. Costs a duplicate collection at peak and needs a per-backend swap
  mechanism (F5, F6). Chosen.
- **Rebuild in place but hold searches off behind the availability guard.**
  Rejected: it extends a failure contract to cover a self-inflicted outage, still
  serves nothing for the duration, and leaves the post-failure fragment
  uncovered (F7).
- **Version the collection name per generation and never reuse a name.** Sidesteps
  the local-mode resurrection hazard and makes the swap a pointer move. Kept as
  the concrete shape of the chosen option rather than a separate alternative.

## Constraints

- A rebuild never removes the currently-served points until a replacement is
  complete and verified to hold what it published.
- Unattended runs may not destroy published data under any gate. Destruction is
  reachable only from an explicit operator request.
- The swap is atomic from a reader's perspective on both backends. Where the
  backend offers no atomic primitive, the served identity is resolved through one
  indirection that is itself updated atomically.
- Generation naming never reuses a name whose directory may survive deletion, so
  the local-mode resurrection behaviour cannot deliver stale points into a new
  generation (F5).
- The published-breadth figure is written for the new generation only after it is
  reconciled, so the completeness predicate keeps working unchanged.
- Peak storage is bounded and checked before a shadow build starts. A root that
  cannot afford the duplicate degrades to a stated, visible outcome rather than
  silently falling back to destruction.
- The GPU, locking and checkpoint-ordering invariants of
  `2026-07-21-large-index-resilience-adr` are unchanged by this record.
- Guard tests prove they can fail: the forbidden state is made permissible, the
  test observed failing for the assertion it names, restored, observed passing,
  both directions recorded.
- Tests use real storage and real service paths. No fake, stub, mock, patch or
  monkeypatch stands in for the behaviour under test.

## Implementation

**Interim mitigation, landing first.** The two unattended gates stop reaching a
destructive rebuild. They escalate to failure-safe reconciliation and record that
the index is serving a superseded regime, which is visible rather than silent.
This accepts the surviving-points defect of F4 for a bounded period: retrieval
quality is degraded and known, where today the index is empty and the caller is
told nothing. It is explicitly not the destination, and it is not a fallback the
final design retains.

**Generation-scoped collections.** A rebuild writes into a collection named for
its generation rather than the served name. Nothing about the served collection
changes while that build runs, so a search during a rebuild reads the previous
complete index at full breadth. A build that fails or is interrupted leaves an
unreferenced collection, never a truncated served one, which is what removes the
F3 latch at its source.

**One indirection for served identity.** Readers resolve the collection they
search through a single per-root pointer rather than deriving the served name
directly. Publication updates that pointer once, after the new generation is
reconciled and its breadth recorded. Server mode may back the indirection with a
native alias; local mode backs it with the persisted pointer the resolution
already consults. The reader-visible contract is identical, which is what keeps
one behaviour across both backends.

**Reclamation.** The superseded collection is dropped after the pointer moves and
no in-flight reader holds it. Reclamation is ordinary maintenance, read-and-drop
only, and never runs in the same path as the swap.

**Admission.** Before a shadow build begins, available headroom is checked
against the estimated duplicate. A root that cannot afford it does not silently
rebuild in place; it reports that the rebuild is not affordable and leaves the
served index intact.

## Rationale

The knockout is F4 against F1. The window has to close, and the two cheap ways to
close it each fail on one side: escalating non-destructively leaves superseded
points, and refusing to escalate leaves a degraded index until a human intervenes.
Only building a replacement before retiring the original satisfies both - the old
points are removed, and they are removed after something correct exists to serve.

Detection was the right first move and remains load-bearing, but the
completeness-guard record is explicit that it detects a window it does not close,
and its audit recommends closing it. F3 shows why that matters more than it
first appeared: under a live watcher the detected state is not transient, because
the reconcile it triggers rarely finishes before the next trigger arrives.

Routing served identity through one indirection is what makes a single design
work on two backends that do not share an atomic primitive (F5). The alternative -
a server-mode swap and a separate local-mode dance - would fork the publication
path exactly where correctness is hardest to verify.

The interim mitigation is included because F1 is live in production and the full
design lands behind an in-flight seam. It is recorded as a mitigation with a
named defect rather than a design, so it cannot quietly become the destination.

## Consequences

- A search during a rebuild reads the previous complete index instead of a
  partially repopulated one, and a failed rebuild no longer degrades what is
  served.
- The self-sustaining full-rehash condition ends, because a failed run stops
  producing the shortfall that triggers the next reconcile.
- Peak storage rises for the root under rebuild, and some roots on a tight
  backend will be told a rebuild is not currently affordable. That is a new
  operator-visible refusal that does not exist today.
- Reclamation becomes a state a reader can observe: an unreferenced collection
  may exist between a failed build and the next maintenance pass.
- The interim mitigation ships a knowingly-degraded retrieval regime for the
  period it is in place. It must be removed when generation-scoped publication
  lands, and leaving it is a defect, not a fallback.
- Collection naming stops being derivable from the root alone. Anything that
  reasons about collection names from outside the store must go through the same
  resolution, and per-root prefix exposure is affected.
- The completeness predicate and the empty-response contract keep working
  unchanged; this record removes the condition they were built to survive rather
  than altering either contract.
