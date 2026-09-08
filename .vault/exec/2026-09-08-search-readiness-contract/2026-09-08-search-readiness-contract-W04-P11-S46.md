---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:034ced45c8768783d3eb440a7379408ab60d9ed3bed800c7a76feb7ff39d5878'
step_id: 'S46'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Define reusable current updating unavailable unverifiable rebuild timeout capacity backend empty and mixed scenarios

## Scope

- `src/vaultspec_rag/tests/_search_readiness_scenarios.py`

## Changes

- `A` `src/vaultspec_rag/tests/_search_readiness_scenarios.py`
- `verify:` `uv run python -c "from vaultspec_rag.tests._search_readiness_scenarios import SEARCH_READINESS_SCENARIOS; assert len(SEARCH_READINESS_SCENARIOS) == 10"` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/_search_readiness_scenarios.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/_search_readiness_scenarios.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/_search_readiness_scenarios.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/_search_readiness_scenarios.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
