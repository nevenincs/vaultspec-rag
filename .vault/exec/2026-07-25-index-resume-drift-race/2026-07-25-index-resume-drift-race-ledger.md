---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:2951d41fd7f7b7e38ff39a9fe16f13dea85b455a100200ca9ac68539bb7f207e'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# `index-resume-drift-race` ledger

## Changes

- `S01` `T` `src/vaultspec_rag/tests/`
- `S02` `T` `src/vaultspec_rag/indexer/`
- `S03` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S04` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S05` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S06` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S07` `T` `src/vaultspec_rag/indexer/_run_ledger.py`
- `S08` `T` `src/vaultspec_rag/indexer/_run_checkpoint.py`
- `S09` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S10` `T` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S12` `T` `tools/module_length.py`
- `S13` `T` `src/vaultspec_rag/tests/`
- `S15` `T` `src/vaultspec_rag/indexer/_run_checkpoint.py`
- `S16` `T` `src/vaultspec_rag/tests/test_indexer_unit.py`
- `S17` `M` `src/vaultspec_rag/indexer/_content_discovery.py`
- `S11` `M` `src/vaultspec_rag/indexer/_drift_owner.py`
- `S14` `M` `src/vaultspec_rag/tests/integration/test_indexer_integration.py`
- `S14` `verify:` `Retained live served-drift test test_served_retry_supersedes_a_moving_source_and_clears_degradation in .pytest-tmp/remediation-served-drift-live.log (2026-10-01 frozen remediation source; required runtime outcome failed)` -> `fail`
- `S14` `verify:` `Retained real served retry in .pytest-tmp/remediation-served-drift-repaired.log at source digest f02581e0a00bc2351080e1454c6c9fab184fc795cf202905f797069ba4dde700, 2026-10-01, required public drift outcome` -> `fail`
- `S14` `A` `src/vaultspec_rag/tests/integration/test_served_resume_drift.py`
- `S14` `A` `src/vaultspec_rag/tests/integration/_served_drift_control.py`
- `S14` `verify:` `PYTHONWARNINGS=error pytest test_served_resume_drift.py -q -W error after retained-ID launcher and manager drift repairs` -> `pass`
- `S11` `M` `src/vaultspec_rag/job_manager/_execution.py`
- `S11` `M` `src/vaultspec_rag/job_manager/_control.py`
- `S11` `M` `src/vaultspec_rag/job_manager/_persistence.py`
- `S11` `A` `src/vaultspec_rag/tests/test_job_manager_drift.py`
- `S11` `verify:` `PYTHONWARNINGS=error pytest manager drift transition degradation and persistence coverage -W error 122 tests` -> `pass`
- `S11` `verify:` `Four managed drift handoff and omission guards intended RED restored GREEN` -> `pass`
- `S11` `verify:` `Actual served moving-source retry reports positive superseded paths and clears degraded health -W error` -> `pass`

## Notes

- `S17` Historical change attribution from Git commit 3919803a; commit records this Step's scoped implementation or review. No fresh runtime verification or historical unrecorded pass is asserted.
- `S11` Historical attribution: 536ea2593cce8c6ca9158f3f901b604df591c31c feat(indexer): report drift volume the circuit breaker cannot see. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S14` Actual historical partial verification work at51b6c15988aebf1aaaba59debe29387b72781999 adds a resumed local-indexer run with real corpus churn and whole-run outcome assertion. Current source inspection confirms CPU BoW/local store, positive churn revisions, result.total greater than0, and drift key shape. It does not require positive `superseded_paths,` use a live HTTP daemon, or couple recovery to cleared degraded health. Separate health unit coverage is not integrated with churn. This row records genuine test-source work only; original live-service compound acceptance remains a substantive audit gap, with no whole-Step or runtime PASS invented.
- `S14` Fresh 2026-10-01 real served retry failed its production applied-point accounting barrier (expected 13, found 12) and teardown reported a still-running spawned launcher process. The retained report has one failed call and one teardown error in 50.36 seconds. S14 reopened against actual contrary runtime evidence; earlier narrow code-operation and historical observations remain unchanged and do not establish completed live acceptance. No successful supersession, completion or cleared degradation is claimed from this run.
- `S14` Second fresh live run: one functional failure in 45.75 seconds, zero warnings. Retry succeeded after applied-point repair and the launcher warning was absent, but public job drift was None and the positive superseded-path acceptance guard failed. S14 remains open; no completed live acceptance is claimed.
- `S14` Actual live service acceptance passed: 1 passed in 40.99 seconds, zero warnings. The source changed after retry admission and a real durable source commit; the unchanged strong assertions require a positive superseded-path counter, completed retry, same source and root, retained original failure finish/error history, and ready health with `job_failed` cleared. The two earlier actual failures remain recorded. Focused pipeline, launcher and manager verification passed with intended RED/restored GREEN guards; independent review found no concrete blocker. Performance S04 and final full CPU/GPU/aggregate verification remain open; no commit or push.
- `S11` The real served retry exposed dropped drift telemetry in the terminal manager handoff. Typed propagation now carries the indexer result through terminal transition and persistence to public state; omitted later transitions retain prior telemetry. Actual dispatch, latest revision reload and public serialization are exercised by the focused positive-counter guard. Fault-only circuit classification is unchanged. No historical entries were removed; the original failure and its repair remain auditable.
