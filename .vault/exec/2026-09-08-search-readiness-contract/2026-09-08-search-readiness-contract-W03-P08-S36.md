---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:74e08fc5581887b715207f2a7f410c6510f21630903f70548b521475d0adc929'
step_id: 'S36'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove payload propagation envelope passthrough transport-only failures and absence of client-derived readiness

## Scope

- `src/vaultspec_rag/tests/test_cli_search.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_cli_search.py`
- `M` `src/vaultspec_rag/tests/test_cli_search_safety.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_cli_search.py src/vaultspec_rag/tests/test_cli_search_safety.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_cli_search.py src/vaultspec_rag/tests/test_cli_search_safety.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_cli_search.py src/vaultspec_rag/tests/test_cli_search_safety.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/test_cli_search.py src/vaultspec_rag/tests/test_cli_search_safety.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_cli_search.py -q` -> `pass` (`55 passed`)
- `verify:` assigned payload fixtures in `src/vaultspec_rag/tests/test_cli_search_safety.py` -> `pass` (`5 passed`)
- `verify:` freshness payload, envelope passthrough, and transport-only timeout mutation proofs -> `red`, restored -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

`uv run pytest src/vaultspec_rag/tests/test_cli_search_safety.py -q` retained exactly five staged timeout-render failures assigned to S40: `test_search_mcp_timeout_diagnostics`, `test_search_timeout_human_output_is_plain_diagnostic`, `test_search_timeout_missing_health_status_is_reported_absence`, `test_search_timeout_jobs_error_is_reported_absence`, and `test_search_timeout_json_preserves_backend_diagnostics`.
