---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S21'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Accept and validate the new search params in the server route

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Passed `intent=payload.get("intent")` from the server `/search` route into the vault
  `search_vault_timed` facade call.

## Outcome

The service route forwards an explicit intent to the search facade, keeping the CLI, HTTP,
and MCP adapters on one contract. `ruff` and `ty` pass.

## Notes

When the CLI sends intent via the query token (the common case), the payload key is absent
and the searcher resolves intent from the parsed token instead. No blockers.
