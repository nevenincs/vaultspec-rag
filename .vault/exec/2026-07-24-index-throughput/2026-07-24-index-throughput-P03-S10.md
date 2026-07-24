---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S10'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# add overlap tests including mutation proofs that the single-consumer contract binds: a second consumer or lock-held-across-non-forward mutation goes red on the intended assertion, restore green, recorded

## Scope

- `src/vaultspec_rag/tests/` streaming suites\`

## Description

- Land the overlap suites (`tests/test_slice_writer_overlap.py`, `tests/test_vault_split_parallel.py`) on main via the P03 merge (commit `eadef36b`), composing the writer seam with donor reuse and the ingest wait policy on the same functions.
- Re-run all four writer-side mutation proofs on the MERGED tree, each an uninterrupted red-green sequence with the tree verified byte-identical after restore:
- Inline-upsert mutation (writer bypassed in the vault slice) - red on the intended assertions ("no encode started while an upsert was in flight" and upsert-thread-equals-caller); restore, 4/4 green.
- Second-writer-thread mutation (a second daemon consumer draining the queue) - red on `len(set(threads)) == 1` in both the overlap and contract tests; restore, 8/8 green.
- Wedge mutation (shutdown deadline removed from `close()`) - red on "close() hung past its shutdown bound", proving the liveness guard binds; restore, green.
- Swallowed-write-failure mutation (writer failure recording removed) - red on `DID NOT RAISE RuntimeError` in both failure-propagation tests; restore, 8/8 green.
- Add the binding composition proof `TestBarrierComposesWithSliceWriter` (commit `60f0e11b`): a wrong-named-vector upsert injected ON the writer thread (acknowledged, never applied) must fail the production vault rebuild at the terminal barrier, after the writer queue drains and before stale-purge or metadata publish; recorded thread idents prove the injection rode the writer.

## Outcome

The single-consumer, ordered-writer, bounded-shutdown, and failure-propagation contracts all hold on the merged tree with reuse and the wait policy composed in. Compose-proof mutation: neutralizing the barrier's exact-count comparison turned the test red on the missing rejection (`DID NOT RAISE IngestVerificationError`); restored, the full barrier suite is 6/6 green.

## Notes

The overlap fake stores were updated to accept the store's new `wait` keyword - the one composition seam the merge surfaced in tests.
