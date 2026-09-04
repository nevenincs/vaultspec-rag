---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:48d973cc155249c69ddebc86d3f4da36ec6eeb3c1c74f0a84d581ad0343f4c50'
step_id: 'S03'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Add the redirected uv environment fixture, a loopback wheel index serving stand-in distributions, and a holder subprocess helper

## Scope

- `src/vaultspec_rag/tests/_uv_env_harness.py`

## Changes

- `A src/vaultspec_rag/tests/_uv_env_harness.py`

## Notes

The fixtures were exercised against real uv before being handed to the proof
Step, since shipping an unverified harness is the failure this campaign exists
to correct. In a throwaway tree: a forced tool install of a stand-in package
carrying a `--with` requirement over loopback HTTP exited zero and installed
both distributions; the receipt recorded that requirement as
`{ name = "torchstub", url = "http://127.0.0.1:PORT/..." }`, the shape
production reads; a wheel tagged `cp299` was refused as unsatisfiable; an
absent wheel returned 404 and left the environment and receipt intact; and a
forced reinstall while the environment's own interpreter held it exited 2 with
`failed to remove directory ...\Scripts: Access is denied`, leaving
site-packages empty - the field failure, reproduced in isolation.

One correction the exercise forced: a receipt always contains a `path` key,
because every recorded entry point carries an `install-path`. Asserting on the
presence of `path` anywhere in the file would pass regardless of how a
requirement was recorded, so the proofs must match the requirement's own line.
