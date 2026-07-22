---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S09'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Serve source-aware plain and JSON log responses from the shared reader

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Accept the source selector on authenticated plaintext and JSON routes.
- Return grouped output from the shared service-domain helpers.
- Return a structured 400 response for invalid sources.

## Outcome

The live server exposes the same bounded grouped contract used by local inspection.

## Notes

Authentication remains required for both representations.
