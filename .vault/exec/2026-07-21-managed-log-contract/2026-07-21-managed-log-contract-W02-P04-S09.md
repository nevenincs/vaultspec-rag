---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:4ada001ff51281817fe02aadb0c8f12bcb486039735aa25cdbc90c15fc788760'
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
