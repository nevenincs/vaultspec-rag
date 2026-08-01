---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:1ae7aae19cdbd20f8404d17ed1cf4eee2ba56e6fb7820f8d149391e9edc4635d'
related:
  - "[[2026-07-21-service-job-control-plan]]"
  - "[[2026-07-21-service-job-control-adr]]"
---

# `service-job-control` audit: `S19 watcher stop and drain`

## Scope

Reviewed `W03.P08.S19` against the accepted plan, ADR, research, reference,
and watcher/storage/concurrency rules. The review covered the complete changes
in `server._watcher`, the registry injection in `watcher`, the server package
export, exact manager-attempt joining, synchronous registry-close callbacks,
stop/reconfigure epochs, deferred warm-up ownership, timeout truth, canonical-job
non-mutation, and affected verification.

## Findings

### watcher-stop-complexity | medium | The lifecycle rewrite exceeds both enforced complexity limits

The new `_ensure_watcher_soon` reports cognitive complexity 22 against the
project limit of 20, and `_wait_for_watcher_cleanup` receives xenon grade D
with complexity 26 against the configured absolute grade C. This is an enforced
quality-gate regression. The interleaved deferred, suppressed, starting,
draining, and restarting maps also make epoch ownership difficult to prove and
have hidden a missing timeout-recovery transition. Split the transitions into
focused helpers or one per-root owner object until the repository gate passes.

### watcher-drain-retry | high | One cleanup timeout can permanently suppress a later watcher start

When `_drain_watcher` reaches its bounded deadline, its `finally` block clears
`drain.cleanup_task` but leaves the drain in `_watcher_drains`. No completion
callback or retry is scheduled when the exact manager attempt later releases.
Both `_ensure_watcher` and `_ensure_watcher_soon` merely record a restart when
they find that retained drain; neither reschedules cleanup. An indexing attempt
that outlasts `job_shutdown_timeout_seconds` can therefore leave every later
start or reconfigure request reporting success while intake never restarts.

### registry-close-drain | high | The synchronous close callback can still close a project before watcher ownership drains

`ServiceRegistry.close_project` calls `_on_close_project` and immediately
removes and closes the slot. The installed callback is `_stop_watcher`, which
now schedules an async drain and returns without waiting. Unlike LRU/manual
eviction, `close_project` does not reject a nonzero lease count. A watcher
attempt can therefore hold a project lease while a concurrent public
`close_project` proceeds to `slot.store.close()`, or intake can admit an attempt
between callback return and close. Strong private task ownership does not
serialize this path, so the requirement not to close stores under live workers
remains unmet.

## Recommendations

Revision is required before closing `W03.P08.S19`.

1. Make a retained timed-out drain self-retrying, or have every subsequent start
   path reschedule and await it before claiming intake restarted.
1. Replace the fire-and-forget synchronous close callback with a boundary that
   prevents `close_project` from closing until exact watcher attempts and leases
   release, without cancelling or mutating canonical jobs.
1. Decompose the watcher lifecycle until the project complexity gate is green,
   then rerun the stop/timeout/restart and concurrent-close probes.

## Revision response

The S19 revision resolves all three findings without expanding the registry
lifecycle protocol.

- `watcher-stop-complexity`: `_run_deferred_watcher_start`,
  `_watcher_cleanup_snapshot`, `_schedule_watcher_drains`, and
  `_watcher_cleanup_results_ok` now isolate the previously interleaved
  transitions. The scoped complexity check reports no new S19 offender. The
  repository-wide complexity command remains red only on pre-existing files
  outside this step's diff.
- `watcher-drain-retry`: both `_ensure_watcher` and `_ensure_watcher_soon` now
  reschedule a retained drain after recording the requested restart. A timed-out
  cleanup therefore retains ownership truth and is retryable when a later start
  or reconfigure request arrives.
- `registry-close-drain`: `ServiceRegistry.close_project` signals watcher intake
  first, then delegates the existence, lease-count, and removal decision to the
  atomic `try_evict` path. A live lease returns `busy` and is surfaced as
  `ProjectBusyError`; the store remains registered and open until the lease is
  released. No asynchronous watcher cleanup is treated as permission to close a
  leased store.

Focused revision evidence is green:

- `test_server.py`: 120 passed, covering the server package and watcher wiring.
- `TestCloseProject`: 3 passed against the real registry and stores.
- `TestLeaseApi::test_try_evict_reports_busy_while_leased`: 1 passed against a
  real project lease, proving busy refusal followed by successful eviction after
  release.
- BasedPyright on the four changed production modules: 0 errors, 0 warnings.
- Ruff and `git diff --check`: clean.

The earlier real registry probe also exercised `close_project` itself while a
real lease was held: it raised `ProjectBusyError`, retained the same live slot
and store, and closed successfully after lease release.

## Re-review verdict

The focused independent re-review confirms that the original findings are
resolved: both ensure paths reschedule retained timeout drains, explicit project
closure uses the atomic busy-safe eviction decision and leaves leased storage
open, and the two S19 complexity offenders no longer exceed their enforced
per-block thresholds. Watcher stop still does not cancel, pause, resume, or
otherwise mutate canonical jobs.

Independent verification found no new in-scope issue. Ruff, the scoped cognitive
complexity check, and `git diff --check` pass. The real `TestCloseProject` and
busy-lease eviction cases pass 4/4; the repository-wide complexity output names
only pre-existing D/F blocks outside this S19 diff.

Final disposition: `CRITICAL 0`, `HIGH 0`, `MEDIUM 0`, `LOW 0`. Approved for
`W03.P08.S19` closure.
