---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:9a4189572be68eca7389793bc010decfd04bffed4ceae7fdfb47eb2fb8dab41a'
step_id: 'S50'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove rebuild-required behavior and remediation across service and adapters

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py`

## Changes

- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py`
- `verify:` `uv run pytest -m unit src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py` -> `pass`
- `verify:` `uv run pytest --collect-only src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
