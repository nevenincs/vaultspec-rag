---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:dcfcee9481f4ba8bd3fce0cfc5aea4d6a2290cff38ab48ad4e00688e475d01fa'
step_id: 'S08'
related:
  - '[[2026-07-21-large-index-resilience-plan]]'
---

# Convert full indexing to weighted production

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `src/vaultspec_rag/indexer/_chunk_worker.py`
- `src/vaultspec_rag/indexer/_preprocess_glue.py`
- `src/vaultspec_rag/tests/test_streaming_segments.py`
- `src/vaultspec_rag/tests/test_chunk_worker_parity.py`
- `src/vaultspec_rag/tests/test_preprocess_batch.py`

## Description

- Replace the full indexer's count-only list queue and fixed-count accumulator with
  file-local `CodeFileSegment` production, exact chunk/byte queue backpressure, and a
  separately bounded active `WeightedCodeSlice`.
- Drain each worker result destructively so already-enqueued chunks leave the source list,
  keep preprocessing results file-local, and length-sort only the active slice.
- Remove the full path's outer `embedding_batch_size` cap. Segment and slice capacity now
  come from the index segment and queue limits; the model's inner batch remains governed by
  `embedding_code_encode_batch_size`.
- Keep the CPU producer window at two futures per worker and retain one GPU consumer.
  Dense/sparse cleanup, synchronous storage, and ID publication remain at the bounded slice
  boundary.
- Propagate ordinary, pooled, and batch-passthrough source-read and chunk failures. A full
  rebuild no longer publishes a failed file as an intentional zero-chunk omission before
  stale-ID reconciliation.
- Sample full-path memory immediately before encoding and after synchronous storage, outside
  the forward-pass lock, and capture diagnostic or cleanup failures through the consumer's
  original error channel.

## Outcome

Full indexing no longer retains a corpus-sized vector-bearing chunk list, creates a
corpus-sized padding sort, or admits queue work by item count alone. Queued work is bounded by
configured chunks and estimated bytes. The active slice is independently bounded and may pull
ahead at most one non-vectorized segment so it can detect a flush boundary without deadlock.
`new_ids` advances only after the matching synchronous upsert succeeds.

The incident-floor producer benchmark streamed 83,624 files and 250,872 chunks through the
production destructive drain, segmenter, weighted queue, and slice packer in 10.627 seconds
(23,608 chunks per second). It emitted 4,646 slices; both the maximum active slice and observed
queue high-water were 54 chunks and 133,936,146 estimated bytes. Traced Python peak memory was
0.369 MiB, demonstrating that the primitive's retained state does not grow with the corpus.

## Verification

- 142 focused indexer, segment, worker, centralized Torch-loading, and batch-failure tests
  pass locally; an independent run reported 163 targeted tests passing.
- Real missing-file and external batch-hook deletion tests prove ordinary and passthrough
  failures propagate rather than authorize stale-point deletion.
- Ruff formatting and lint, Ty, BasedPyright, compile, diff, and targeted complexity checks
  pass. The changed indexer has no complexity offender; the repository-wide gate remains red
  only on unrelated dirty files.
- Independent performance and architecture review reports no unresolved Critical or High
  finding after catching and driving fixes for a queue deadlock, a legacy outer batch cap, and
  suppressed file failures.

## Notes

Worker IPC still materializes one whole-file result, or one fixed-size batch preprocessing
result, before main-process segmentation. That bound is independent of corpus size but is not
the downstream 8 MiB segment boundary. Scanned paths, metadata, ID sets, and stale-ID sorting
also remain corpus-sized non-vector state for the W02 ledger and finalization steps.

`S09` and `S10` still own both incremental producers. `S18` and `S19` own enforced low-memory
and blocked-consumer acceptance. The existing whole preprocess-batch test file contains an
unrelated nondeterministic concurrent log-append assertion and legacy monkeypatch usage; the
new real external-hook test passes independently. Real CUDA and Qdrant multi-segment
acceptance remains blocked by the occupied shared GPU and belongs to `S11`/`S18`.
