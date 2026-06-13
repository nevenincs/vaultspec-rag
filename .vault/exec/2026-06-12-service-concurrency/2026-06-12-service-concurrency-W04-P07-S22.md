---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-12'
step_id: 'S22'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Surface limiter depth and lock-wait telemetry through the existing bounded metrics plumbing

## Scope

- `src/vaultspec_rag/server/_state.py`

## Description

- Emit per-pool gauges (total tokens, borrowed tokens, queued waiters) for
  the search and index limiters in the Prometheus rendering.

## Outcome

Pool saturation is observable before it manifests as timeouts; output
stays bounded (six gauges).

## Notes
