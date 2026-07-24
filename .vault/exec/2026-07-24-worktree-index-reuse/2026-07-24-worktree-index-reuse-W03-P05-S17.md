---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S17'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---
# run the end-to-end fork index with the flag on and off against a real sibling donor

## Scope

- `capture and record the telemetry and headline wall-clock in the Step Record`
- `live service run`
- `Step Record`

## Description

- Provisioned a byte-near-identical fork: a fresh worktree of this repository
  checked out at the resident service worktree's committed HEAD, so its tracked
  bytes match the donor namespace's indexed content.
- Ran the live service (machine-singleton, port 8766, from the resident venv)
  code index of the fork with the reuse off-switch forced off, then on,
  clearing the scratch namespace and its resume ledger before each run.
- Captured per-job telemetry and wall-clock; cross-checked donor discovery and
  eligibility read-only in-process against the same live storage.
- Restored the service to default config and removed the scratch fork.
- FOLLOW-UP (same day): root-caused and fixed the blocking null-telemetry
  anomaly, and root-caused and fixed the storage-delete/resume-ledger replay
  hazard recorded in the Notes (now plan step S20).

## Outcome

- Flag OFF baseline (clean from-scratch code rebuild, constrained profile and
  batch to fit the shared 16 GB GPU): 311 s wall, ~1,988 code chunks, ~4.6-5.0
  GB peak CUDA; reuse telemetry correctly absent.
- Flag ON (default-on, present eligible sibling donor): ~311 s wall, ~4.6 GB
  peak CUDA (full GPU encode), no reuse hits and no telemetry block - an
  effective 0% hit rate. The anticipated fork speedup was NOT observed.
- ROOT CAUSE (resolved): the null reuse block on the job record was stats
  plumbing, not the resolver. The reuse block rode only the legacy activity
  record (`record_finish(..., reuse=...)` via `_sync_legacy_finished`,
  `src/vaultspec_rag/jobs.py:1042`), while the served job view
  (`_service_job_snapshot`, `src/vaultspec_rag/server/_routes.py:442-451`)
  prefers the canonical `JobManager` snapshot for every manager-owned job -
  and `JobSnapshot.to_dict()` (`src/vaultspec_rag/job_models.py`) carried no
  reuse field at all. Every daemon-dispatched job therefore served
  `reuse: null` regardless of what the run resolved, making "reuse never
  engaged", "donor absent", and "hits adopted" indistinguishable from the
  outside. Config (suspect 1) and the rebuild funnel (suspect 2) were
  affirmatively cleared: the support profile does not gate the knob (new
  regression test in `tests/test_config.py`), and the daemon rebuild funnel
  (`job_dispatch._run_code_attempt` -> `full_index` ->
  `_pipeline_chunk_and_embed`) resolves donors at pipeline entry and adopts
  hits end-to-end, as the new integration test proves.
- FIX: the canonical job resource now carries the telemetry - `reuse` field on
  `JobSnapshot` + `to_dict`, threaded through
  `JobManager.finish_attempt`/`_commit_attempt_exit`/`_replace_snapshot_locked`
  (`src/vaultspec_rag/job_manager.py`), and restored on state reload
  (`src/vaultspec_rag/job_persistence.py`, lenient for pre-fix state files).
- FAILING-TEST-FIRST EVIDENCE (both directions recorded): the new permanent
  integration test
  `tests/integration/test_index_reuse_daemon_path.py::test_rebuild_job_record_carries_donor_reuse_telemetry`
  drives the real daemon funnel (JobManager + `bind_index_job` + production
  registry + real supervised qdrant + real GPU model, isolated STATUS_DIR /
  QDRANT_STORAGE_DIR, byte-identical sibling donor) and asserts the SERVED
  record carries `reuse_hits > 0`, `hit_rate > 0`, `gpu_seconds_saved > 0`.
  RED before the fix on exactly the defect
  ("`isinstance(None, dict)` - served job record dropped the reuse block");
  GREEN after. The flag-off leg
  (`test_flag_off_rebuild_job_record_has_no_reuse_block`) stays green: knob
  off still serves `reuse: null`.
- FALSE-COVERAGE ACKNOWLEDGEMENT (guard-tests lesson): the 11 seam-level unit
  tests in `tests/test_index_reuse.py` were green the whole time the feature
  was operationally inert - they exercise the encode seam below the job
  funnel and could not observe the record-layer drop. That green tally is
  exactly the false-coverage class the guard-tests rule warns about: it
  consumed the attention that would have gone looking. The new daemon-path
  test is positioned at the layer this defect lived in and would have caught
  it.
- RE-MEASUREMENT (redeployed daemon, current tree loaded, embedded-local
  profile matching the 311 s baseline, single shared 16 GB GPU): the reuse
  block is now PRESENT and populated on every served record - itself the
  proof that the JobSnapshot snapshot fix is live in the restarted daemon -
  and the feature engages end-to-end through the production funnel. Two
  flag-ON legs, both against the resident storage's eligible sibling donors:
  - Byte-identical fork (a byte-for-byte file copy of the indexed fork, so
    the donor's stored bytes match exactly): 100.0% hit rate
    (6,424 hits / 0 misses of 6,424 chunks), 28.7 s wall-clock,
    128.5 estimated GPU-seconds saved, `donor_absent: false`. HEADLINE:
    311 s flag-OFF -> 28.7 s flag-ON, a 10.8x wall-clock reduction with
    zero forward passes for the whole corpus.
  - Realistic git-checkout fork of HEAD (donor = the live `main` namespace):
    69.2% hit rate (4,448 hits / 1,976 misses of 6,424 chunks), 45.8 s
    wall-clock (still 6.8x under baseline), 52.2 GPU-seconds saved. The
    ~31% miss share is the byte-vs-git-identity gap the ADR measured: a
    fresh `git worktree` checkout renormalises line endings, so its bytes
    diverge from the donor's indexed bytes on the CRLF-divergent files and
    the per-point content verify correctly MISSES them rather than adopting
    a mismatched vector - divergent content pays today's encode cost, which
    is exactly the designed-for behaviour. Only 21 tracked files differ
    between HEAD and `main`'s working tree, far too few to explain the
    misses, confirming the cause is byte renormalisation, not stale content.
- Both acceptance signals are therefore met on the clean leg: ~100% hit rate
  on the served record AND a large real wall-clock reduction versus the
  311 s flag-OFF baseline. The earlier "effective 0% hit rate, null
  telemetry" observation is fully explained and retired: it was the served
  record dropping the reuse block on a measurement-time daemon that predated
  the seam code, not a donor-selection or adoption failure.

## Notes

- Ledger replay hazard (now plan step S20) - RESOLVED as a defect, not
  correct-by-design: `storage delete` drops the collection but leaves the
  per-root resume ledger (`index_runs.sqlite3`), so a later `--rebuild`
  resumed the interrupted generation, skipped its "storage-confirmed" units
  with zero GPU work, and published a success whose committed portion no
  longer existed anywhere (silent data loss masquerading as a fast rebuild).
  Fix: `_open_run_checkpoint` retires (INVALIDATED) any generation carrying
  commit evidence while the code collection is absent
  (`_checkpoint_evidence_lost`, `src/vaultspec_rag/indexer/_codebase_indexer.py`;
  existence probe `VaultStore.code_collection_exists`). Guard test
  `tests/integration/test_index_job_control.py::test_clean_rebuild_reencodes_when_collection_vanished_under_the_ledger`:
  RED before the fix (store missing exactly the committed files while the
  rebuild reported success), GREEN after (full re-encode, `resumed_units == 0`).
  Residual, contract-level and out of local scope: the INCREMENTAL path's
  parent-manifest carry has the same staleness exposure after external
  collection destruction; honest behaviour there likely means demanding a
  full reconciliation - flagged for a decision rather than fixed here.
- The measurement hazard note above is thereby superseded: clearing the
  resume ledger by hand is no longer required for honest rebuild timings.
- Gates on touched files: ruff check/format, basedpyright, ty, complexity
  gate (CCR001/xenon/nesting), and the citation gate all green; affected
  unit suites (jobs, job control, resilience, server routes, index reuse,
  config, ADR regression: 256 passed) green; the new daemon-path integration
  suite (2 tests) and the appended ledger guard test green.
- PRE-EXISTING failure, NOT from this session's work:
  `tests/integration/test_index_job_control.py::test_managed_application_failure_wins_over_pending_cancel`
  fails deterministically on this box (job ends CANCELLED instead of FAILED;
  the expected dimension-mismatch upsert failure never fires). Verified
  unrelated three ways: it fails with the reuse knob forced off, the failure
  path overlaps neither the reuse feature diff nor this session's diff, and
  it fails identically against a pristine HEAD worktree with none of the
  uncommitted work present. Needs its own triage.
- Work left uncommitted on purpose (session mandate); no plan checkboxes
  touched.
