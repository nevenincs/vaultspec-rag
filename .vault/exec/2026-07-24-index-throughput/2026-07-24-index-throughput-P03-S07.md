---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:94555faa7c7c4ffe0c5711713a6fe7c6ca76408cec2ee1de6aae4f28af5ff7d4'
step_id: 'S07'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# adopt the bounded-queue producer/consumer pattern for the vault encode path with sentinel shutdown and time-bounded joins

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`
- `src/vaultspec_rag/indexer/_vault_indexer.py`

## Description

- Record written after the fact from the landed change; the work shipped in
  commit `25f73a6e`.
- Replace the vault path's synchronous slice loop with a writer-side bounded
  queue in `src/vaultspec_rag/indexer/_streaming.py`: the calling thread
  stays the only encode (GPU) thread, and one FIFO writer thread owns every
  upsert, so slice N+1 encodes while slice N is stored.
- Shut the writer down on a sentinel put that is liveness-guarded and timed,
  followed by a bounded join that logs and raises when a store call is
  wedged rather than hanging the run.
- Keep the per-slice CUDA cache flush on the encoding thread so the flush
  cadence semantics are unchanged by the overlap.
- Propagate a writer-thread store failure into the calling run before any
  terminal metadata is produced.

## Outcome

Landed. The vault path overlaps encode with storage under one GPU consumer
thread and one writer thread. The direction of the queue is inverted from the
plan's wording, in that the writer side is queued rather than the producer
side, because the vault path's producer is the CPU split that S06 moved into
the worker pool; the contract the plan asked for (encode of slice N+1 overlapping
the storage of slice N, single GPU consumer, sentinel shutdown, time-bounded
joins) is the one that shipped.

Guard-test failure proofs recorded with the commit, each a single
mutate-red-restore-green sequence:

- inline-upsert mutation: red on "no encode started while an upsert was in
  flight" and on the upsert-thread-is-not-the-encode-thread assertion.
- second-writer-thread mutation: red on the single-upsert-thread assertion.
- unbounded sentinel/join mutation: red on the test's own liveness guard
  that close() hung past its shutdown bound.
- swallowed-write-failure mutation: red on DID NOT RAISE in both
  failure-propagation tests.

## Notes

- No throughput number is recorded here. The overlap is proven behavioural by
  test; its wall-clock effect on a rebuild-class corpus was not measured in
  this Step and belongs to the plan's measurement Steps.
- This record was scaffolded during the plan closeout; its evidence is the
  commit diff, its message, and the slice-writer overlap suite under
  `src/vaultspec_rag/tests/`.
