---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` `W01.P02` summary

The canonical job model, exact-ID manager, lifecycle protocol, and durable recovery authority
are implemented as one service-domain contract.

- Modified: `src/vaultspec_rag/jobs.py`

## Description

Immutable job specifications, resource and progress snapshots, revisioned views, structured
outcomes, capabilities, attempts, and canonical states now describe every managed job.
`JobManager` enforces bounded admission, normalized-root active-work deduplication, bounded
idempotency retention, exact task ownership, and bounded terminal history.

Pause, resume, cancellation, retry, deletion, acknowledgement, and first-terminal-writer-wins
transitions use optimistic revisions and deterministic ownership checks. Versioned persistence
uses atomic replacement and complete-generation validation; queued and paused work restores,
while crashed live attempts become retained `interrupted` history. The post-phase audit also
closed durability rollback, capability, resource acknowledgement, and restore-validation gaps.
