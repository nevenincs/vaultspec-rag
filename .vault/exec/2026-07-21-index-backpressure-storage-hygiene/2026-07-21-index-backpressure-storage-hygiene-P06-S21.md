---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S21'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# extend the ADR regression guards for lifecycle inertness of the new hygiene code and the bounded-retry invariant

## Scope

- `src/vaultspec_rag/tests/test_adr_regression.py`

## Description

Two new ADR guards: `TestJobErrorTaxonomyStaysLight` (fresh-interpreter
import of `_job_errors` loads neither torch nor any CLI module) and
`TestEncodeRecoveryStaysBounded` (source scan pairing every CUDA-OOM
handler in `embeddings.py` with the batch-size floor raise). The existing
lifecycle-inertness guards already cover the new hygiene code since it
lives inside the scanned modules.

## Outcome

Committed with the P07 test commit; 32 ADR regression tests green.

## Notes
