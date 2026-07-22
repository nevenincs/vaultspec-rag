---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S18'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Verify service clients fail fast with holder and pointer evidence for every degraded resolution

## Scope

- `src/vaultspec_rag/tests/test_http_admin_errors.py`

## Description

- Cover an unheld singleton failing without a holder and without a degraded verdict.
- Cover each degraded pointer shape under a real held lock failing fast with its own
  reason, the holder identity, and evidence in the surfaced message.
- Cover a stale pointer refusing to resolve while a status file naming a different port
  is present, proving no fallback address is handed back.

## Outcome

Every degraded resolution is proven to fail fast with holder and pointer evidence, and the
compatibility fallback is proven unreachable while a holder is live.

## Notes

The fallback case is the one worth keeping honest: it deliberately plants a status file
naming a different port, because a fallback that only ever ran with nothing to fall back
to would pass whether or not the guard existed. The assertion checks that the foreign port
never appears in what the caller receives.
