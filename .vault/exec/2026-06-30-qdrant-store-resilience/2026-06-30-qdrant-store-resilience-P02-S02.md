---
tags:
  - '#exec'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S02'
related:
  - "[[2026-06-30-qdrant-store-resilience-plan]]"
---

# Add \_corrupt_collection_from_output that returns an on-disk collection name found in the failure tail or None

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

Added `_corrupt_collection_from_output` detection.

## Outcome

Keys on the real on-disk collection set, not Qdrant's version-dependent message format: returns the longest on-disk collection name appearing in the failure tail when a load-failure marker co-occurs, else None. Abstains rather than guess (QR1/QR4).

## Notes

Tested: names-on-panic, abstain-no-marker, abstain-no-on-disk-name, longest-first, empty tail.
