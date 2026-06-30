---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-06-30'
step_id: 'S16'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

# Expose database clean/wipe and engine status as backend API functions

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Implement and expose `clean` (database clean/wipe) and `get_status` (RAG status, hardware metrics) facade functions inside the public `src/vaultspec_rag/api.py` module.
- Move collection dropping, metadata sidecar deletion, and GPU VRAM query routines out of CLI/MCP and into these API functions.

## Outcome

- Exposed `clean` and `get_status` successfully. Verified that they operate cleanly on the storage and hardware layers.

## Notes
