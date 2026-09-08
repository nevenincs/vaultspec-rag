---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:2ff5a5aeb3d886c1f2b99141ed68b0f6c5b05d1e65aab35f8f8f4f10bb48be88'
step_id: 'S30'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Preserve GPU-compute and project-lease measurements as distinct named causes without widening lock scope

## Scope

- `src/vaultspec_rag/search/_searcher.py`

## Changes

- `M` `src/vaultspec_rag/search/_searcher.py`
- `verify:` `uv run ruff check src/vaultspec_rag/search/_searcher.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/search/_searcher.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/search/_searcher.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_search_unit.py src/vaultspec_rag/tests/test_search_quality_fixes_unit.py src/vaultspec_rag/tests/test_service_search_diagnostics.py -q` -> `pass`
- `verify:` `git diff --check -- src/vaultspec_rag/search/_searcher.py` -> `pass`
