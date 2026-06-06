---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
step_id: 'S05'
related:
  - "[[2026-06-05-cli-mcp-decoupling-plan]]"
---

# Standardize get_service_state backend data collection into backend API

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Implement `get_service_state` inside `src/vaultspec_rag/api.py`.
- Query RAG status (document counts, GPU device, VRAM) via `get_status(root)`.
- Query registry active projects snapshot.
- Format file watcher config and active watched roots list.
- Expose the function in the public `__all__` facade list.

## Outcome

- Successfully consolidated all service state queries into the new backend facade function `get_service_state`.

## Notes
