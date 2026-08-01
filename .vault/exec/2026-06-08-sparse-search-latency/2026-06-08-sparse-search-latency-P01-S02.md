---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-08'
modified: '2026-06-30'
body_hash: 'sha256:a839b5b64cb835e47c28a70aed8a8216f50e5f0f7f900c6319557e7650c7d193'
step_id: 'S02'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` P01.S02

## Description

- Passed `sparse_enabled` configuration to `VaultSearcher`.
- Skipped SPLADE `encode_query_sparse` execution when `sparse_enabled` is False.
- Updated `_encode_query` return type signature to `SparseResult | None`.

## Outcome

`_encode_query` successfully bypasses SPLADE computation when `sparse_enabled` is False.

## Notes

No issues encountered.
