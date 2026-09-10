---
tags:
  - '#audit'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:a0ef56229e4d9d2f64804c1273fc8882bf5aa4725ec77c7032d01990444dc78e'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
  - "[[2026-09-08-adaptive-watcher-control-adr]]"
---

# `adaptive-watcher-control` audit: `scheduler lifecycle review`

## Scope

Reviewed the accepted scheduler step against the governing ADR, research, reference, and
approved plan. The review covered the complete service watcher lifecycle implementation,
the focused scheduler tests, and the uncommitted change set, with emphasis on fair admission
state, event/deadline wakeups, deterministic bounded recovery jitter, callback failure
containment, task ownership, and bounded stop/drain/join behavior.

The follow-up review inspected the remediations for every finding and their focused regression
tests. No unresolved safety, intent, fairness, deadline, task-ownership, or shutdown-liveness
defect remains in this step's scope.

## Findings

### callback-failure-containment | high | One callback exception permanently strands registered controllers

`_WatcherScheduler._invoke` deliberately releases active ownership in `finally`, but lets any
exception from a reevaluation or admission callback escape `_run_cycle` and terminate the sole
scheduler task. The dead scheduler retains all registrations, while the next registration
creates a fresh scheduler containing only the newly registered controller. Existing roots
therefore receive no more deadline reevaluation or fair admission, and no failure is logged or
surfaced. The focused tests cover only successful callbacks and do not prove isolation or
continued progress after either callback class fails.

Resolution: resolved. `_run_cycle` now contains and logs failures independently around both
reevaluation and admission callbacks, while `_invoke` still releases active ownership in its
`finally` path. The regression test proves a failed reevaluation does not prevent the same
cycle's eligible admission, and inspection confirms the equivalent admission boundary cannot
terminate the scheduler task.

### stopping-registration-race | high | Registration can attach to a scheduler that cannot run again

`unregister_root` irreversibly sets `_stopping` when the last registration is removed, while
`_register_watcher_controller` reuses the scheduler until its task has actually completed.
A registration arriving after that state transition but before task completion is stored on
the stopping scheduler without clearing `_stopping`; `run` then exits and leaves the new
controller orphaned. This is possible across roots and within service-loop task interleavings,
and the current join test exercises only unregistering an in-flight callback rather than
registering during the stop window.

Resolution: resolved. Registration now clears the stopping state before publishing the
controller and wakeup. The regression test deterministically removes the last root, registers
a replacement before task retirement, and proves the scheduler is active and nonempty.

### initial-wakeup-recovery-delay | medium | The first wakeup can be discarded and exceed the chosen recovery-jitter window

The first controller is registered immediately after the scheduler task is created, so its
wakeup event is commonly already set when `run` starts. `run` computes a timeout and then
clears that event before waiting. For an overdue recovered controller,
`_recovery_not_before` chooses a stable delay of at most one second, but `_next_timeout`
excludes the overdue controller deadline and falls back to the five-second measurement
interval. The pre-set wake is discarded, so recovery admission can occur roughly five seconds
later instead of at the deterministic not-before instant. The recovery test calls
`_run_cycle` directly and therefore does not cover the production run loop that loses the
wakeup.

Resolution: resolved. The run loop now clears a wakeup only after consuming the wait, and
timeout selection uses the effective recovery not-before deadline even when the persisted
controller deadline is overdue. The new production-loop regression test proves the initial
wakeup is consumed and the subsequent sleep equals the stable bounded jitter.

## Recommendations

- Resolved: contain and report reevaluation and admission callback failures per registration
  so one controller cannot terminate the service scheduler.
- Resolved: reactivate a not-yet-retired scheduler when registration races with last-root
  removal, with deterministic lifecycle coverage.
- Resolved: consume already-signalled wakeups and include `recovery_not_before` in timeout
  selection for overdue persisted deadlines, with coverage through `run`.
