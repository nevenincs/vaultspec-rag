---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S25'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Adversarial: concurrent multi-repo search and index load through one service holds under saturation

## Scope

- `src/vaultspec_rag/tests/integration/test_adversarial_multirepo.py`

## Description

- Authored `test_adversarial_multirepo.py` (real GPU): two independent repos (separate roots,
  separate stores) share the one embedding model - the real multi-repo contention. 24
  concurrent full searches split across both repos, interleaved with a reindex on one, run
  through a thread pool; the test asserts no errors/deadlock and that every search returns hits.

## Outcome

Concurrent multi-repo search + index load holds under saturation on the real GPU + real stores
(1 passed, ~27s). Exercises the shared GPU lock and the backend-aware per-collection store
locks under the multi-user load profile. `ruff` and `ty` pass.

## Notes

Realized at the store/searcher level (the actual GPU+lock contention point) rather than over
HTTP, matching the existing real-GPU integration pattern and avoiding a second daemon. No
blockers.
