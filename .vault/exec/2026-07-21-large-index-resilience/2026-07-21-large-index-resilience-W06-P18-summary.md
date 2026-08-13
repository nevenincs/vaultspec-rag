---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:d6ba479f58a8ec390e5e51638313eb349462684260085bcd46c4bb3bdb3d12d4'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` `W06.P18` summary

## Description

Added the overlapping-access coverage that could observe this defect class at all.

A deterministic blocking reader holds an unexhausted cursor over the whole point-id table - the lock shape a paging iterator and an integrity scan both have - while commits go through the production recording path. Two guards use it: one asserting a long read cannot fail a concurrent commit, one asserting a held read starves neither content kind on the shared file. Both were verified in both directions against the real code path, not merely against the harness: swapping the requested journal mode to a rollback journal fails each on its recording assertion with the typed contention error, and restoring write-ahead logging passes both. The mutation was reverted immediately and the sequence is recorded in the module.

The failing direction is also kept as an executable test that starves a rollback-journal commit, so a harness that stops producing contention fails visibly rather than letting the guards beside it pass vacuously.

A cross-process test spawns separate interpreters that open the same ledger, run the full scan, and commit concurrently. Its scope is stated in the test itself: it covers multi-process correctness, not the journal mode, because it passes under a rollback journal too.

Artifacts: `src/vaultspec_rag/tests/test_index_run_ledger.py`.

Notes: two tests were discarded during this phase rather than kept. The first cross-kind guard passed against the deliberately broken build once the scan came off the open path, so it was rewritten around a deterministically held read. The planned live-service load test was not taken - its fixture is GPU-gated and would have contended with the operator's running service and resident model memory on this machine, and an unexecutable heavyweight test is worth less than a lighter one that was actually run.
