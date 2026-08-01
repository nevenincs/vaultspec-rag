---
tags:
  - '#exec'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:1a762e1a9c4636f770b83cc86adad438a6402851d3566730e3b70995efff2ab8'
step_id: 'S02'
related:
  - "[[2026-07-24-operator-feedback-hardening-plan]]"
---

# Add a startup status reporter whose output is stream-placed by mode

## Scope

- `src/vaultspec_rag/cli/_progress.py`

## Description

- Add a startup status reporter exposing an unconditional announce, a deduped stage, and a rate-limited heartbeat.
- Drive the live region through the shared console so the frame can be erased and repainted around lines printed by other code.
- Place static lines on the diagnostic stream off a terminal, and emit nothing at all in machine-output mode.

## Outcome

Progress renders on a terminal, degrades to plain rate-limited lines when piped, and leaves the machine-output channel byte-empty.

## Notes

An earlier iteration gave the live region its own console on the same stream. Reproduced output showed a warning welded onto the spinner frame with no newline, because a live region positions itself from what it alone rendered; it was reverted to one console. Guard proofs recorded: a non-interactive region fails on the missing label with the whole stream reduced to cursor codes; a second console fails on a print landing inside a frame; a console bound at construction rather than call time fails because a test-swapped console receives nothing.
