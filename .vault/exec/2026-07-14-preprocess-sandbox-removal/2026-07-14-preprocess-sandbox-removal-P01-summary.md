---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# `preprocess-sandbox-removal` `P01` summary

All seven Steps closed in one commit. The OS containment layer is gone: both platform backends deleted, the probe/resolution/staging/fail-closed machinery removed, and the runner rewired to launch hooks directly against the original source path under a curated env with a fresh scratch cwd. Every bound (timeout, output caps, schema validation, on_error dispositions, argv hygiene) preserved.

- Modified: `src/vaultspec_rag/indexer/_hook_sandbox.py`
- Deleted: `src/vaultspec_rag/indexer/_hook_sandbox_windows.py`
- Deleted: `src/vaultspec_rag/indexer/_hook_sandbox_posix.py`
- Modified: `src/vaultspec_rag/indexer/_preprocess_runner.py`
- Modified: `src/vaultspec_rag/indexer/_chunk_worker.py`
- Modified: `src/vaultspec_rag/indexer/_preprocess_config.py`
- Modified: `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

Deleted the AppContainer and bwrap/seatbelt backends with their icacls grants and per-worker memos; removed source staging and staged-path remapping so hooks read the real file; dropped the fail-closed refusal and the server_mode/unsandboxed plumbing end to end. The subprocess grandchild boundary (CPU/CUDA correctness) is untouched.
