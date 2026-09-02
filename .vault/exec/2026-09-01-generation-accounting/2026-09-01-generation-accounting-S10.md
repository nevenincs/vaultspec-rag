---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:ac844ffafbf2d25271ee98d003c090cd29e16786d1f5dd7d4140f79fb97db172'
step_id: 'S10'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Prove target-scoped code deletion never initializes the served collection

## Scope

- `src/vaultspec_rag/tests/test_store_codebase.py`

## Description

- Exercise explicit-generation code upsert and deletion through the local store.
- Assert both operations prepare only the generation collection while the served collection remains absent.

## Changes

- Added regression coverage for explicit-target table preparation during code upsert and deletion.

## Outcome

The regression pins table preparation to the caller-supplied build target for both
mutating operations.

## Notes

The focused integration test is fail-closed on this host: pytest exits before collection
because no ready compatible machine-pointer service is available. No binary was installed
or bypassed, so the guard-failure demonstration also remains unavailable here.
