---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:df5dd8721b48c6426c1313e66c882003c96a6d79e3d938adf28ca219bea07853'
step_id: 'S04'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Prove clean-generation cleanup mutates only the active build collection

## Scope

- `src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`

## Description

- Seed the served and active build collections with the same real point identifier.
- Invoke the production stale reconciliation against the lifecycle-derived build target.
- Assert that cleanup removes the build point while the pre-publication served point remains.
- Demonstrate the guard failure by temporarily omitting the target: the named
  build-count assertion fails; restore the target and demonstrate the pass.

## Outcome

The real-storage regression detects a cleanup call that falls back to the served
collection while a clean generation is still being built.

## Changes

- Add a clean-generation stale-cleanup regression using two real collections.

## Notes

Scoped Ruff format, Ruff lint, `ty`, strict basedpyright, and the direct
real-storage guard demonstration passed. The focused pytest selection was
blocked before execution by the GPU-tier fail-closed guard: the resident
service release is `0.4.21`, while this checkout requires `0.4.15`.
