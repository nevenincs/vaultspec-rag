---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:56aeac10a0a799b3fd07a73bcfce03c3e6d95974f42b01c8081da11a26d5799c'
step_id: 'S35'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Send caller policy and bound preserve canonical bodies and remove synthesized freshness diagnosis

## Scope

- `src/vaultspec_rag/serviceclient/_search_transport.py`

## Changes

- `M` `src/vaultspec_rag/serviceclient/_search_transport.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/serviceclient/_search_transport.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/serviceclient/_search_transport.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/serviceclient/_search_transport.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/serviceclient/_search_transport.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_cli_search.py -q` -> `pass` (`52 passed`)
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_http_search_errors.py -q` -> `pass` (`41 passed`)
- `verify:` `git diff --check -- src/vaultspec_rag/serviceclient/_search_transport.py` -> `pass`

## Notes

`uv run pytest src/vaultspec_rag/tests/test_cli_search_safety.py -q` retained 10 staged failures: five old payload assertions omit the new default `freshness_policy`, assigned to S36, and five assertions require removed client-synthesized `http_search_timeout` diagnostics, assigned to S40.
