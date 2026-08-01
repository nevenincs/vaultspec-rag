---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:a53eac9be6b2837c8f8b14661cc4d4a4bf05e56c849b69dc13263dec1e1ea036'
step_id: 'S18'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Submit watcher indexing through JobManager, retain paused convergence slots, coalesce later dirtiness, and schedule cancelled replacements with bounded backoff using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/watcher.py`

## Description

- Route watcher-originated vault and code convergence through the process-wide `JobManager`.
- Transfer dirty paths between pending and immutable attempt generations under a thread lock.
- Retain the exact root/source job ID across pause and same-ID resume while coalescing later dirtiness.
- Hold and report the public registry project lease around each managed indexing attempt.
- Preserve dirty intent after cancellation or failure and admit a new canonical ID after capped exponential backoff.
- Keep watcher intake shutdown separate from manager-owned job cancellation and cleanup.

## Outcome

S18 is complete. Watcher indexing no longer owns an AnyIO worker or limiter path. Manager-owned attempts use the production registry slot, progress reporter, cooperative control token, writer/pipeline resource reporting, scoped changed paths, and leased graph cache. Callback and idle-poll observation are exact-ID idempotent, including immediate queued or paused cancellation and foreign equivalent-job deduplication.

Verification passed: Ruff formatting and lint, basedpyright, ty, and diff validation; 9 watcher filter/config tests; 11 managed index-control integration tests; 47 jobs unit tests; and a bounded real GPU/model/indexer/store probe covering held lease observation, pause release, same-ID resumed convergence with later dirtiness, cancellation release, dirty retention, finite replacement delay, and successful convergence under a new ID. A real capacity probe confirmed retry delays progress once per eligible failure from 1.0 to 2.0 seconds.

Independent review approved the step with Critical 0, High 0, Medium 1, Low 0.

## Notes

- `W04.P12.S23` must correct the legacy compatibility projection that leaves canonical paused or queued watcher jobs with legacy `phase=running`, which can produce false running/stalled summaries. Canonical manager state and resources remain truthful.
- `W03.P11.S21` is gating debt: migrate the obsolete standalone local-store watcher test topology to the public registry and add real pause-coalescing, cancellation-dirtiness, replacement, watcher-stop, and cleanup-join coverage before phase or Wave acceptance.
- Three watcher-control cases encountered external daemon readiness connection refusal before their assertions; they did not expose an S18 source failure.
- No production fallback, fake, mock, stub, patch, monkeypatch, skip, or xfail was added.
