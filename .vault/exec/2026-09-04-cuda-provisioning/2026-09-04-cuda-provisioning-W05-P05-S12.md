---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:051374ef3acef1da4f645d544dc178abe77c10677774d888c2cab64a6732dad1'
step_id: 'S12'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Add the hosted Windows pull-request leg covering the provisioning proof class

## Scope

- `.github/workflows/ci.yml`

## Changes

- `M .github/workflows/ci.yml`
- `M justfile`
- `A tools/test_ci_trust_boundary.py`

## Notes

The research flagged as inference that this test class needs no GPU, model
cache or Hugging Face token. Confirmed before relying on it: every file in the
class imports only package modules, all five declare the fast tier, and the
token gate in the root conftest fires for `GPU_MARKERS | {SUBPROCESS_GPU}`
only, which the fast tier is not in. Measured locally at 45 tests in 52
seconds, against a 25 minute ceiling.

CI calls `just test provisioning` rather than an inline pytest invocation, so
the lane runs the same verb a developer does and the file list has one home.

The leg is hosted `windows-latest`, mirroring vaultspec-core's shape. The
self-hosted Windows job stays out of the pull-request lane: its exclusion is
the containment the workflow header describes, and this leg is not a route
into it.

A structural gate was added because the mutation exposed that nothing guarded
the decision - the workflow step could be changed to any other command and no
test would notice. `tools/test_ci_trust_boundary.py` asserts the two
properties that are invisible from reading a single job: no job reachable from
a fork's pull request runs on self-hosted infrastructure, and the
pull-request lane runs the provisioning class on Windows.

Guard proof, both directions. Replacing the step with `just test fast` failed
the provisioning assertion; moving the leg onto the self-hosted fleet failed
the containment assertion with the offending job named. Both restored; zero
MUTATION markers remain, actionlint passes, and the two gates pass.
