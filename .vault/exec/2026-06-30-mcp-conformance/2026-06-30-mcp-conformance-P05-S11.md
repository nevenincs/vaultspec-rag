---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S11'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Treat a stale or orphaned machine pointer as absence and isolate the leaked test token under the managed-storage isolation discipline

## Scope

- `src/vaultspec_rag/_machine_lock.py`

## Description

Stale/orphaned pointer is treated as absence; leaked-token class closed.

## Outcome

The staleness defence shipped in P01 (`_discovery_is_stale`): a pointer past its heartbeat window is no service, so the orphaned pointer with a dead pid the research found can no longer mislead a consumer. The leaked `test-token` defect class is closed by isolating `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` in the discovery-touching tests, per the managed-storage isolation discipline.

## Notes

`test_stale_pointer_is_treated_as_absent` is the regression guard.
