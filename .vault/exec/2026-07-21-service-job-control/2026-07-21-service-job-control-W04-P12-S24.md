---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S24'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Add create, exact detail, desired-state update, retry, and terminal deletion routes and retain reindex as a validated compatibility adapter using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Validate canonical index specifications, absolute project roots, initiator
  metadata, control requests, revisions, and idempotency keys.
- Serve exact job detail and structured create, desired-state, retry, and
  terminal-deletion outcomes with stable status codes and `Location` headers.
- Merge canonical manager resources with legacy-only service activity in the
  bounded collection view.
- Bind and dispatch newly created and retried jobs through the production index
  runner while leaving replayed and start-paused work inert.
- Retain `/reindex` as a validated adapter over canonical job admission.
- Add real Starlette route coverage for authentication, filtering, replay,
  force rejection, cancellation, retry linkage, deletion, and compatibility
  validation.

## Outcome

The authenticated Hypertext Transfer Protocol (HTTP) service now owns the full
canonical indexing-job resource lifecycle. Exact mutation paths never accept
prefixes. Manager outcomes remain structured and idempotent, and create and
retry responses expose the canonical resource location.

New jobs bind to the real production dispatcher. Start-paused resources retain
their durable intent without starting work, while replays and active-work
deduplication avoid duplicate dispatch. Terminal deletion never doubles as
cancellation.

The focused route run passes 15 of 15 tests. PyCompile, Ruff, Ruff format, and
Ty pass for the changed production files.

Independent review found two high-severity issues and one medium-severity
issue. The implementation now returns post-dispatch revisions, validates code
policy before admission, and rejects malformed reindex type values. Focused
correction coverage and the final Ruff and Ty checks pass.

## Notes

No fake, mock, stub, patch, monkeypatch, skipped test, or expected-failure path
was introduced. Existing shared search-availability changes in
`src/vaultspec_rag/server/_routes.py` remained intact. No destructive Git
operation ran, and no data was lost.
