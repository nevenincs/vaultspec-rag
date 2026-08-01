---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-07-27'
body_hash: 'sha256:ed346e011cdac0093f349d0eb09f36c04ec90e9520065b77d4f2ff45aa9d2509'
step_id: 'S22'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Surface limiter depth and lock-wait telemetry through the existing bounded metrics plumbing

## Description

### Scope

- `src/vaultspec_rag/server/_state.py`

- Emit per-pool gauges (total tokens, borrowed tokens, queued waiters) for
  the search and index limiters in the Prometheus rendering.

## Outcome

Pool saturation is observable before it manifests as timeouts; output
stays bounded (six gauges).

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
