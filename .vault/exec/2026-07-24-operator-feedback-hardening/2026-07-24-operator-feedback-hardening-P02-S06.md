---
tags:
  - '#exec'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:f5a2cbc516e61758b50faa811db73d4b0097859a9dc558dae95ea250316e8a57'
step_id: 'S06'
related:
  - "[[2026-07-24-operator-feedback-hardening-plan]]"
---

# Log the startup refusal cause before the daemon process exit

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Log the startup failure cause before the daemon's process-level exit.
- Emit the traceback first and the one-line cause last, and record an expected contention yield at a lower severity than a fault.

## Outcome

A daemon that refuses to start says why. A second service reports the winning process and the remedy instead of exiting non-zero in silence.

## Notes

The exit is a process-level exit, so the re-raise ending the handler was unreachable and the exception text was discarded entirely. The ordering is deliberate: the failure surface shows only the final lines of that log, so the actionable sentence has to be written last while the frames stay above it. The handler had never logged; this is additive, and no attempt was made to bisect when the covering test last passed.
