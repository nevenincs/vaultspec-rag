---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S05'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# Pass a --fresh flag through the CLI survey verb and the transport query builder in serviceclient/\_transport.py

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Add `fresh` to `_STORAGE_SURVEY_PARAMS` in `src/vaultspec_rag/serviceclient/_transport.py` so the admin route builder forwards it
- Add `--fresh` to `server storage survey` and pass it through `_survey_from_service` (`src/vaultspec_rag/cli/_service_storage.py`)

## Outcome

CLI, MCP, and HTTP consumers share one freshness semantic through the same transport. Commit 7ae79ca.

## Notes

The CLI-direct fallback always computes live, so `--fresh` only needs to reach the service path.
