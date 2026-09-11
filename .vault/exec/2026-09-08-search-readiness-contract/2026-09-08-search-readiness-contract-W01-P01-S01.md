---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:c1b3bad84936863d38f3f1259ff657d735128a9b4c35cf7412b0b9411229c23c'
step_id: 'S01'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Define typed availability freshness authority wait policy generation evidence source fact and aggregate serialization

## Scope

- `src/vaultspec_rag/_search_state.py`

## Changes

- `M` `src/vaultspec_rag/_search_state.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W01-P01-S01.md`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/_search_state.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/_search_state.py` -> `pass`
- `verify:` `uv run --no-sync python -m ty check src/vaultspec_rag/_search_state.py` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_service_search_diagnostics.py src/vaultspec_rag/tests/test_search_availability.py -q --tb=short` -> `pass`
