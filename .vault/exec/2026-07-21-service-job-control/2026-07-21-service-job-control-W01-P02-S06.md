---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S06'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Implement revisioned pause, resume, cancellation, retry, terminal deletion, first-terminal-writer-wins, and deterministic races using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Apply optimistic revisions only when desired state changes; treat same-target retries as successful replays.
- Transition queued and live work through truthful pause, resume, and graceful cancellation states.
- Distinguish a retractable pause from a delivered unwind and requeue reconciliation without exposing a false paused state.
- Bind attempt start, control acknowledgement, and terminal completion to the exact task and attempt number.
- Preserve the first terminal writer, create linked retries for retryable outcomes, and restrict deletion to terminal history.
- Reject force termination explicitly while the thread runtime cannot provide it.

## Outcome

The manager now provides the complete revisioned lifecycle state machine. Pause and
cancellation acknowledge only through the unwind boundary, stale attempt callbacks cannot
rewrite newer work, and retries and deletion preserve immutable terminal history.

## Notes

Ruff, formatting, `ty`, and strict BasedPyright passed. All 49 focused unit tests passed,
and a real asyncio probe exercised immediate pause, pre-delivery resume, post-delivery
resume, cancellation acknowledgement, first-terminal-writer-wins, retry, and deletion.
