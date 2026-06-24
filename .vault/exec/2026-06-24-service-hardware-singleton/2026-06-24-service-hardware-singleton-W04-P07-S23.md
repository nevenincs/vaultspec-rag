---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S23'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Adversarial: an injected held port or storage lock yields fast-fail or reap, never a competitor

## Scope

- `src/vaultspec_rag/tests/integration/test_adversarial_singleton.py`

## Description

- Added injected-holder cases to `test_adversarial_singleton.py`: a foreign port holder
  (listening, no managed identity) decides `refuse` ("never spawn a competitor"); a dead-owner
  orphan decides `reap_then_spawn`; and a live foreign holder injected into the machine lock
  (a real spawned subprocess pid) makes `acquire_machine_lock` fast-fail with that holder.

## Outcome

An injected held port or lock never yields a competitor on the shared single-writer storage -
it fast-fails or routes to reap. `ruff` and `ty` pass.

## Notes

The live-foreign-holder case uses a genuinely running subprocess pid, so the fast-fail is
exercised against real liveness, not a fabricated pid. No blockers.
