---
tags:
  - '#exec'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S06'
related:
  - "[[2026-07-23-index-job-backend-resilience-plan]]"
---

# Add a guard test driving a store operation against a backend that refuses then accepts, asserting bounded-retry survival, and record it failing against the pre-change single-shot path then passing after

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Added `TestRealConnectionRefusedIsRetried`, which uses a real TCP socket against a real closed port so the failure is an actual OS-level `ECONNREFUSED` (`WinError 10061`) - the exact production signature - rather than a stub that merely raises.
- `test_single_attempt_fails_hard_on_refused_connection` pins the pre-change behaviour permanently: with the attempt budget set to one, the identical operation fails hard with `ConnectionRefusedError` after exactly one attempt.
- `test_refused_then_accepted_connection_succeeds_via_retry` has attempts one and two hit a genuinely closed port and only then brings a real listener up, asserting the operation ultimately connects, that exactly two attempts were refused, and that each refusal was a real `ConnectionRefusedError`.

## Outcome

Guard verified in both directions as one uninterrupted sequence:

- WITH FIX: both tests pass; the retry rides out two genuine refusals and connects on the third attempt.
- MUTATED (the retry loop reduced to a single iteration, reproducing the pre-change single-shot path): `test_refused_then_accepted_connection_succeeds_via_retry` fails with `[WinError 10061] No connection could be made because the target machine actively refused it`, logged as `store operation connect failed after 1 attempts` - failing on the connection-refused condition specifically, not on an incidental error.
- RESTORED: all 19 tests in the module pass.

No mocks, stubs, or patched clients are involved: the refusals are produced by the operating system against a port with nothing listening, and the recovery is a real socket accepting a real connection.

## Notes

A first version brought the listener up on a background timer and proved flaky in the wrong direction - it passed with only one attempt, because installing the retry policy resets configuration and took longer than the timer delay, so the backend was already up before the first attempt. Driving the transition off the attempt count instead makes the sequence deterministic while keeping every refusal a real one; the assertions on the refusal count and exception type are what prevent the test from passing vacuously if the port were open from the start.
