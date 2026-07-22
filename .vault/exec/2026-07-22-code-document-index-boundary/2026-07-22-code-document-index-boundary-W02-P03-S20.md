---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S20'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Add targeted document clean semantics without evicting code state or unrelated extraction cache entries

## Scope

- `src/vaultspec_rag/api.py`
- `src/vaultspec_rag/store.py`

## Description

- Add `document` as an explicit targeted cleanup domain.
- Drop and recreate only the document collection for targeted cleanup.
- Remove only the document metadata sidecar and retain extraction cache state.

## Outcome

Callers can clean document vectors and publication evidence independently.
Combined cleanup now includes all three storage domains without coupling
document cleanup to code state or extraction-cache invalidation.

## Notes

Formatting, lint, and type checks passed. Real-store isolation verification is
reserved for the phase boundary.
