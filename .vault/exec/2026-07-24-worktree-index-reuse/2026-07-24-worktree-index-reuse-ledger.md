---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:f2a71e658b973c305af66017e5862ae3f06e43c5f89819594cdb472496d2aaa2'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# `worktree-index-reuse` ledger

## Changes

- `S01` `T` `src/vaultspec_rag/indexer/_streaming.py`
- `S01` `T` `-`
- `S02` `T` `record old-vs-new wall-clock`
- `S02` `T` `reuse hit rate`
- `S02` `T` `and fresh-namespace upsert plus prealloc wall-time`
- `S02` `T` `scratch namespace run`
- `S02` `T` `numbers into the Step Record`
- `S03` `T` `.vault/adr/2026-07-24-worktree-index-reuse-adr.md`
- `S03` `T` `working tree`
- `S04` `T` `src/vaultspec_rag/indexer/_donor_candidates.py`
- `S05` `T` `src/vaultspec_rag/indexer/_donor_candidates.py`
- `S06` `T` `src/vaultspec_rag/tests/test_donor_candidates.py`
- `S07` `T` `src/vaultspec_rag/config.py`
- `S07` `T` `indexer wiring`
- `S08` `T` `local mode same-process handles only)`
- `S08` `T` `src/vaultspec_rag/store.py`
- `S09` `T` `src/vaultspec_rag/indexer/_streaming.py`
- `S10` `T` `indexer job accounting`
- `S10` `T` `server jobs surface`
- `S11` `T` `src/vaultspec_rag/tests/test_index_reuse.py`
- `S12` `T` `record both directions in the Step Record`
- `S12` `T` `src/vaultspec_rag/tests/test_index_reuse.py`
- `S13` `T` `src/vaultspec_rag/tests/test_donor_candidates.py`
- `S14` `T` `src/vaultspec_rag/tests/test_donor_candidates.py`
- `S15` `T` `src/vaultspec_rag/tests/test_donor_candidates.py`
- `S16` `T` `repository quality gates`
- `S17` `T` `capture and record the telemetry and headline wall-clock in the Step Record`
- `S17` `T` `live service run`
- `S17` `T` `Step Record`
- `S18` `T` `docs/`
- `S20` `T` `repro plus fix plus guard test`
- `S20` `T` `escalating if the ledger delete contract must change`
- `S20` `T` `src/vaultspec_rag/indexer/_run_checkpoint.py`
- `S20` `T` `storage delete surface`
- `S20` `T` `tests`
- `S19` `verify:` `Read-only GitHub main ancestry of why-focused feature commit820c4b782f70193590327dbf2a8648bdf5d39995` -> `pass`

## Notes

- `S19` Current GitHub compare820c4b78...main returns ahead with `behind_by0` and `merge_base` equal to the feature commit; local merge-base ancestor check also exits0. GitHub commit metadata retains the why-focused donor-reuse change message. This proves the actual feature commit is present on remote main, not an invented historical push command or timing. No Git mutation performed.
