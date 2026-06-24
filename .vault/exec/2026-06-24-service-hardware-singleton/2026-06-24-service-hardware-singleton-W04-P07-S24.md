---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S24'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Adversarial: an unhealthy or corrupt qdrant holder is refused-attach with a named cause

## Scope

- `src/vaultspec_rag/tests/integration/test_adversarial_singleton.py`

## Description

- Added unhealthy/corrupt-holder cases to `test_adversarial_singleton.py`: a listening but
  not-ready managed holder decides `refuse` with "ready" in the cause; a wrong-version managed
  holder decides `refuse` with "version" in the cause.

## Outcome

An unhealthy or corrupt/mismatched Qdrant holder is refused-attach with a NAMED cause rather
than attached blindly (attaching to a sick server is worse than refusing). `ruff` and `ty`
pass.

## Notes

The cause strings are asserted, satisfying the "named cause, never opaque" requirement at the
decision layer. No blockers.
