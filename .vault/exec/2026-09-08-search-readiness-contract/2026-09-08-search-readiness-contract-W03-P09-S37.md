---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:54d776f6393594024e29fc172a0dec2377810e3d7fcd5bbe9249654df78e99d9'
step_id: 'S37'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Expose freshness policy and bounded duration on search commands with immediate defaults

## Scope

- `src/vaultspec_rag/cli/_search.py`

## Changes

- `M` `src/vaultspec_rag/cli/_search.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/cli/_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/cli/_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/cli/_search.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/cli/_search.py` -> `pass`
- `verify:` `uv run vaultspec-rag search --help` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_cli_search.py -q` -> `pass` (`55 passed`)
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_cli_search_safety.py -q -k "not search_mcp_timeout_diagnostics and not search_timeout_human_output_is_plain_diagnostic and not search_timeout_missing_health_status_is_reported_absence and not search_timeout_jobs_error_is_reported_absence and not search_timeout_json_preserves_backend_diagnostics"` -> `pass` (`21 passed`, `5 deselected`)
- `verify:` `git diff --check` -> `pass`

## Notes

`uv run pytest src/vaultspec_rag/tests/test_cli_search_safety.py -q` retains the five already planned S40 stale timeout-render expectations: `test_search_mcp_timeout_diagnostics`, `test_search_timeout_human_output_is_plain_diagnostic`, `test_search_timeout_missing_health_status_is_reported_absence`, `test_search_timeout_jobs_error_is_reported_absence`, and `test_search_timeout_json_preserves_backend_diagnostics`.
