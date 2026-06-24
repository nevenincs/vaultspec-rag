---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S10'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Map related and status from Qdrant rows in the vault search path

## Scope

- `src/vaultspec_rag/search/_searcher.py`

## Description

- Mapped `status` from the Qdrant row (`r.get("status", "")`) onto the vault `SearchResult`
  in `_search_vault_encoded`.
- Mapped `related` defensively: coerced the payload value to a `list[str]` only when it is a
  list, else an empty list, so a missing or malformed field never raises.

## Outcome

Vault results now carry status and related end-to-end (payload to result object). `ruff` and
`ty` pass. Live population is confirmed after the reindex in S11.

## Notes

The codebase mapping path is untouched (status/related stay empty there by design). No
blockers.
