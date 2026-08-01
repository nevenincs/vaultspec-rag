---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-24'
modified: '2026-07-27'
body_hash: 'sha256:6a7f7f76e82a0b7c285d403af3fc242d5e67de70b4d1c8e277e093c1ae976493'
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

Evidence gap: `2026-07-24-index-throughput-plan` marks `P01.S01` closed, while this record's retained body and complete git log --follow history do not state an implementation result. No outcome beyond that source-attributed plan state is asserted.

## Notes

Template evidence: intro_commit=d81c21c6f44aed3da9929714232da41e21367d60; template_commit=d81c21c6f44aed3da9929714232da41e21367d60:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
