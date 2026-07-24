---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S01'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# implement the machine-wide encode-job admission gate in the job dispatch layer with honest queued state stamped on job records

## Scope

- `src/vaultspec_rag/server/job_dispatch.py`
- `job records`

## Description

Implemented the machine-wide encode-job admission gate in the managed dispatch layer, in an isolated worktree (branch worktree-agent-a4ae2400749f6bfde, commit `91a843ed`; rebases onto main after the reuse feature lands). No new semaphore: a fixed one-token `get_encode_limiter()` sits beside the existing pool partition (`src/vaultspec_rag/concurrency.py:68`); `JobManager._attempt_limiter` (`src/vaultspec_rag/job_manager.py:779`) selects it spec-driven via the new `is_encode_bearing` predicate (`src/vaultspec_rag/job_models.py:445`) - INDEX x {vault, code, document}. The daemon is the machine singleton, so in-process equals machine-wide. Exemptions hold by construction: searches, the maintenance tick, and donor reads never reach `_run_attempt`; a source-scan guard additionally forbids the maintenance/search/lifecycle modules from naming the encode limiter. Honest state: `admission_acquired_at` stamped on `JobTimestamps` at the exact admission moment inside `_run_worker_attempt`'s resource transaction (`job_manager.py:818`), serialized through the single `to_dict()` shape every consumer reads, persisted with validation, cleared on any `started_at` rewrite; `None` on a live attempt means waiting, and the delta from `started_at` is the measured admission wait. `limiter_stats()` gains an encode pool that flows into the metrics surface automatically. Known semantic note recorded: a slot-waiting job remains state RUNNING (pre-existing limiter semantics), now honestly discriminated by the stamp.

## Outcome

## Notes
