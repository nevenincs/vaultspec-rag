---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:8872f098b0b296d585c82c1a6f2d0cdfc89c14d88fdd6f30e61b2af51f80415e'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` `W06.P17` summary

## Description

Made lock contention a typed, retryable outcome instead of a terminal one.

SQLite's spellings for a held lock now classify as their own transient job-error kind, ahead of the timeout markers, with operator remediation stating that storage-confirmed work is intact and the run resumes from its last checkpoint. Previously they fell through to the unclassified bucket, which reads as a terminal fault - that fallthrough was the whole cost of the original incident, discarding a generation holding hundreds of committed units for a condition that would have cleared on retry.

The storage-confirmed recording path - the one that failed in production - now replays under a bounded budget with short backoff. Replay is safe by construction there: a contended transaction rolls back whole, and an exact replay of an already-recorded unit reports zero insertions. Only contention is replayed; an unrelated operational error surfaces on first sight. Exhaustion raises a typed error carrying SQLite's own wording, so the condition stays classifiable at the service boundary.

The classifier's branch chain became an ordered marker table, which made first-match-wins precedence explicit rather than implied by statement order.

Artifacts: `src/vaultspec_rag/_job_errors.py`, `src/vaultspec_rag/indexer/_run_ledger_models.py`, `_run_ledger_commits.py`.

Safety: classification verified end to end for both spellings and for the typed error's own message; unrelated operational errors verified not to retry.
