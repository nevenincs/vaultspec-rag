---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S12'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Make CLI dry-run apply the same preprocessing mode and return the structured admission summary

## Scope

- `src/vaultspec_rag/cli/_index.py`

## Description

- Apply the requested preprocessing execution mode before policy resolution.
- Render the production scan's stable counts, samples, paths, and fingerprint.
- Keep human samples bounded while retaining complete structured JSON paths.

## Outcome

CLI dry-run now reports the same admission decision as execution under the selected
preprocessing mode and does not reproduce classifier rules.

## Notes

Reconciled from production commit `e1254ed`; no additional code change was required.
