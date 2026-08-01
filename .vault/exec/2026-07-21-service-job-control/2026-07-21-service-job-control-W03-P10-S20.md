---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:2fbd8e90757f35b1e7b37cc710032ecb7a716cdacb69b500ae4a7e54423a4622'
step_id: 'S20'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Restore the single manager, resume durable queues, preserve pauses, drain workers before store closure, and report unclean shutdown truthfully using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Restore and reopen the one canonical manager after model readiness, bind every
  durable active job, dispatch only queued running intent, and preserve pauses.
- Add a distinct cooperative shutdown request that terminalizes released
  attempts as interrupted without overriding application or release failures.
- Stop dispatch and watcher intake before periodic cleanup, then await watcher
  and manager ownership concurrently under the configured shutdown bound.
- Separate resource-release safety from persistence durability so failed writes
  report an unclean stop without unnecessarily retaining released components.
- Keep registry, Qdrant, and machine-lock ownership intact when workers,
  watchers, or gate closure remain unproven.
- Reopen the same fully cleared registry and manager for supported clean
  in-process lifecycle reuse; preserve retained restore failures for bounded
  cleanup and later rebinding.
- Extract production vault and code attempt runners from `jobs.py` into
  `job_dispatch.py`, retaining exact registry injection and load-before-lease
  ordering.

## Outcome

Service startup now restores durable canonical state after the models are ready,
attaches all production execution bindings before starting work, resumes queued
running intent, and leaves paused intent dormant under the same IDs. A clean
in-process restart reopens the same cleared registry and reuses the manager's
in-memory generation without a conflicting second restore.

Shutdown closes dispatch and watcher intake first. Cooperative workers unwind
through their existing release boundaries and become interrupted only after
task, worker, capacity, project lease, writer lock, and pipeline ownership are
clear. Resource survivors prevent registry, Qdrant, and machine-lock teardown;
persistence failure is reported as unclean but does not falsely imply live
ownership. Newly admitted work during stopping remains durably queued because
binding is allowed while dispatch stays gated.

Verification passed: 186 focused job-control, jobs, lifespan, and server tests;
159 service-registry, lifespan, and server tests with real GPU-backed registry
behavior; and 20 non-daemon manager persistence and registry tests. Real probes
covered queued and paused preservation, interruption after release, timeout
survivors, bind-after-stop, failure precedence, registry two-cycle reuse,
watcher-stop failure safety, and retained restore cleanup/rebinding. Ruff,
BasedPyright, changed-path cognitive complexity, nesting, and diff hygiene pass.
Independent review closed at Critical 0, High 0, Medium 0, Low 0.

## Notes

The repository-wide complexity command remains red on pre-existing D/F blocks;
the S20-touched completion and drain paths are below the configured limits.
Three live watcher-service cases could not start because the isolated status
directory had no provisioned pinned Qdrant binary. The child loaded this
worktree after `PYTHONPATH` correction and exited at the expected provisioning
guard before application assertions. No test was skipped or loosened.

No fake, mock, stub, patch, monkeypatch, skip, expected failure, forced task
cancellation, or destructive cleanup was added.
