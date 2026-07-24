---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S03'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Add the both-direction guard tests covering worker blocks when quiesced with a bounded join timeout, worker resumes when released, shutdown wins over a concurrent re-pause, and a checkpoint inside a protected span never parks, each proven red-then-green in one sequence

## Scope

- `src/vaultspec_rag/tests/test_job_control_unit.py`

## Description

- Extend the `job_control` import in `src/vaultspec_rag/tests/test_job_control_unit.py` to bring in `QuiesceGate` and `ShutdownRequested`, and add a `_PARK_OBSERVE_SECONDS = 0.5` bound for observing a parked worker; reuse the existing `_join_thread` bounded-join helper.
- Add `test_worker_blocks_when_gate_is_quiesced`: a worker reaches `checkpoint()` with the gate paused, is asserted still alive after a bounded join, then resume releases it and it finishes.
- Add `test_worker_resumes_when_gate_is_released`: a parked worker completes promptly once `resume()` is called, proven by the bounded join succeeding.
- Add `test_shutdown_wins_over_concurrent_re_pause`: a parked worker wakes and raises `ShutdownRequested` when `request_shutdown()` latches the gate open while a concurrent thread calls `pause()`.
- Add `test_checkpoint_inside_protected_span_never_parks`: with a paused gate, a `checkpoint()` inside a `token.protected()` span returns immediately and the worker completes.

## Outcome

All four guards are proven red-then-green in one uninterrupted sequence each (evidence below), and the full module is green: 21 passed (17 pre-existing plus the 4 new guards). Green gate at this Step: ruff clean on `src tools`, ty clean, basedpyright reports 0 errors.

### Guard evidence (red-then-green)

- **blocks-when-quiesced.** Mutation: made `QuiesceGate.wait()` return immediately, ignoring pause (early `return` before `self._event.wait()`). Red: `AssertionError: worker did not park at the quiesced gate` (`assert worker.is_alive()` at the bounded observe join) — the worker finished early instead of parking. Restore: `1 passed`.
- **resumes-when-released.** Mutation: made `QuiesceGate.resume()` a no-op (early `return` before `self._event.set()`). Red: `AssertionError: worker 'quiesce-resume-worker' did not stop` at `_join_thread` after the 5s bounded join (call duration 5.5s) — the worker never woke. Restore: `1 passed`.
- **shutdown-wins-over-concurrent-re-pause.** Mutation: removed the `self._gate.latch_open()` call from `request_shutdown()`. Red: `AssertionError: worker 'quiesce-shutdown-worker' did not stop` at `_join_thread` — without the latch the racing `pause()` kept the gate closed and the worker never raised `ShutdownRequested`. Restore: `1 passed`.
- **protected-span-never-parks.** Mutation: dropped the protected-depth guard on the gate wait in `checkpoint()` (removed the `if self._protected_depth > 0: return` block). Red: `AssertionError: worker 'quiesce-protected-worker' did not stop` at `_join_thread` — the checkpoint inside the protected span parked on the paused gate. Restore: `1 passed`.

## Notes

The bounded join in `_join_thread` is load-bearing for these guards: a broken-open gate or a broken release surfaces as a failed still-alive assertion at 5s rather than hanging the suite. A broken-resume/broken-latch mutation leaves the worker parked in-kernel; each red was captured via the per-test `-v` reporter line, which emits after the call phase completes.
