---
tags:
  - '#exec'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:e388fed34faa766a1676b256fd2810f5f645f5790cf7de6694342ddc02a14fb7'
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

A first version brought the listener up on a background timer and proved flaky in the wrong direction - it passed with only one attempt, because installing the retry policy resets configuration and took longer than the timer delay, so the backend was already up before the first attempt. Driving the transition off the attempt count instead makes the sequence deterministic while keeping every refusal a real one.

Code review then found a more serious gap: both original classes drive the retry helper directly with a socket lambda and never touch the store, so reverting a call site to a direct client call left the whole suite green - the guard did not bind to the change this work exists to make. A third class was added that drives a real store in server mode against a closed port.

Its first form asserted on elapsed time and was itself proven not to bind: under the reverted call site it still passed, because the client performs its own connection and version-check work against a refused endpoint and that alone exceeds any short backoff. The assertion was moved onto the retry's own per-attempt log records, which only the bounded retry emits. Re-proven in both directions: with the call site routed through the retry exactly two retry records appear naming the operation; with the call site reverted to a direct client call none appear and the test fails; restored, the module's 20 tests pass. The lesson - that a timing threshold is not a valid discriminator here - is recorded in the class docstring so a future reader does not reintroduce it.
