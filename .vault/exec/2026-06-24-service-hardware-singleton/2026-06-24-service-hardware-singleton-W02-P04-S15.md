---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S15'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Integration-test refuse-fast on unhealthy, wrong-version, or foreign holder

## Scope

- `src/vaultspec_rag/tests/integration/test_qdrant_attach.py`

## Description

- Added the refuse-fast integration tests to `test_qdrant_attach.py`: a foreign holder (no
  identity sidecar) makes `start_supervised_from_config` raise "refusing to start qdrant", and
  a version-mismatched managed server (identity present, server reports a different version)
  raises with "version" in the message.

## Outcome

P1's refusal paths are verified end-to-end: a competitor is never spawned onto the shared
storage when the holder is foreign or fails the capability gate, and the error names the
cause. `ruff` and `ty` pass.

## Notes

Shares the real-HTTP-server harness with S14. No blockers.
