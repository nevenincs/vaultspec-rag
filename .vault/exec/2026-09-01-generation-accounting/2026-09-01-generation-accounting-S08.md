---
tags:
  - '#exec'
  - '#generation-accounting'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:ff034e903a9c467ce5b2c6101ee2abbaf8220ce06d70b58b91edf061ac3f8183'
step_id: 'S08'
related:
  - "[[2026-09-01-generation-accounting-plan]]"
---

# Prove retained empty-source outcomes finalize after storage retirement

## Scope

- `src/vaultspec_rag/tests/test_run_checkpoint.py`

## Description

- Added a real-store resumed-generation regression for a retained source that becomes empty.
- Asserted exact storage retirement, `DELETE_STALE` evidence, `SOURCE_EMPTY` policy state, and metadata finalization.
- Proved the guard by temporarily bypassing the production retirement: the narrow test failed at its exact `_stored` assertion with both retained point identities present; restored the call immediately and observed a passing narrow test.

## Outcome

The empty-source convergence now has an independent production-path regression proving storage-first retirement and successful finalization without duplicating the skip-or-vanish helpers.

## Notes

No incidents, data loss, scaffolds, or persistent failures. The guard mutation was restored in the same uninterrupted sequence before further work.
