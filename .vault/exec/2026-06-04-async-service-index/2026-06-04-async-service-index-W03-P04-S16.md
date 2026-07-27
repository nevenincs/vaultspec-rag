---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-07-27'
step_id: 'S16'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/api.py`

- Implement and expose `clean` (database clean/wipe) and `get_status` (RAG status, hardware metrics) facade functions inside the public `src/vaultspec_rag/api.py` module.

- Move collection dropping, metadata sidecar deletion, and GPU VRAM query routines out of CLI/MCP and into these API functions.

## Outcome

- Exposed `clean` and `get_status` successfully. Verified that they operate cleanly on the storage and hardware layers.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
