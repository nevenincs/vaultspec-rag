---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:491de2715a68e2beeeed7d1275234b66fe5a1b22b512129200e7ea5155b9741f'
step_id: 'S10'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Inject one registry-allocated readiness revision after each canonical document generation publication succeeds

## Scope

- `src/vaultspec_rag/indexer/_document_indexer.py`
- `src/vaultspec_rag/service.py`
- `and src/vaultspec_rag/server/_search_readiness.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `M` `src/vaultspec_rag/service.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W01-P03-S10.md`
- `verify:` `uv run ruff format --check src/vaultspec_rag/indexer/_document_indexer.py src/vaultspec_rag/service.py src/vaultspec_rag/server/_search_readiness.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/indexer/_document_indexer.py src/vaultspec_rag/service.py src/vaultspec_rag/server/_search_readiness.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/indexer/_document_indexer.py src/vaultspec_rag/service.py src/vaultspec_rag/server/_search_readiness.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_document_checkpoint.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_document_index_escalation.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_indexer_unit.py -k "document"` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_scan_cache.py -k "document"` -> `pass`

## Notes

`uv run pytest -q src/vaultspec_rag/tests/integration/test_document_lifecycle.py` exited 1 before collection because no compatible resident machine-pointer service was available; no tests ran.
