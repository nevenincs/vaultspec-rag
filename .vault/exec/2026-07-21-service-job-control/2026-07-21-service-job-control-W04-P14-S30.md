---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S30'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Implement show, pause, resume, stop, retry, and delete commands with unique-prefix resolution before exact mutation using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/cli/_service_jobs.py`

## Description

- Implement singular show, pause, resume, stop, retry, and delete commands.
- Resolve human job prefixes through the bounded collection before exact
  detail and mutation calls.
- Require JSON callers to address the exact detail resource directly.
- Carry positive revisions into desired-state mutations and forward force mode
  truthfully.
- Converge success, rejection, ambiguity, invalid-resource, and unavailable
  paths on one structured JSON envelope.

## Outcome

The CLI now exposes all six canonical resource controls. Human invocations may
use one unambiguous prefix, while every HTTP mutation receives a full exact
identifier. JSON invocations never resolve prefixes, already-satisfied outcomes
remain successful, and malformed revisions fail before mutation. Ruff, Ruff
format, and BasedPyright pass. Independent re-review passed with no remaining
critical, high, or medium findings.

## Notes

Review identified one medium race-safety issue: malformed revisions disabled
optimistic concurrency. The adapter now rejects those resources instead. A
direct dead-port invocation confirmed one JSON envelope and exit code 3. S31
owns real-server CLI lifecycle coverage.
