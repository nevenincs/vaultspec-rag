---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:a8fe4d312c1086fc0862c89183ad4e642bbd2961bd2b847508f2eebfae61047d'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# `managed-log-contract` `W01.P02` summary

The Qdrant supervisor now drains child output through a secure bounded rotating sink while retaining an independent diagnostic ring.

- Modified: `src/vaultspec_rag/qdrant_runtime/_supervise.py`
- Modified: `src/vaultspec_rag/tests/test_qdrant_supervise_diagnostics.py`

## Description

Real-file and real-subprocess tests cover rollover, sparse retention, persistence failure, inherited pipes, single-writer refusal, and safe respawn. Ten focused tests and independent re-review pass.
