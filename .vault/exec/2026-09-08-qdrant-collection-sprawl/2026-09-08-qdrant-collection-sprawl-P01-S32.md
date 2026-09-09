---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:ed5300fab268d30742993fa153114cfb3987fd6567325fc7a31ea3972dc79a29'
step_id: 'S32'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test proving an unverifiable active-job probe defers the namespace rather than authorising the drop

## Scope

- `src/vaultspec_rag/tests/test_storage_safety.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_safety.py`
- `M` `src/vaultspec_rag/tests/test_storage_ops.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_storage_safety.py test_storage_ops.py test_storage_survey.py test_storage_ops_reclaim.py test_storage_manifest.py test_index_lifecycle.py test_generation_survey.py` -> `pass`
- `verify:` `mutation: unestablished probe read as the empty set` -> `fail`
- `verify:` `mutation: unverifiable deferral wired to the busy reason` -> `fail`

## Notes

The gate is exercised through the injected liveness probe, which is the
seam the cycle already exposes for it. The probe's own read-failure branch
is not reached: the job registry it consults is in-memory with no failure
to induce, so covering that branch would take a test double standing in for
the registry, which would assert nothing about the registry.
