---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S11'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Implement the attach gate: health, version match, storage match, ownership

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Added `decide_qdrant_action(probe, identity, *, expected_version, expected_storage)` to
  `_resolve.py`: a pure policy over `classify_qdrant_state` + `verify_attachable` returning
  `("attach"|"refuse"|"reap_then_spawn"|"spawn", reason)`.

## Outcome

The attach gate is a single, testable decision: a healthy/owned/capable managed server →
attach; a foreign or gate-failing holder → refuse; a managed orphan → reap-then-spawn;
otherwise spawn. Verified by smoke across all five states. `ruff` and `ty` pass.

## Notes

Implemented as a pure function so the policy is exhaustively testable without spawning a real
server (the integration wiring is S12). No blockers.
