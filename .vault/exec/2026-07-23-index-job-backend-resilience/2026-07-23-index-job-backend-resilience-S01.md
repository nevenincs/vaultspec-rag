---
tags:
  - '#exec'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S01'
related:
  - "[[2026-07-23-index-job-backend-resilience-plan]]"
---

# Generalise the write-only bounded transient retry into a store-operation retry that any store call can run under, preserving the transient/unrecoverable classification, capped backoff, and durable no-progress budget clamp

## Scope

- `src/vaultspec_rag/_store_writes.py`

## Description

- Renamed `run_write_with_retry` to `run_store_operation_with_retry`, keeping one API rather than introducing a second name for the same behaviour.
- Rewrote the module and function docstrings to state the broader role and why it exists: an index job reaches ensure and read operations before its first write, so leaving those single-shot turned a momentary refusal into a hard job failure.
- Retitled the module from write-path to operation-path hardening and generalised the diagnostic log messages from "store write" to "store operation".
- Updated the single production call site and the test module to the new name.

## Outcome

One bounded-retry entry point now serves every store operation. Behaviour is unchanged for the existing write path: the same transient-versus-unrecoverable classification, the same capped exponential backoff, the same clamp against the caller-owned durable no-progress budget, and the same typed no-progress outcome on expiry. The store-writes unit suite passes unchanged at 15 tests, confirming the rename carried no semantic drift.

## Notes

The module filename and the `StoreWritePolicy` value object keep their existing names; renaming them would have churned many unrelated importers for no behavioural gain.

Code review found that attempt count alone is not a ceiling. Each attempt was bounded only by the client-level timeout, so an operation against a backend that accepts the connection and then stalls cost the full timeout once per attempt - the retry multiplied the worst case rather than capping it, and the ensure path runs about a dozen such operations while holding the lifecycle lock. The helper gained an optional total wall-clock ceiling: it clamps each attempt's admitted timeout to the remaining budget and, on failure, ends the operation on the original exception once the budget is spent rather than raising a liveness outcome, since an unmanaged read that spent its own allowance has not stalled a managed run. The store passes the single-attempt timeout as that ceiling, keeping the retried worst case at parity with the pre-change one.
