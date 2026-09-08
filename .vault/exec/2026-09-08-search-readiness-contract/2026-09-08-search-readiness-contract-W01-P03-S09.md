---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:b1c55617f22633c0c2e99ac00bc718888cd90e5d4b7adec7dd28a1f55d436d61'
step_id: 'S09'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Own the readiness registry lifecycle and inject one registry-allocated revision emission after canonical code publication succeeds

## Scope

- `src/vaultspec_rag/server/_search_readiness.py`
- `src/vaultspec_rag/service.py`
- `src/vaultspec_rag/server/_lifespan.py`
- `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `and src/vaultspec_rag/indexer/_generation_lifecycle.py`

## Changes

- `M` `src/vaultspec_rag/server/_search_readiness.py`
- `M` `src/vaultspec_rag/service.py`
- `M` `src/vaultspec_rag/server/_lifespan.py`
- `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `M` `src/vaultspec_rag/indexer/_generation_lifecycle.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W01-P03-S09.md`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_search_readiness.py src/vaultspec_rag/service.py src/vaultspec_rag/server/_lifespan.py src/vaultspec_rag/indexer/_codebase_indexer.py src/vaultspec_rag/indexer/_generation_lifecycle.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_search_readiness.py src/vaultspec_rag/service.py src/vaultspec_rag/server/_lifespan.py src/vaultspec_rag/indexer/_codebase_indexer.py src/vaultspec_rag/indexer/_generation_lifecycle.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_search_readiness.py src/vaultspec_rag/service.py src/vaultspec_rag/server/_lifespan.py src/vaultspec_rag/indexer/_codebase_indexer.py src/vaultspec_rag/indexer/_generation_lifecycle.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_run_checkpoint.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_service_registry_recovery.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_server.py -k "DaemonLifecycleHelpers or ServiceRegistryIntegration"` -> `pass`
