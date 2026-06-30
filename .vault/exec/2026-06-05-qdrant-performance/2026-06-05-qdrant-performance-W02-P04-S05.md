---
tags:
  - '#exec'
  - '#qdrant-performance'
date: '2026-06-06'
modified: '2026-06-30'
step_id: 'S05'
related:
  - '[[2026-06-05-qdrant-performance-plan]]'
---

# Add support for positive/negative recommendations in hybrid search calls

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Add `like_ids` and `unlike_ids` optional parameters to `hybrid_search` and `hybrid_search_codebase` methods.
- Retrieve and resolve stable UUIDs from input document or chunk IDs.
- Construct `RecommendQuery` with positive/negative points list to guide the dense prefetch search when feedback vectors are specified.

## Outcome

- Hybrid search routines support relevance feedback using positive and negative point IDs, routing recommendations via Qdrant's recommendation system.
