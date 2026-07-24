---
tags:
  - '#exec'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S07'
related:
  - "[[2026-07-24-operator-feedback-hardening-plan]]"
---

# Render every degradation with its cause and a remedying command

## Scope

- `src/vaultspec_rag/cli/_status_labels.py`

## Description

- Build one renderer that turns a degradation report into causes and remedying commands.
- Key remediation on structured signals rather than on the wording of the reason, and surface an unclaimed reason verbatim.
- Point the start path and the project status view at that one renderer.

## Outcome

A degraded service names the failing job, its error kind, its age, and the command that inspects it. A service that is not degraded but carries a historical failure reports that separately rather than silently.

## Notes

Guard proof recorded: dropping the unclaimed-reason branch fails on the verbatim assertion while the rest of the test still passes, isolating the failure to the property under test. Verified byte-identical against the start path's previous output across seven payload shapes; the one difference was in the shared renderer's favour, since the old code rendered a structured record as a container repr.
