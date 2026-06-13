---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-12'
step_id: 'S06'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Add unit and GPU integration tests for chunked vault indexing, grouped search, and rebuild-on-schema-bump

## Scope

- `src/vaultspec_rag/tests`

## Description

- Add `test_vault_chunking_unit.py` (split semantics, grouping, bounded
  nudge) and `test_vault_chunking_integration.py` (tail retrieval past the
  old 8000-char horizon, exact get-by-id, one-row listing,
  delete-all-chunks, shrunk-tail purge, layout-marker rebuild).

## Outcome

13 unit + 8 GPU integration tests, all passing. The headline assertion - a
needle phrase placed past 12000 chars is retrievable with its snippet
showing the matched passage - proves the critical quality defect fixed.

## Notes
