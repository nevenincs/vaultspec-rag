---
tags:
  - '#exec'
  - '#index-observability'
date: '2026-07-28'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:f1d6ff095b600b09a52ca4a801d6c9a02cdc140fb2361760cc1edd0c6c191c94'
related:
  - "[[2026-07-28-index-observability-plan]]"
---

# `index-observability` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/indexer/_streaming.py`
- `S01` `M` `src/vaultspec_rag/jobs.py`
- `S01` `M` `src/vaultspec_rag/progress.py`
- `S02` `M` `src/vaultspec_rag/server/_routes_jobs.py`
- `S02` `M` `src/vaultspec_rag/_job_errors.py`
- `S02` `M` `src/vaultspec_rag/jobs.py`
- `S03` `M` `src/vaultspec_rag/watcher_runtime.py`
- `S04` `M` `src/vaultspec_rag/server/_routes_jobs.py`
- `S04` `M` `src/vaultspec_rag/jobs.py`
- `S05` `M` `src/vaultspec_rag/cli/_service_jobs_presentation.py`
- `S05` `M` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S06` `A` `src/vaultspec_rag/tests/test_jobs_degradation.py`
- `S06` `A` `src/vaultspec_rag/tests/test_jobs_degradation_display.py`
- `S06` `M` `src/vaultspec_rag/tests/test_watcher_transition_logging.py`
- `S06` `M` `src/vaultspec_rag/tests/test_progress_unit.py`
- `S07` `verify:` `Current canonical CPU lane just test-python` -> `pass`

## Notes

- `S01` Historical change attribution from Git commit bdbe9d6b. No fresh runtime or unretained historical passing result is asserted.
- `S02` Historical change attribution from Git commit bdbe9d6b. No fresh runtime or unretained historical passing result is asserted.
- `S03` Historical change attribution from Git commit bdbe9d6b. No fresh runtime or unretained historical passing result is asserted.
- `S04` Historical change attribution from Git commit bdbe9d6b. No fresh runtime or unretained historical passing result is asserted.
- `S05` Historical change attribution from Git commit bdbe9d6b. No fresh runtime or unretained historical passing result is asserted.
- `S06` Historical change attribution from Git commit bdbe9d6b. No fresh runtime or unretained historical passing result is asserted. Test authoring is recorded; original gate argv/outcomes are not asserted.
- `S07` Genuine current root-owned configured CPU target completed5810passed8platform-specificskipszero warnings221.50s; exact artifact remediation-full-cpu-holder-fixed.log. This records an executed applicable test dimension only, not a historical gate run, all-marker pytest selection, lint/static results, GPU pass, commit delivery, or whole compound Step acceptance. Full GPU strict-Werror reveals connection lifecycle warnings under repair and final aggregate remains pending. Mechanical execution attribution does not erase these broader evidence limits.
