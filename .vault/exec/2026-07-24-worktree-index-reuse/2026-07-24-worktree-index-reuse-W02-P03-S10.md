---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:f893d6799997c2f84eb34957899f90b62500ae5c75355f37201c1ac425c09459'
step_id: 'S10'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# add per-job reuse telemetry (hit count, hit rate, GPU-seconds-saved estimate, donor-absent rate) surfaced through the existing job status envelope

## Scope

- `indexer job accounting`
- `server jobs surface`

## Description

- Add `ReuseStats` per-job counters in `src/vaultspec_rag/indexer/_reuse.py`: `reuse_hits`, `reuse_misses`, derived `hit_rate`, `gpu_seconds_saved` (hits x this job's own measured per-chunk miss-encode cost, timed at the seam; documented constant fallback `FALLBACK_ENCODE_SECONDS_PER_CHUNK = 0.02` only when the run encoded nothing), `donor_absent`, and the consulted donor collection list; `snapshot()` emits the JSON-ready block.
- Flow the block the same way preprocess counters already flow: `IndexResult.reuse` (all three indexers populate it from the run's stats; `None` when the knob is off), `JobExecutionResult.reuse`, the three dispatch runners in `src/vaultspec_rag/job_dispatch.py`, the watcher's managed attempt in `src/vaultspec_rag/watcher.py`, and `record_start`/`record_finish` in `src/vaultspec_rag/jobs.py`, which stamp a `reuse` field on the job record served by `/jobs` (server jobs CLI and MCP read the same envelope; no CLI-only computation).
- Surface the block on the direct CLI index rows in `src/vaultspec_rag/cli/_index.py` when present.

## Outcome

- One new nullable `reuse` field rides the existing job record; no new persistence, no new envelope, `None` everywhere reuse is disabled so prior consumers are unaffected.
- `gpu_seconds_saved` prefers the job's own measured encode rate over any constant; the fallback path is exercised and asserted by the all-hits test.
- Jobs and server-route unit suites pass unchanged plus the new telemetry assertions (`test_jobs_unit.py`, `test_server_routes.py`: 61 passed).

## Notes

- The canonical `JobSnapshot.to_dict()` view carries only the summary string (same as the preprocess counters it mirrors); the structured block lives on the activity record `/jobs` merges in. Extending the canonical snapshot model was deliberately left out of scope to keep the change consistent with how the existing index stats flow.
