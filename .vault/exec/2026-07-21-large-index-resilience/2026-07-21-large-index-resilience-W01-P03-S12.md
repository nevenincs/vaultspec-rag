---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S12'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Construct the server-mode store client from explicit operation timeout configuration

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Replace the hard-coded remote Qdrant request timeout with the validated service configuration.
- Round fractional configured seconds upward to match the installed Qdrant client's REST and gRPC deadline semantics.
- Add imported-production coverage proving a non-default timeout reaches a real server-mode client.

## Outcome

Server-mode `VaultStore` construction now consumes
`store_operation_timeout_seconds`; local-mode construction is unchanged. The complete
store unit suite passes 40 tests. Ruff and strict type checks pass for the implementation
and its regression test. Independent review reported no critical, high, or medium finding.

## Notes

The installed Qdrant client declares an integer timeout and rounds fractional values upward
internally. The explicit `math.ceil` preserves that behavior while satisfying strict typing
and never shortens the configured operation budget. No service or Qdrant process was started,
stopped, or restarted for this step.
