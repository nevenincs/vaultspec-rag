---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S07'
related:
  - '[[2026-07-21-large-index-resilience-plan]]'
---

# Define bounded file segments, weighted slices, CPU transfer, and immediate vector-field release

## Scope

- `src/vaultspec_rag/embeddings.py`
- `src/vaultspec_rag/indexer/_streaming.py`
- `src/vaultspec_rag/tests/test_streaming_segments.py`

## Description

- Define immutable, file-local segment units with deterministic ordinals, one final marker,
  exact byte weights, and strict transition validation across slice flushes.
- Estimate concurrent source, embedding input, payload, dense, sparse, and Python-container
  lifetimes. Sparse reservation uses the loaded model's fail-closed output dimension because
  the production SPLADE path applies no top-k pruning.
- Keep the 8 MiB durable segment budget distinct from the 128 MiB weighted slice budget so
  checkpoint granularity stays small while the active GPU consumer retains useful batching.
- Return dense indexing output on-device, release `gpu_lock`, transfer once to CPU, and then
  perform list conversion and synchronous Qdrant work outside the lock.
- Clear dense and sparse fields from real code and vault chunk objects after every successful
  store call and exceptional unwind.
- Remove the corpus-sized length-sorted copy while preserving padding efficiency through a
  sort of only the active bounded slice.

## Outcome

The streaming boundary now has an honest memory weight and a deterministic future ledger
unit. No segment crosses a file, no weighted slice splits or reorders a segment, and corrupt
ordinal or file-end transitions fail even when the corruption lands immediately after a
slice flush. Dense and sparse output lifetimes end at the synchronous store boundary instead
of remaining attached to corpus objects.

The 250,872-chunk incident-floor primitive benchmark produced 4,646 slices with a maximum of
54 chunks and 133,914,276 estimated bytes per slice. Packing took 7.753 seconds at 32,359
chunks per second with 0.067 MiB traced Python peak memory. Independent reproduction measured
7.658 seconds and 0.071 MiB peak. This preserves batching above the configured 32-chunk inner
encode batch while bounding durable units to 8 MiB.

## Verification

- 13 focused real-object segment, weighting, transition, release, explicit-override,
  NumPy, and Torch tests pass.
- 125 indexer, segment, and centralized Torch-loading tests pass.
- Ruff formatting and lint, Ty, BasedPyright, compile, lazy-import, and diff checks pass.
- The complexity report contains no threshold or nesting violation for the changed
  `_streaming.py`; the repository-wide gate remains red only on unrelated dirty files.
- Independent review initially found an unsafe 1,024-entry sparse cap and cross-flush sequence
  gap. Both were corrected. Final review found eager configuration resolution under explicit
  helper limits; that dependency was removed. Re-review reports no unresolved Critical or
  High finding.

## Notes

`S08` through `S10` still own removal of upstream full and incremental whole-list retention;
this Step defines and applies the bounded consumer-side primitives without claiming those
producer paths are complete. `S11` still owns real-CUDA acceptance. The pre-existing
reduced-signature sparse OOM test double remains intentionally unsupported; no production
fallback, skip, or expected failure was added for it.
