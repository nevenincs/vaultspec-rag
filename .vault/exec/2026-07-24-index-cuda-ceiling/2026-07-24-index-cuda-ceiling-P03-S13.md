---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:7bf8b812c74b1dba8787ef4365939b8c188c7f7cc589ae95b343e427f075b28b'
step_id: 'S13'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# thread the captured per-job forward peak into the memory budget as the maximum across the job's brackets

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Add `record_forward_peak_mb` to `MemoryBudget` in `src/vaultspec_rag/memory_probe.py`: thread-safe maximum accumulation of lock-bracketed forward peaks into the job's own budget.
- Add the thread-local `record_forward_peaks` router; the code consumer thread registers it around `encode_and_upsert_code_slice` in `src/vaultspec_rag/indexer/_codebase_indexer.py`, and the document path registers it around `encode_and_upsert_document_slice` in `src/vaultspec_rag/indexer/_document_indexer.py`.

## Outcome

Attribution is by thread: a job's forwards run on the thread that entered its recorder context, so a completed bracket credits the owning job and no other. The retained value is the maximum across all of the job's brackets.

## Notes

None.
