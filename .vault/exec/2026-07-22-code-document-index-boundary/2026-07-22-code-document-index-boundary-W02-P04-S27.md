---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:6f8371ed1e49db090b37e7dbedeb0ee608a88e1dfc45e6c89593c6f7b814cd5d'
step_id: 'S27'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Return explicit per-domain outcomes from all indexing without hiding a partial failure

## Scope

- `src/vaultspec_rag/api.py`
- `src/vaultspec_rag/jobs.py`

## Description

- Represent each all-domain result as an explicit success or error.
- Retain every domain outcome when another domain fails.

## Outcome

Combined indexing no longer collapses or hides partial outcomes.

## Notes

Public transport adapters remain assigned to their later planned phase.
