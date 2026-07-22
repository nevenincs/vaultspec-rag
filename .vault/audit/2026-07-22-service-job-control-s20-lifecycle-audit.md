---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` audit: `S20 lifecycle restore and shutdown`

## Scope

Review `W03.P10.S20` against the accepted plan, ADR, research, reference, and
service lifecycle rules. The review covers canonical manager restoration,
binding every restored active job before dispatch, queued-intent resumption,
paused-intent preservation, the shutdown dispatch gate, cooperative interruption,
bounded watcher and worker drain, persistence truth, teardown ordering, and
supported in-process manager reuse. It also covers extraction of the production
indexing runners from `jobs.py` into `job_dispatch.py`.

Pre-review verification is green for Ruff, BasedPyright, and `git diff --check`.
The focused job-control and jobs unit suites pass 64 tests. The broader
server/lifespan/watcher batch passes 134 tests; its three live-service watcher
cases cannot start because this isolated status directory has no provisioned
Qdrant binary, and the daemon exits with the expected actionable provisioning
error before application startup. No test was skipped or loosened.

The first subprocess attempt inherited the main worktree's editable install and
failed its newer test-containment guard because that unrelated checkout's
managed-singleton session root was absent. Setting `PYTHONPATH` to this isolated
worktree's `src` resolved the source-selection error: the child then loaded this
S20 diff, and exposed only the independent missing-Qdrant-binary prerequisite
described above.

Direct real-manager probes confirm that queued and paused records retain their
states, a cooperative running attempt becomes interrupted only after task,
worker, capacity, lease, writer, and pipeline ownership release, dispatch is
gated, clean in-process reuse reopens, and a timed-out owner remains visible and
prevents reuse. A separate race probe confirms binding remains allowed after
shutdown begins while dispatch returns `dispatch_stopped` and leaves the job
queued.

## Findings

### registry-reuse | high | Clean in-process restart reopens the manager but leaves the registry permanently shut down

`ServiceRegistry.close_all` sets `_shutting_down=True` at
`src/vaultspec_rag/service.py:680-681` and never provides a reopen transition;
both lease paths reject that instance at `src/vaultspec_rag/service.py:401-404`
and `:417-420`. Clean shutdown nevertheless retains the same package registry,
while the next lifespan only reloads its models and reopens the stopped manager
at `src/vaultspec_rag/server/_lifespan.py:263-269` and `:444-459`. The manager
then dispatches restored queued work against a registry whose every lease fails,
and ordinary searches fail likewise. Reopen or atomically replace the one
canonical registry before rebinding and dispatching jobs; do not create a second
registry that diverges from the package and `get_registry()` seams.

### shutdown-signal-failure | high | A watcher-stop failure is diagnostic only and can still permit data-component teardown

`_begin_managed_shutdown` catches `_stop_all_watchers` failures and records only
a reason at `src/vaultspec_rag/server/_lifespan.py:578-593`.
`_watcher_shutdown_status` then declares watcher ownership released solely when
`_wait_for_watcher_cleanup` returns true at `:527-539`, without incorporating
that stop failure. The cleanup snapshot does not include still-public
`_watcher_tasks`, so an exception while iterating roots can leave later watcher
intake active while the wait reports no drains. `resources_released` can
therefore become true at `:485-498`, allowing registry and Qdrant teardown at
`:634-643`. Any failure to close the dispatch/intake gates must fail closed, or
the lifecycle must separately prove that every public watcher was disabled
before teardown.

### published-restore-failure | high | A post-publication restore write failure masks the restore error and breaks lifecycle reuse

`restore_persisted` deliberately retains restored state when its normalization
write may already have been published, returning an error without rolling back
(`src/vaultspec_rag/job_manager.py:1953-2076`; the persistence layer exposes
`published=True` after replacement). `_start_job_manager` unconditionally calls
`abort_startup` for every restore error at
`src/vaultspec_rag/server/_lifespan.py:449-456`, but `abort_startup` rejects any
nonempty active or terminal state at `src/vaultspec_rag/job_manager.py:301-309`.
That secondary `RuntimeError` masks the canonical restore failure and leaves the
manager's restore generation incomplete; cleanup later returns it to `new` with
nonempty state, so the next in-process restore fails `manager_not_empty` again.
Preserve the original restore outcome and add an explicit lifecycle transition
for a retained/published generation, or make abort rollback only when the
manager actually remained empty.

## Recommendations

Revision is required before closing `W03.P10.S20`.

1. Restore the single registry to an admissible startup state before any job
   binding/dispatch on clean embedded reuse.
1. Treat manager/watcher gate-signal failures as ownership-unknown and prohibit
   store, Qdrant, and singleton teardown until release is positively proven.
1. Preserve failure precedence and make published restore failures recoverable
   on the next in-process startup without masking or poisoning manager state.

## Revision response

The S20 revision resolves all three findings without introducing a second
registry or manager authority.

- `registry-reuse`: `ServiceRegistry.prepare_startup` now reopens the exact
  package registry only after `close_all` completed and proved that projects,
  root locks, and shared models were released. `_start_components` invokes that
  transition before Qdrant startup, model load, job rebinding, or dispatch.
- `shutdown-signal-failure`: watcher intake-stop success is now an explicit
  input to `_watcher_shutdown_status`. A stop exception makes watcher ownership
  unreleased even if the asynchronous cleanup snapshot is otherwise empty, so
  `_shutdown_components` records an unclean stop and leaves registry, Qdrant,
  and machine-lock ownership intact.
- `published-restore-failure`: `abort_startup` now distinguishes an untouched
  empty manager from a retained generation. `_start_job_manager` resets only
  the empty case; for retained post-publication state it preserves the original
  restore code and message, completes the generation, and lets the normal
  bounded shutdown flush and close it. A clean in-process retry reuses that
  canonical generation and rebinds it instead of restoring into a nonempty
  manager.

Independent re-review also confirms that all restored active jobs are bound
before any dispatch, only queued jobs whose durable desired state is `running`
resume, and paused jobs remain undispatched. `begin_shutdown` closes the
dispatch gate and signals exact runtime tokens under the manager lock;
bind-after-shutdown remains safe because binding does not reopen dispatch.
Shutdown completion checks task, worker, limiter-capacity, project-lease,
writer-lock, and pipeline ownership globally before permitting registry close.
A timeout therefore retains the manager, registry, Qdrant, and machine lock.
Application or release failures retain precedence over the distinct cooperative
shutdown signal, and the production runner extraction in `job_dispatch.py`
preserves registry injection and CPU-worker/GPU-gate boundaries.

Focused revision evidence is green: Ruff and BasedPyright report no findings,
`git diff --check` passes, and the job-control/jobs unit batch passes 64/64 with
no skip or expected-failure result. A real `ServiceRegistry` probe completed two
close/reopen cycles on the same instance. The executor's real-manager probes
also cover retained published-restore cleanup/rebind, queued/paused reuse,
exact cooperative interruption and release, dispatch gating, timeout
no-teardown, and bind-after-shutdown ordering.

## Re-review verdict

All original findings are resolved, and the final independent pass found no
new in-scope defect. Final disposition: `CRITICAL 0`, `HIGH 0`, `MEDIUM 0`,
`LOW 0`. Approved for `W03.P10.S20` closure.

## Final verification

The final post-review run passes 186 focused job-control, jobs, lifespan, and
server tests. A separate GPU-backed registry, lifespan, and server run passes
159 tests, while 20 non-daemon manager persistence and registry cases pass.
Ruff, BasedPyright, changed-path cognitive complexity, nesting-depth analysis,
and `git diff --check` are clean. The repository-wide complexity gate still
names only established D/F blocks outside the S20 delta.
