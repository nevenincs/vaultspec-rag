---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-08'
modified: '2026-06-08'
step_id: 'S03'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` P01.S03

## Description

- Added `test_encode_query_respects_sparse_enabled` to `src/vaultspec_rag/tests/integration/test_search_integration.py`.
- Added `test_encode_query_sparse_enabled_true` to verify correct behavior when toggled.
- Verified that fallback bypasses sparse vector creation successfully.
- **Audit Fixes (2026-06-08)**:
  - Fixed `src/vaultspec_rag/store.py` (`VaultStore`) to natively route dense queries when `sparse_vector=None` instead of relying on `RrfQuery` exception fallback.
  - Added end-to-end integration tests `test_search_vault_sparse_disabled_end_to_end` and `test_search_codebase_sparse_disabled_end_to_end` to `src/vaultspec_rag/tests/integration/test_search_integration.py` to assert that exceptions are avoided and full paths work seamlessly with `sparse_enabled=False`.

## Outcome

Test coverage asserts the new fallback behavior. The RRF query issue is fully resolved with a native bypass when sparse search is disabled, and tests verify full codebase and vault search fallback paths.

## Notes

Addressed CRITICAL and HIGH issues identified during `P01` code review.
