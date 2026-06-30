---
tags:
  - '#exec'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S03'
related:
  - "[[2026-06-30-qdrant-store-resilience-plan]]"
---

# Wrap supervised start with a bounded detect-quarantine-retry loop, on by default, abstaining when no culprit is identified

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

Wrapped supervised `start()` with bounded detect-quarantine-retry.

## Outcome

On a readiness failure whose tail names an on-disk collection, quarantine it and retry; bounded by `_MAX_QUARANTINES_PER_START` (3). When no culprit is found or the bound is reached, raise the existing ready-failure error with the panic tail. `auto_quarantine=False` opts out (QR3).

## Notes

Tested end-to-end with a real fake binary: a perpetually-corrupt store quarantines exactly the bound then raises; the two beyond the bound are untouched.
