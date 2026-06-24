---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S13'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Refuse fast without spawning when a holder fails the attach gate

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Implemented the refuse-fast branches in `start_supervised_from_config`: a `refuse` decision
  (foreign holder or a managed server failing the attach gate) and a `reap_then_spawn`
  decision (managed orphan) both raise a `RuntimeError` naming the cause and the remedy
  (stop/fix the holder, or `--local-only`), instead of spawning a competitor.

## Outcome

A bad or foreign port holder now produces an immediate, named refusal rather than a competing
child on the shared storage and a 300s timeout. Verified by the S15 integration tests (refuse
on foreign holder; refuse on version mismatch). `ruff` and `ty` pass.

## Notes

Automatic reaping of a managed orphan is deferred to W03.P06 (S20); until then the
`reap_then_spawn` path refuses with the owner pointer and manual-reap guidance, which is
already a large improvement over the prior opaque hang. No blockers.
