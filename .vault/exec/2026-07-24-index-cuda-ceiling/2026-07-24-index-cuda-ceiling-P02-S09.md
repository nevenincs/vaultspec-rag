---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:6bdc3737ab6b35e07b11490e16fa0c9ba746a50ae4ef62fc200033d2549c32de'
step_id: 'S09'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# add a test asserting the config override raises the ceiling above the profile floor and still lowers it below

## Scope

- `src/vaultspec_rag/tests/test_config.py`

## Description

- Added a test proving the override raises the effective ceiling ABOVE the
  profile figure and lowers it BELOW - the bidirectionality the old clamp
  could not express.
- Added a test exercising both auto-derive branches (device total present ->
  total minus headroom; absent -> profile fallback) by patching the probe.
- Updated the resilience matrix: `index_cuda_ceiling_mb` default is now 0 and
  it moves out of the reject-zero set; added the headroom knob to it; added an
  explicit accept-zero / reject-negative guard for the sentinel.

## Outcome

All 125 config tests pass.

## Notes

These are positive/contract tests of the resolution logic, not guard tests, so
green runs suffice. The cross-job and double-count GUARD proofs are P04 work in
phase P03/P04 and are not attempted here.
