---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S06'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# move vault document parsing into the spawn-safe CPU worker pool keeping every worker torch-free

## Scope

- `src/vaultspec_rag/indexer/_vault_indexer.py`
- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Record written after the fact from the landed change; the work shipped in
  commit `25f73a6e` together with the vault writer-side overlap of S07.
- Parallelise the whole-corpus vault markdown split across the same
  spawn-safe CPU worker pattern the code path uses: the split entry point
  `split_documents` in `src/vaultspec_rag/indexer/_vault_prep.py` fans
  contiguous document batches at `_split_document_batch` into a spawn pool
  and falls back to the serial split below the byte threshold.
- Keep the pool auto-gated on the same source-byte threshold as code
  chunking, so small corpora never pay spawn startup.
- Keep every worker torch-free: the batch entry point reaches only the
  markdown split, and a fresh-interpreter import test asserts `torch` stays
  out of `sys.modules` after importing the worker chain.
- Call the parallel split from the vault stream in
  `src/vaultspec_rag/indexer/_streaming.py`, replacing the in-loop
  single-threaded split.

## Outcome

Landed. Vault parsing runs in CPU-only spawn workers with the serial path
retained below the auto threshold; worker torch-freeness is test-asserted
in `src/vaultspec_rag/tests/test_vault_split_parallel.py`.

## Notes

- No measured parse-stage number is recorded here: the research baseline for
  the serial stage is 458 s on a rebuild-class vault corpus, but the
  post-change parse stage was never timed on that corpus, so the speedup is
  unquantified. The plan's measurement steps own that number.
- This record was scaffolded during the plan closeout, not during execution;
  its evidence is the commit diff and the tests it added, not a live
  observation of the run.
