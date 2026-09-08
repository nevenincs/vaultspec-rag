---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:534f509c33a5324cbc9416ff1b5349260e6f8dd26102d5203223c78705b807ec'
step_id: 'S13'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Mutation-prove waiter cleanup and job-terminal-not-publication guards

## Scope

- `src/vaultspec_rag/tests/test_search_readiness.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_search_readiness.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W01-P03-S13.md`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `git diff --exit-code -- src/vaultspec_rag/server/_search_readiness.py src/vaultspec_rag/job_manager/_control.py src/vaultspec_rag/service.py` -> `pass`
