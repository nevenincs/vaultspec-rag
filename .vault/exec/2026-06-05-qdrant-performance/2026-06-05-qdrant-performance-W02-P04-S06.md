---
tags:
  - '#exec'
  - '#qdrant-performance'
date: '2026-06-06'
modified: '2026-06-30'
step_id: 'S06'
related:
  - '[[2026-06-05-qdrant-performance-plan]]'
---

# Expose like_ids and unlike_ids parameters in api.py search facade functions

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Extend `search_vault` and `search_codebase` public facade APIs with optional `like_ids` and `unlike_ids` arguments.
- Pass recommendation arguments directly to the underlying `VaultStore` search calls inside active slot leases.

## Outcome

- The unified backend api layer exposes recommendation query functionality, making it available for client routing layers.
