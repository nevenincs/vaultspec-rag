---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S09'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Validate the identity signal under local trust for safe attach

## Scope

- `src/vaultspec_rag/qdrant_runtime/_resolve.py`

## Description

- Added `verify_attachable(probe, identity, *, expected_version, expected_storage)` to
  `_resolve.py`: the local-trust attach gate returning `(ok, reason)` only when the server is
  ready, an identity sidecar exists (owned), the live version matches the managed version, and
  the served storage matches the expected path (normcase/normpath compared).

## Outcome

The "is this running Qdrant safe to attach to" question now has one auditable answer with a
named reason for every refusal. `ruff` and `ty` pass; verified by the S10 gate tests (attach
when ready+owned+capable; refuse on not-ready / no-identity / version / storage mismatch).

## Notes

Validation is local-trust (the sidecar lives in the machine-global managed dir), paired with
the health/version checks so a forged network response alone cannot pass the gate. No blockers.
