---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:59ec1d23e894168db37c5e68d6f90383fcfff502f63127966ed2d0f322024f76'
step_id: 'S68'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Exercise overlapping index and search load against a live service on a realistic corpus and assert no locked-database outcome

## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`

## Description

- Add a cross-process test spawning separate interpreters that each open the same ledger, run the full integrity scan, and commit units concurrently.
- Assert every worker exits clean, reports no lock in its diagnostics, and that the final committed-unit count is exact.

## Outcome

Covers what a CLI run, a service run, and a recovering run on one root actually share: only the database and its locks. Threads in one interpreter share a SQLite library and can mask a file-level mistake; separate processes cannot.

Scope is stated in the test itself rather than implied, because this one does not discriminate the journal mode - it passes under a rollback journal too, since no single read here is long enough to exhaust the busy budget. It covers multi-process correctness: every unit committed exactly once, an exact final count, no corruption. The journal-mode property is guarded by the two sibling tests that were verified to fail without it.

The originally planned shape was overlapping index and search load against a live service. That was not taken: the live-service fixture is GPU-gated and would have contended with the operator's running service and its resident model memory on this machine, and shipping a heavyweight test that could not be executed here would have been worse than shipping a lighter one that was.

## Notes

This test does not discriminate the journal mode and its docstring says so, because it passes under a rollback journal too. The planned live-service load test was not implemented: its fixture is GPU-gated and would have contended with the operator's running service and resident model memory on this machine. Writing an unexecutable heavyweight test would have been worse than shipping the lighter one that was actually run, so the deviation is recorded rather than hidden.
