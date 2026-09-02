---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-02'
body_schema: 'body-v1'
body_hash: 'sha256:d1590e7e1fe7f9a727c18c94e56729b726b040419890f0e3d3674eacbd2dccad'
step_id: 'S06'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Prove a live reindex timeout override reaches the HTTP request

## Scope

- `src/vaultspec_rag/tests/test_search_timeout.py`

## Description

- Consolidate the search and admin environment cleanup into one test-local helper.
- Drive `_try_http_reindex` across the real loopback HTTP transport against a delayed
  `/reindex` response under `VAULTSPEC_RAG_REINDEX_TIMEOUT=0.01`.
- Assert the resolved whole-call deadline reaches the HTTP request rather than accepting
  the delayed success response.
- Demonstrate the guard by temporarily replacing the runtime resolver with the default,
  observe its named `result["ok"] is False` assertion fail on a successful response,
  restore immediately, and observe the restored test pass.

## Outcome

The live override is exercised at the production HTTP boundary without a test-only
production seam. The guard's broken direction fails on the intended assertion; the
restored direction passes.

## Notes

`uv run --no-sync ruff check src/vaultspec_rag`, `uv run --no-sync ruff format --check src/vaultspec_rag/tests/test_search_timeout.py`, `uv run --no-sync ty check src/vaultspec_rag/tests/test_search_timeout.py`, and `uv run --no-sync pytest src/vaultspec_rag/tests/test_search_timeout.py -q` passed.
