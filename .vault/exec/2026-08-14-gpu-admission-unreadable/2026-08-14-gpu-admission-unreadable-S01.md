---
tags:
  - '#exec'
  - '#gpu-admission-unreadable'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:8c0bcbe4784e31a0b92133a320624179f7a01d0df16b92852588e3d6af7a0e64'
step_id: 'S01'
related:
  - "[[2026-08-14-gpu-admission-unreadable-plan]]"
---

# Give the gate a consecutive-unreadable ledger and refuse past its limit under a distinct reason

## Scope

- `src/vaultspec_rag/_gpu_admission.py`

## Description

- Add a consecutive-unreadable ledger to the gate: one counter, cleared by
  any reading that yields a free figure, extended by a reading that finds
  the device present and the figure absent, and left alone by a reading
  that never reached the question.
- Take the streak as an argument to the verdict rather than counting it
  there, so the judgement stays a pure function of its inputs.
- Refuse at or past the limit under a new reason token, and add that token
  to the set the load gate raises on.
- Give the refusal its own operator prose naming the device fault and the
  driver, and make the single renderer dispatch on the reason it is given
  rather than growing a second renderer.

## Outcome

A device that answers presence and refuses every memory query is admitted
twice and refused on the third reading. The refusal carries a reason
distinct from an absent device, and a message that names neither a
competing tenant nor the admission floor, because neither is the fault.

The limit is a count rather than an elapsed span deliberately: the
incident produced a slow trickle of observations, which a time window
could have re-armed indefinitely from an idle period between them.

## Notes

The threshold constant is public and exported rather than private. The
rendered operator message embeds it, so it is part of what this module
publishes rather than an internal detail, and the boundary guard can then
assert against the shipped figure instead of restating it.
