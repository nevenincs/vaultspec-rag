---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S24'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add tests for front-door idempotency, dry-run preview, and the local-only binary skip on the provisioning orchestrator

## Scope

- `src/vaultspec_rag/tests/test_provision.py`

## Description

- Extend `src/vaultspec_rag/tests/test_provision.py` with a `TestFrontDoorIdempotency`
  class exercising the whole front door end-to-end against real backends, no
  mocks and no network.
- Add a second-run idempotency test: first run configures torch (`created`) and
  verifies a preseeded qdrant binary (`unchanged`); the second run reports each
  satisfied dependency as `unchanged` and never rewrites the verified binary
  (asserted via mtime), with the opted-out model step honestly `skipped`.
- Add a whole-front-door dry-run preview test asserting every step reports
  `dry_run`, torch stays `sync_pending`, and neither the real pyproject nor the
  isolated managed dir is written.
- Add a local-only test asserting the binary step is the only one skipped (torch
  still runs) and no binary lands in the isolated managed dir.
- Add a cached-models idempotency test that asserts the `unchanged` collapse only
  on the network-free cached outcome, leaving the no-mocks contract intact on a
  cold cache.

## Outcome

Five real tests cover front-door idempotency, dry-run preview, and the local-only
binary skip with the verify-before-execute contract preserved (the qdrant
idempotency path is proven by pre-seeding the managed dir exactly as a verified
provision leaves it, mirroring the qdrant runtime tests). The whole scoped suite
runs green (`54 passed`). One iteration corrected an over-strict assertion: a run
with an opted-out model step honestly aggregates to `mixed`, not `unchanged`, so
the test now asserts per-step idempotency (the real contract) rather than the
collapsed status.

## Notes

The aggregate-status assertion was initially wrong: `unchanged` torch + `unchanged`
qdrant + `skipped` models collapses to `mixed` by the documented aggregation
rule. The fix asserts the per-step actions, which is the honest idempotency
contract; the model-step skip is itself an honest outcome, not a failure.
