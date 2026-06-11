---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S12'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Insert preprocess_decoded at the top of both chunk_file and chunk_and_hash_file (D6)

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

Added `preprocess_file()` and `_chunks_from_output()` to `_chunk_worker.py` and a
`preprocess_decoded` step at the top of both `chunk_file` and `chunk_and_hash_file` (after
read+hash, before decode/chunk). On a rule match the runner runs (cache-consulted); `ok`
output becomes `CodeChunk`s (units -> one chunk each with anchor + split locator; text ->
splitter chunks stamped with source_path/preprocessor_id); `skipped` yields no chunks;
`passthrough`/`none` fall through to ordinary chunking. `FileChunkResult` gained
`preprocess_status`/`preprocess_reason` (D6).

## Outcome

Worker produces searchable preproc chunks on both entrypoints; embed seam untouched; import
chain stays torch-free. Verified by `test_preprocess_worker.py` (6 tests).

## Notes

Per the approved W03 storage decision, preproc units are CodeChunks in the existing
collection (deviation from D12's separate collection; recorded in S18).
