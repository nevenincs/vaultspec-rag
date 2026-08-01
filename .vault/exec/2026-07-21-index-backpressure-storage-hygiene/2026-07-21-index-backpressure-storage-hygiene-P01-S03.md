---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:385726ee3c3c2a0b6a358b622c33bf214605265787305f37c8dc37c70aeae6eb'
step_id: 'S03'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add config knobs for the qdrant client timeout and write retry bounds following existing naming

## Scope

- `src/vaultspec_rag/config.py`

## Description

Added the three write-path knobs to `config.py` following the existing
EnvVar + `_ENV_OVERRIDE_MAP` + `_RAG_DEFAULTS` idiom:
`qdrant_client_timeout_s` (30.0), `store_write_retries` (3), and
`store_write_backoff_s` (1.0), env-overridable as
`VAULTSPEC_RAG_QDRANT_CLIENT_TIMEOUT_S` /
`VAULTSPEC_RAG_STORE_WRITE_RETRIES` /
`VAULTSPEC_RAG_STORE_WRITE_BACKOFF_S`.

## Outcome

Committed as `feat(config): qdrant client timeout and store write retry knobs (#242)`; smoke-verified resolution through `get_config()`.

## Notes

**Reconciliation 2026-07-21 (post PR 246):** the parallel session's merged PR 246 shipped the same ask (`_store_writes` classification and bounded retry, `_SERVER_REQUEST_TIMEOUT_S` on the client, disk headroom guards). This branch's variant was removed in the origin/main merge; PR 246's shapes are canonical. The config knobs were dropped with it; PR 246 uses module constants.
