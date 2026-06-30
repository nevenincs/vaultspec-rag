---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S37'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add an adversarial test suite covering out-of-scope deletion, traversal and symlink payloads, unknown-namespace, busy-root, and json-without-confirmation

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_adversarial.py`

## Description

- Add the adversarial test suite: json-without-yes refusal for every destructive verb, invalid migrate target rejection, traversal rejection, and the prune out-of-scope-protection invariant.

## Outcome

test_storage_adversarial.py (unit) + the prune-invariant integration test; green. ruff, ty, and basedpyright clean.

## Notes

Part of the storage-lifecycle surface (PR #196); CLI-direct architecture per accepted ADR divergence.
