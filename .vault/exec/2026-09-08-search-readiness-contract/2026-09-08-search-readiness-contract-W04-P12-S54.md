---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-14'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:b23ad38cc08f857879d5c7409d12373652f9e2ba1f236ae6c6c6b20d26bc514f'
step_id: 'S54'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---


# Prove retrieval ordering ranking output and result shape remain unchanged

## Scope

- `src/vaultspec_rag/tests/integration/test_search_result_shape.py`

## Changes

- `M` `src/vaultspec_rag/server/_models.py`
- `M` `src/vaultspec_rag/tests/integration/test_search_result_shape.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/integration/test_search_result_shape.py -q` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_server_document_models.py src/vaultspec_rag/tests/test_http_search_errors.py -q` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_models.py src/vaultspec_rag/tests/integration/test_search_result_shape.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_models.py src/vaultspec_rag/tests/integration/test_search_result_shape.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_models.py src/vaultspec_rag/tests/integration/test_search_result_shape.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/server/_models.py src/vaultspec_rag/tests/integration/test_search_result_shape.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
