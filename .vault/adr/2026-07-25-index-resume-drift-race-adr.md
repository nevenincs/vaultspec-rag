---
tags:
  - '#adr'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:8c78db152840f73d0d48c6018ba3ede3a4377dbf651493ccf6a1099d931de388'
related:
  - "[[2026-07-25-index-resume-drift-race-research]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
  - "[[2026-07-23-chunk-id-uniqueness-adr]]"
  - '[[2026-07-25-index-drift-circuit-accounting-adr]]'
  - '[[2026-07-25-document-index-drift-parity-adr]]'
---

# `index-resume-drift-race` adr: `seam the codebase indexer and give drift a single owner` | (**status:** `accepted`)

## Problem Statement

A resumed code index over a tree still being edited aborts the entire run on
the indexed-path upsert guard, and the service stays degraded while the tree
stays busy. `2026-07-25-index-resume-drift-race-research` establishes that the
guard is correct, that the window spans most of the run, and that the remedy
cannot execute inside the transaction that detects the collision.

That leaves the question of which layer owns detection and remedy, and the
honest answer today is that no layer does, because one class owns everything.
`CodebaseIndexer` is roughly 3601 lines and 115 methods inside a single 3939
line module, holding discovery, admission, chunk production, GPU dispatch,
generation and ledger lifecycle, and drift remedy at once. The pre-dispatch
drift snapshot and the dispatch loop that invalidates it are members of the
same object, so nothing in the type system or the call graph can express the
ordering they require. The race is not merely adjacent to that entanglement;
it is what the entanglement produces.

A decision is needed now because the defect is live, and because any narrow
patch has to choose an owner for the remedy. Choosing one without seaming the
module means inventing a seventh responsibility for a class that already has
six, which is how the module reached this size.

## Considerations

- The guard fails closed and stays; permitting the write duplicates content
  rather than replacing it (`2026-07-25-index-resume-drift-race-research`).
- Remedy requires storage I/O ordered before ledger mutation, so detection and
  remedy cannot share a transaction (same research).
- Narrowing the snapshot-to-record window cannot close it, only shrink it
  (same research).
- The module-length gate records the longest module as 1170 lines while that
  module now measures 3939. The gate is invoked without its failing flag, so
  the ratchet campaign it was built for never started and the drift went
  unobserved for the entire growth.
- `2026-07-21-large-index-resilience-adr` fixes the surrounding invariants: one
  in-process GPU consumer, no competing global lock, and a checkpoint that may
  lag storage but must never lead it. Any seam must preserve all three.
- Chunk identity embeds a content hash (`2026-07-23-chunk-id-uniqueness-adr`),
  which is why a superseded path's points must be dropped rather than
  overwritten.

## Considered options

- **Re-check drift immediately before recording each path's units.** Cheap and
  strictly better than today, but leaves a residual window and adds a seventh
  concern to the same class. Rejected as a complete answer; folded into the
  chosen option as a cheap early filter.
- **Defer the racing path to the next generation.** Smallest blast radius and
  simplest to reason about, but leaves the path stale for a cycle and, on a
  continuously hot tree, indefinitely. Rejected as the primary mechanism,
  retained as the bounded fallback.
- **Treat the collision as a signal and re-open the path in place.** Detection
  and remedy use the same evidence, so the window closes by construction rather
  than by timing. Chosen, conditional on the remedy having an owner.
- **Fix the race without seaming the module.** Rejected: it requires the
  remedy to live in the class whose entanglement produced the race, and
  forecloses expressing the ordering the remedy depends on.
- **Rewrite the indexer wholesale.** Rejected: no behavioural baseline survives
  it, and the existing suite is the only evidence the seams are correct.

## Constraints

- Decomposition is behaviour-preserving. The existing suite is the baseline and
  must stay green throughout; a seam that requires changing an assertion about
  indexing behaviour is a seam in the wrong place.
- The parent decision `2026-07-21-large-index-resilience-adr` is accepted and
  stable, and its GPU, locking, and checkpoint-ordering constraints bind every
  seam introduced here. This record amends none of them.
- Extraction runs ahead of the fix, not beside it. The drift owner cannot be
  introduced as a new concern inside the monolith and extracted later.
- The module-length gate must move from advisory to failing as part of this
  work, at a threshold the tree actually meets after extraction, or the same
  drift recurs unobserved.
- No new global lock and no second GPU consumer. Seams are ownership
  boundaries, not concurrency boundaries.

## Implementation

The work is ordered: seam first, then fix, then gate.

**Seam.** `CodebaseIndexer` decomposes along the responsibility clusters its
own method names already describe: discovery and admission, chunk production
and submission, generation and ledger lifecycle, and drift ownership. Each
becomes a collaborator the indexer holds rather than a region of one class. The
indexer retains orchestration and the GPU consumer it already owns, so the
single-consumer constraint is untouched. Extraction is mechanical and
behaviour-preserving; the suite is the oracle.

**Drift owner.** One collaborator owns the full drift lifecycle: deciding a
path has drifted, dropping its published points, and removing the units that
claimed them, in that order. Today that ordering is documented in a docstring
and enforced by nothing. Concentrating it in one component makes the ordering
a property of the type rather than a convention, and gives the "which layer"
question an answer that survives the next change.

**Fix.** The ledger's collision becomes a distinguishable signal rather than an
opaque state error, so the orchestration layer can tell a racing path from a
genuine invariant breach. On that signal the run asks the drift owner to
supersede the path and re-records it. Retry is bounded per path; on exhaustion
the path is deferred to the next generation and the run completes rather than
aborts. A cheap pre-record drift check stays as a filter that keeps the common
case off the signal path entirely.

**Gate.** The module-length check moves to failing at a threshold the seamed
tree meets, restarting the ratchet its own documentation describes.

## Rationale

The knockout is that detection and remedy must reason over the same evidence at
the same instant, and no arrangement of a pre-dispatch snapshot achieves that
(`2026-07-25-index-resume-drift-race-research`). Only a component that both
observes the collision and owns the supersede can close the window rather than
narrow it. That component cannot be the class that already holds every other
concern, because the remedy's storage-before-ledger ordering is exactly the
kind of invariant a 115-method class cannot express or defend.

Seaming is therefore not opportunistic cleanup attached to a bug fix; it is the
precondition that makes the fix statable. The alternative — a seventh concern
in the same class — reproduces the conditions that produced the defect, and the
gate evidence shows those conditions compound silently rather than announcing
themselves.

## Consequences

The window closes by construction rather than by timing, and a busy tree
degrades to a bounded per-path retry instead of a failed run. The drift
ordering becomes enforceable. The "which layer" question gains a durable
answer.

Honestly framed: this is a large refactor of the most load-bearing module in
the indexer, undertaken to fix one defect. The risk is real and concentrated in
behaviour preservation, which is why extraction is mechanical, ordered ahead of
the fix, and gated on an unchanged suite. Expect the module count to grow and
some call sites to become less direct.

The bounded retry introduces a new failure mode: a pathologically hot path can
exhaust its budget every generation and stay stale indefinitely. Deferral makes
that visible as a stale path rather than a failed run, which is the better
failure. A deferred path emits a warning naming the path and the exhausted
budget; silent deferral is not acceptable.

Turning the length gate to failing will surface other modules over threshold.
That is the point, and it will cost work this record does not scope.

This record decides the seam and the drift owner for the code index path. The
circuit-breaker accounting for drift outcomes is decided by
`2026-07-25-index-drift-circuit-accounting-adr`, and the document index path's
resume semantics by `2026-07-25-document-index-drift-parity-adr`. Each is a
decision in its own right and carries its own record.
