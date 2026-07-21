---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-21'
step_id: 'S10'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Mention --json in the human jobs summary line and command help so scripted consumers are routed to the structured envelope instead of grepping the word active

## Scope

- `src/vaultspec_rag/cli/_service_jobs.py`

## Description

- Append a Scripting line to the human jobs feed summary pointing at --json (the summary unconditionally contains the words active/waiting).
- Expand the --json option help to say scripted waits must use it.

## Outcome

Committed as 0616f5f. jobs --json envelope untouched.

## Notes

None.
