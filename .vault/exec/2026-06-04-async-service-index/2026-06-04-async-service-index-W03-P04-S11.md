---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
step_id: 'S11'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

# Move background task registry and asyncio create_task execution into a new backend module

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Move background reindexing task and jobs registry into `src/vaultspec_rag/jobs.py` to decouple task execution from the MCP transport layer.
- Keep strong references to background asyncio Tasks inside a module-level set in `jobs.py`.
- Expose a callback registration function to allow wrapper layers to listen to job complete events.

## Outcome

- Created the new backend module successfully.

## Notes
