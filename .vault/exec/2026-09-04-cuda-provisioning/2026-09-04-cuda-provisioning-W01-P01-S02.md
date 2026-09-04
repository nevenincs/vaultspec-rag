---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:88d28694a84f1415cb87240083fe52d35b847c1b3bac182f606bc028127db945'
step_id: 'S02'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Prove the holder query against real image-path, working-directory and uninspectable holders

## Scope

- `src/vaultspec_rag/tests/test_env_holders.py`

## Changes

- `A src/vaultspec_rag/tests/test_env_holders.py`

## Notes

Guard proof, one uninterrupted sequence, all three mutations restored and
verified absent from disk afterwards:

- Removing the working-directory relation from `environment_holders` failed
  `test_a_foreign_process_sitting_in_the_environment_is_a_directory_holder` at
  its bounded wait - the query never reported the directory holder. Restored,
  passes in 5s.
- Dropping the uninspectable counter failed
  `test_an_uninspectable_process_denies_certainty_without_inventing_a_holder`
  on `assert result.uninspectable == 1` with `assert 0 == 1`. Restored.
- Returning an empty complete result from a failed scan failed
  `test_a_scan_that_cannot_enumerate_is_incomplete_rather_than_empty` on
  `assert result.complete is False` with `assert True is False`. Restored.

The first mutation initially took 4m45s to fail because the holder-wait helper
spawned a subprocess per poll. The helper now sleeps in-process against a 15s
deadline, so the failing path costs 19s rather than five minutes; the passing
path was never affected.
