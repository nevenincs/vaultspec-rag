---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S14'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Integration-test attach to a healthy managed qdrant with no second spawn

## Scope

- `src/vaultspec_rag/tests/integration/test_qdrant_attach.py`

## Description

- Authored `test_qdrant_attach.py` with a real stdlib HTTP server standing in for a running
  managed Qdrant (answers `/readyz`, reports a configurable version), the managed config
  driven through genuine env knobs, and the identity sidecar written to make it owned.
- Added the attach test: with a healthy, owned, version-matching server, `start_supervised_
  from_config` returns an attached supervisor (no child pid) that reports alive.

## Outcome

P1's happy path is verified end-to-end through the real start path, no mocks/GPU/real Qdrant.
`ruff` and `ty` pass; 3 tests in the module pass in ~1.7s.

## Notes

Uses an ephemeral loopback port and a temp storage/status dir, and clears the process-wide
active supervisor in teardown so it cannot leak into other tests. No blockers.
