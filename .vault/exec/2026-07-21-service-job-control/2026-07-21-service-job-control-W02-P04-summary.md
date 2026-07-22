---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` `W02.P04` summary

Vault indexing now accepts cooperative control through phase, bounded parsing,
GPU slice, storage mutation, and metadata boundaries while keeping clean rebuild
publication indivisible.

- Modified: `src/vaultspec_rag/indexer/_streaming.py`
- Modified: `src/vaultspec_rag/indexer/_vault_indexer.py`
- Created: `src/vaultspec_rag/tests/integration/test_index_job_control.py`

## Description

Streaming checks the same no-op-default control token immediately before and
after each bounded forward-pass lock. Vault full, incremental, and scoped paths
propagate that token through scanning, bounded parsing, streaming, cleanup, and
atomic metadata writes. Clean rebuilds reject already-pending control before a
drop and defer requests arriving after the drop until replacement points, stale
cleanup, and metadata are valid.

Real-behavior integration tests use production indexing and embedding methods,
real files, local Qdrant, real locks, and a tiny CPU SentenceTransformer backend.
They prove pause and cancellation between published slices and observe an empty
clean collection without acknowledging pause until all IDs, revised content,
and revised metadata are published.

Ruff, Ruff formatting, ty, strict BasedPyright, and `git diff --check` passed
throughout the Phase. The final gate passed 3 integration cases, 17 adjacent
run-control cases, and 106 indexer unit cases. Independent review found and
resolved S11's initially unbounded parse-drain issue; final S11 and S12 reviews
reported no Critical or High findings. CUDA verification was not retried after
the recorded OOM because the CPU-backed production path proves these control
and publication contracts without an unsafe live-GPU forward pass.
