---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S05'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Extract generation and ledger lifecycle into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Ground by meaning first, and prove no generation-lifecycle owner already
  exists.
- Move opening a generation, the two evidence predicates, and publication of a
  finished one onto one collaborator.
- Bind the drift owner to the generation inside the same collaborator, so the
  two are created at one instant.
- Give the pipeline limits type a run-configuration projection, so the
  lifecycle never imports the indexer back.
- Repoint the tests that drove the moved methods at the production path.

## Outcome

Semantic search grounded the step before any edit. The query - resuming a
pending finalization and detecting lost checkpoint evidence, restricted to
production code - returned the lifecycle cluster in
`src/vaultspec_rag/indexer/_codebase_indexer.py` at `:1657` for the
evidence-lost predicate and `:1730` for the resumed finalization, the three
call sites that open a checkpoint at `:2577`, `:3121`, and `:1624`, the
carried-evidence predicate at `:2817`, and the point-evidence helper at
`:2243`. The only hits outside the indexer were the checkpoint type itself,
which is the collaborator's dependency rather than a competing owner. That
established the cluster had no existing home.

Opening a generation, judging whether resumed evidence still describes
anything, and publishing a finished one are one authority: each answer measures
what the ledger claims against what storage actually holds. Held together, a
generation can be retired and reopened in one place, instead of every caller
remembering to check first before resuming.

The lifecycle owns the open generation, so it owns the drift owner bound to it.
The two are now created at the same instant and neither can outlive the other,
which is what the ownership boundary was for.

Result assembly stayed on the indexer. Publication is lifecycle work; building
the result from run counters, reuse telemetry, and device identity is not, so
the collaborator reports whether it published and the caller assembles what it
already holds.

A circular import was avoided by direction rather than by a shim: the limits
type projects the run configuration a resumed generation must match, so the
lifecycle receives a built configuration and never imports the module it was
extracted from.

The module the seam came out of fell from 2641 lines to 2465. Across both
extractions in this Phase it fell from 3292, into a 725-line production
collaborator and a 315-line lifecycle one.

Gates: lint clean, format clean, type check reports no diagnostics across the
indexer package. The full non-GPU unit suite is green at 2748 tests.

## Notes

No forwarding shim, delegating wrapper, or compatibility alias was added. The
one delegating property that remains - the last-checkpoint accessor - is the
indexer's own public surface, consumed by job dispatch, not a compatibility
alias for a moved symbol.

A cut left a static-method decorator attached to the method that followed the
one it belonged to. Type checking did not catch it because the orphaned method
takes self as its first parameter either way; it was caught by reading the diff
and repaired before the suite ran.

The error and fallback branches were run, not just the happy path: the five
tests pinning the carried-evidence predicate cover its cannot-tell, shortfall,
and uncountable-store branches and all pass.

As in the previous extraction, no function-local import landed on a cold
branch. The lifecycle's single function-local import reads config while opening
a checkpoint, which every run does.
