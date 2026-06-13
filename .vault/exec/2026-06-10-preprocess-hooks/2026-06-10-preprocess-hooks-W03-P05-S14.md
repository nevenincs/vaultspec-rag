---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S14'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add a fresh-interpreter regression test that the worker import chain stays torch-free with preprocess wired (D6)

## Scope

- `src/vaultspec_rag/tests/test_preprocess_worker.py`

## Description

Added `test_preprocess_worker.py` (6 tests): chunk_file produces preproc chunks with
anchor/locator/source_path/preprocessor_id and unique ids; chunk_and_hash_file marks
`preprocess_status="ok"`; a cache hit skips re-running the extractor (script deleted between
calls); an unmatched file chunks normally; the context pickles; and a fresh-interpreter
subprocess asserts importing the worker plus all three preprocess modules leaves `torch`
out of `sys.modules` (the `index-workers-stay-cpu-only` guard with preprocess wired) (D6).

## Outcome

6/6 pass; the existing torch-free guard in `test_chunk_worker_parity.py` also still passes.

## Notes

Real subprocess extractor fixture; no mocks.
