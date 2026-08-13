---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:315ad455b1362bcf1f7f3a9c2022c506cff337c6c4dc128d10527598b11218e7'
step_id: 'S64'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Classify a busy or locked database as a typed transient condition rather than an unclassified failure

## Scope

- `src/vaultspec_rag/_job_errors.py`

## Description

- Add a distinct transient job-error kind for durable-state lock contention.
- Match SQLite's two spellings for a lock a peer already holds, ahead of the timeout markers.
- Restructure the classifier's marker matching into an ordered table.
- Give the kind operator remediation stating that storage-confirmed work is intact.

## Outcome

Contention no longer falls through to the unclassified bucket. That fallthrough was the whole cost of the original defect: a transient lock read as a terminal fault, and a generation holding storage-confirmed work was discarded rather than retried.

The table restructure was not cosmetic. Adding a condition to the branch chain pushed the classifier past its return-count limit, and the ordered table makes first-match-wins precedence explicit instead of implied by statement order.

## Notes

Marker order matters and is now explicit: the contention markers sit ahead of the timeout markers so a message carrying both classifies as the transient condition rather than as a store timeout.
