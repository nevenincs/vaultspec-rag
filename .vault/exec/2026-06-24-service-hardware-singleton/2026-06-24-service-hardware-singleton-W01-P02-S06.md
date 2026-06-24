---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S06'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Classify a managed qdrant orphan by expected storage and dead owner pid

## Scope

- `src/vaultspec_rag/qdrant_runtime/_resolve.py`

## Description

- Added `classify_qdrant_state(probe, identity)` to `_resolve.py`, combining the endpoint
  probe and the identity record into one of five states the attach/spawn decision keys on:
  `absent`, `stale_identity`, `managed_orphan`, `managed_running`, `foreign`.

## Outcome

A managed orphan (listening but recorded owner dead) is now distinguishable from a healthy
managed server, a foreign holder, a stale sidecar, and a clean slate. `ruff` and `ty` pass;
verified by the S07 test exercising all five states. This is the decision substrate W02's
attach gate and W03's reap-on-start build on.

## Notes

Classification keys on expected storage via the identity record's owner pid plus the live
probe, matching the step's "expected storage and dead owner pid" intent. No blockers.
