---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:8403f83b53e03f4cc6f3f65899419b5f1424d06e128e388311043a2d7e47f4d5'
step_id: 'S12'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Drop UNSANDBOXED from the daemon child-env forwarding allow-list

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Narrow `_service_child_env`/`_spawn_service` `preprocess_mode` to `Literal["off"] | None`; forwarding writes only `VAULTSPEC_RAG_PREPROCESS=off`.
- Reword the `SERVICE_DAEMON` marker comment (no longer sandbox-related).

## Outcome

Daemon env forwarding carries only the kill switch.

## Notes

None.
