---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:b8c2491609e137a97f0eae59505732816a1463c0474d7c80dd3b84b71f5a4193'
step_id: 'S66'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Prove a reader overlapping a committing writer on one real ledger file cannot fail that commit, and that the guard fails under a rollback journal

## Scope

- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Description

- Add a deterministic blocking-reader helper that holds an unexhausted cursor over the whole point-id table.
- Add a seeding helper that fills the ledger until scanning it is real work.
- Assert a commit through the production recording path succeeds while that read is held.
- Keep the failing direction executable as a sibling test that starves a rollback-journal commit and asserts the classified kind.

## Outcome

The production failure now reproduces at unit scale and is guarded. Verified in both directions against the real code path: swapping the requested journal mode to a rollback journal fails this test on its recording assertion with the typed contention error carrying SQLite's wording, and restoring write-ahead logging passes it. The mutation was reverted immediately and the sequence is recorded in the module for the next reader.

The failing direction is kept as a test rather than as prose because a contention assertion is worthless if the harness stops producing contention, and nobody would notice that from a green run.

## Notes

The guard was proven against the production code path, not only against the harness. The mutation, the assertion each guard fails on, and the observed error are recorded in the module so the next reader can repeat the check instead of trusting a green run. No mutation was left on disk.
