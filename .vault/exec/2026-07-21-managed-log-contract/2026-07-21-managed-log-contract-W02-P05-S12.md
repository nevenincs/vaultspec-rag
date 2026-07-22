---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S12'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Replace the legacy activity parser and raw compatibility flag with grouped source rendering and offline fallback

## Scope

- `src/vaultspec_rag/cli/_service_logs.py`

## Description

- Replace service activity parsing with explicit service, Qdrant, or all-source rendering.
- Use grouped raw plaintext by default and expose the shared JSON shape.
- Fall back to the production local reader only when the service is unavailable.
- Remove the raw compatibility flag and service-only command identity.

## Outcome

One `server logs` command works truthfully while the daemon is live and after it stops.

## Notes

Live structured errors remain errors and do not trigger misleading local success.
