---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:56c81572491a112a0d2253237e1cd10a324eacaa5202f197550742f2e99df407'
step_id: 'S23'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Extend domain outcomes with immutable source readiness and derive a lossless combined aggregate

## Scope

- `src/vaultspec_rag/search/_outcomes.py`

## Changes

- `M` `src/vaultspec_rag/search/_outcomes.py`
- `M` `src/vaultspec_rag/tests/test_cli_search.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_cli_search.py -q` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/search/_outcomes.py src/vaultspec_rag/tests/test_cli_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/search/_outcomes.py src/vaultspec_rag/tests/test_cli_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/search/_outcomes.py src/vaultspec_rag/tests/test_cli_search.py` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

The staged S24 type gate reports five `source_fact` omissions in `src/vaultspec_rag/_public_search.py`. The staged S26 outcome suite has 16 passing and 2 failing tests because its legacy fixtures do not yet supply the required source facts.
