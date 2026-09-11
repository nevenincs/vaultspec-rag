---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:ea5273cc59da89f3eed2a671d03496b47ecbe68ec51523bc0cc34ca13f96787d'
step_id: 'S39'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove JSON parity policy validation updating success typed failure wait cause and identifier bounds

## Scope

- `src/vaultspec_rag/tests/test_cli_search.py`

## Changes

- `M` `src/vaultspec_rag/cli/_search.py`
- `M` `src/vaultspec_rag/tests/test_cli_search.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_cli_search.py -q` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_cli_search_safety.py -q -k "not test_search_mcp_timeout_diagnostics and not test_search_timeout_human_output_is_plain_diagnostic and not test_search_timeout_missing_health_status_is_reported_absence and not test_search_timeout_jobs_error_is_reported_absence and not test_search_timeout_json_preserves_backend_diagnostics"` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/cli/_search.py src/vaultspec_rag/tests/test_cli_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/cli/_search.py src/vaultspec_rag/tests/test_cli_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/cli/_search.py src/vaultspec_rag/tests/test_cli_search.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/cli/_search.py src/vaultspec_rag/tests/test_cli_search.py` -> `pass`

## Notes

Five stale timeout-render assertions remain assigned to S40:
`test_search_mcp_timeout_diagnostics`,
`test_search_timeout_human_output_is_plain_diagnostic`,
`test_search_timeout_missing_health_status_is_reported_absence`,
`test_search_timeout_jobs_error_is_reported_absence`, and
`test_search_timeout_json_preserves_backend_diagnostics`.
