---
tags:
  - '#exec'
  - '#qdrant-performance'
date: '2026-06-06'
modified: '2026-07-27'
body_hash: 'sha256:061e8f7bc944919d05ff57ca1213a9ef646d6ddb108d0706a8a062df5b99f8c6'
step_id: 'S05'
related:
  - '[[2026-06-05-qdrant-performance-plan]]'
---

## Description

### Scope

- `src/vaultspec_rag/store.py`

- Add `like_ids` and `unlike_ids` optional parameters to `hybrid_search` and `hybrid_search_codebase` methods.

- Retrieve and resolve stable UUIDs from input document or chunk IDs.

- Construct `RecommendQuery` with positive/negative points list to guide the dense prefetch search when feedback vectors are specified.

## Outcome

- Hybrid search routines support relevance feedback using positive and negative point IDs, routing recommendations via Qdrant's recommendation system.

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
