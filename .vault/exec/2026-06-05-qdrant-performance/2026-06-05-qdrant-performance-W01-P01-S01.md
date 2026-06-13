---
tags:
  - '#exec'
  - '#qdrant-performance'
date: '2026-06-05'
modified: '2026-06-05'
step_id: 'S01'
related:
  - "[[2026-06-05-qdrant-performance-plan]]"
---

# Expose QDRANT_URL and QDRANT_API_KEY environment variables in config class

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Expose `QDRANT_URL` and `QDRANT_API_KEY` environment variables.
- Add properties `qdrant_url` and `qdrant_api_key` to config model.

## Outcome

- Configuration variables are available to route client calls to Qdrant Server Mode.
