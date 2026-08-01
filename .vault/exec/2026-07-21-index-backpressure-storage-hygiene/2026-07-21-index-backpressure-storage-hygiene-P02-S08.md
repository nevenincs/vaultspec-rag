---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:2dba15a7b79361c2b474e658cbdef7d7977c3e9040689866e878f526ddc6eb00'
step_id: 'S08'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add jobs-registry and route tests for error_kind propagation and stall flagging

## Description

### Scope

- `src/vaultspec_rag/tests/`

Tests: `TestJobErrorKind` (classification lifecycle on real records),
`TestJobStallShaping` (liveness flag semantics + summary counts), and
`TestHealthJobsRollup` (a real Starlette TestClient asserting the /health
jobs block).

## Outcome

Committed as `test(jobs): error_kind classification, stall shaping, /health jobs rollup (#242)`; 33 registry/route tests + 66 CLI tests green.

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
