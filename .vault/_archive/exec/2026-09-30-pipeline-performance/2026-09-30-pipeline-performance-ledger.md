---
tags:
  - '#exec'
  - '#pipeline-performance'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:77736523943690c44bbbd6f3f562c262a09baeeb3d3baea69b74c676f5dd8eb4'
related:
  - "[[2026-09-30-pipeline-performance-plan]]"
---

# `pipeline-performance` ledger

## Changes

- `S01` `A` `dev/gpu_pipeline_profile.py`
- `S01` `A` `dev/_profile_tools.py`
- `S01` `A` `dev/_profile_workloads.py`
- `S01` `A` `src/vaultspec_rag/tests/test_gpu_profile_harness.py`
- `S01` `A` `.vault/research/2026-09-30-pipeline-performance-research.md`
- `S01` `A` `.vault/plan/2026-09-30-pipeline-performance-plan.md`
- `S01` `A` `.vault/index/pipeline-performance.index.md`
- `S01` `verify:` `pytest test_gpu_profile_harness.py: 11 tests` -> `pass`
- `S01` `verify:` `ruff check src dev tools` -> `pass`
- `S01` `verify:` `ruff format --check src dev tools` -> `pass`
- `S01` `verify:` `ty check profiling tools and harness tests` -> `pass`
- `S01` `verify:` `profile tool guard mutation intended failures and restored passes: 5 cases` -> `pass`
- `S01` `verify:` `cpu profiling CLI unprofiled smoke: 7 rounds` -> `pass`
- `S01` `by:` `vaultspec-high-executor`
- `S01` `A` `.vault/audit/2026-09-30-pipeline-performance-audit.md`
- `S01` `verify:` `pytest profiling harness and AST unit tests: 74 tests` -> `pass`
- `S01` `verify:` `consumer teardown guard intended failures and restored passes: 2 cases` -> `pass`
- `S01` `verify:` `independent re-review closes borrowed-lifetime high finding` -> `pass`
- `S02` `M` `src/vaultspec_rag/indexer/_ast_chunker.py`
- `S02` `M` `src/vaultspec_rag/tests/test_indexer_unit_chunking.py`
- `S02` `M` `.vault/research/2026-09-30-pipeline-performance-research.md`
- `S02` `verify:` `exact AST tuple parity on 820 sources at 5 budgets` -> `pass`
- `S02` `verify:` `20 paired CPU rounds and 36 default-budget repeat pairs` -> `pass`
- `S02` `verify:` `pytest profiling harness and AST unit tests: 74 tests` -> `pass`
- `S02` `by:` `vaultspec-high-executor`

## Notes

- `S01` An externally owned merge into this worktree delays the explicit-path Step commit. No foreign staged files were modified or included. Native execution is deferred until the reviewed pins are committed.
- `S01` Explicit-path commit and native execution remain deferred until the externally owned merge is finished. Overall review is PENDING for real native/CUDA evidence.
- `S02` Partial Step only: CUDA/native inference measurements and sparse budget/parity selection remain blocked by active service tickets and pending external merge. S02 stays unchecked; no sparse batch/precision/backend default changed.
