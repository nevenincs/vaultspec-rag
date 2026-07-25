---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S04'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Extract chunk production and submission into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Ground by meaning first, and prove no chunk-production owner already exists.
- Move worker planning, work partitioning, and the batch, serial, and pooled
  producers onto one collaborator.
- Move the bounded weighted segment queue and segment submission onto the same
  collaborator, because they are the same back-pressure loop.
- Delete the single-file future handler that had no callers, and the scoped
  preprocess recorder only it reached.
- Repoint every test that drove the moved methods at the production path.

## Outcome

Semantic search grounded the step before any edit. The query - chunk
production and submission phrased as behaviour plus domain nouns, restricted to
production code - returned ten hits, every one of them inside
`src/vaultspec_rag/indexer/_codebase_indexer.py`: the serial producer at
`:1117`, the result sink at `:1899`, failure classification at `:1788`, segment
measurement at `:519`, the bounded queue's admission accounting at `:196` and
its put at `:230`, and the chunk-and-embed phase body at `:2089`. Nothing
outside that one module answered the query, which is what established that no
collaborator existed to extend and the work was an extraction rather than a
second implementation.

Production and submission moved together. They are one back-pressure loop: the
producers reach the encode side only through the publish callback, and that
callback blocks on the bounded queue. Splitting them would have put a queue
boundary between two halves that must agree on when to stop, which is the
coupling the bound exists to express.

The producers no longer know about the GPU consumer, the run checkpoint, or the
preprocess and support accounting. Those run in the sink the caller supplies,
so a caller wanting results without an encode pipeline passes its own sink and
still drives the shipped code.

The move collapsed two dead paths rather than carrying them across. The
single-file future handler had no caller anywhere in the tree, and the scoped
preprocess recorder was reached only from inside it, so both went. Reconciling
the preserved branch against this tree also found a drift module that a rescue
merge had left with no importer at all, beside the drift owner that actually
ships; it went in the same change.

The module the seam came out of fell from 3292 lines to 2641, into a 725-line
collaborator.

Gates: lint clean, format clean, type check reports no diagnostics. The
indexer suite is green at 210 tests, against a 193-test pre-change baseline
over the same modules plus the streaming-segment module the queue moved to.

## Notes

No forwarding shim, delegating wrapper, or compatibility alias was added, and
the module the symbols left keeps no re-export of them. Tests were repointed in
the same change that removed what they exercised.

The error and fallback branches were run, not just the happy path: preprocess
abort propagation, the queue-capacity rejection, the serial fallbacks, and the
fresh-interpreter check that importing the chunk worker leaves torch out of
`sys.modules` - seventeen tests covering those paths pass.

The extraction introduced no function-local import on a cold branch, which is
the failure mode a de-shim invites here because lint and the type checker both
accept one. Every function-local import in the new module sits on a hot path:
the queue's threading import runs on construction, and the config reads run on
every worker-planning call.

One coverage gap is pre-existing and was not closed: no test drives the broken
process pool fallback in either producer, so that branch is exercised only in
production.
