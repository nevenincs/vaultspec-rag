---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S14'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# stamp admission-acquired time on job records and accumulate per-job GPU-lock wait via a timed-acquire helper, publishing both through the existing jobs envelope so queued-shown-as-running is fixed

## Scope

- `src/vaultspec_rag/server/job_manager.py`
- `src/vaultspec_rag/server/job_models.py`
- `src/vaultspec_rag/indexer/_streaming.py`
- `src/vaultspec_rag/embeddings.py`

## Description

- Add a torch-free `GpuLockWaitAccumulator` plus `gpu_lock_wait_scope()` contextvar scope and `timed_gpu_lock()` timed-acquire helper in `src/vaultspec_rag/job_control.py` (commit `c89b7b50`).
- Instrument both gpu_lock sites: the dense-encode acquisition in `src/vaultspec_rag/indexer/_streaming.py` and the sparse-encode acquisition in `src/vaultspec_rag/embeddings.py`; only the acquisition wait is credited, never the forward pass.
- Run the codebase GPU consumer thread under `contextvars.copy_context().run` in `src/vaultspec_rag/indexer/_codebase_indexer.py` so its waits attribute to the owning attempt.
- Activate the scope around `binding.runner` in `JobManager._run_worker_attempt` and publish the total via `set_resources(gpu_lock_wait_seconds=...)` even when the runner unwinds on control or error.
- Add `gpu_lock_wait_seconds` to `JobSnapshot` and its `to_dict`, beside the admission stamp; persistence parses it leniently (`None` on old state).
- Cover with `TestGpuLockWaitTelemetry`: contended-acquire crediting, scopeless inertness, and end-to-end publication on the job record.

## Outcome

The admission-acquired stamp (landed with the P01 gate merge) and the per-job GPU-lock wait are both first-class numbers on the jobs envelope: wall clock now splits into admission wait, lock wait, and work. Three new unit tests green; the full job unit suite (67 tests) green; ruff, basedpyright, ty, complexity, and citation gates all pass.

## Notes

The scope plumbs through a contextvar because the attempt's threads are the unit of attribution; any future indexer thread must be spawned under a copied context or its waits silently drop (stated at the accumulator docstring).
