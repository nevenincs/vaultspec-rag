---
tags:
  - '#exec'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-07-27'
body_hash: 'sha256:402bc985aea81b4f7b0eb8414859d58e534143b30d870571f07b925af5e1e5e5'
step_id: 'S11'
related:
  - "[[2026-06-04-async-service-index-plan]]"
---

## Description

### Scope

- `src/vaultspec_rag/jobs.py`

- Move background reindexing task and jobs registry into `src/vaultspec_rag/jobs.py` to decouple task execution from the MCP transport layer.

- Keep strong references to background asyncio Tasks inside a module-level set in `jobs.py`.

- Expose a callback registration function to allow wrapper layers to listen to job complete events.

## Outcome

- Created the new backend module successfully.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
