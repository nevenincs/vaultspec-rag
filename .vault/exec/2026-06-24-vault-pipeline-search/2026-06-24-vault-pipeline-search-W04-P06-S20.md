---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
body_hash: 'sha256:b2c5da74b8ad743d81ad5b562990c3a6d43e4a34866616d40898111bfd767f52'
step_id: 'S20'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Thread intent, status, and doc-type-union params through the HTTP search client

## Scope

- `src/vaultspec_rag/cli/_http_search.py`

## Description

- Added an `intent` parameter to `_try_http_search` and `_build_http_search_payload` in the
  service-client transport, placing it into the vault search payload only when set.

## Outcome

The HTTP search client now forwards an explicit intent to the service. Programmatic and MCP
callers can set it directly; the CLI carries intent inside the query token instead, so the
payload omits it and the service parses the token. `ruff` and `ty` pass.

## Notes

The transport stays import-light (validation still via the leaf `_validation` module). No
blockers.
