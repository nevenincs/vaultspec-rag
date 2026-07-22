---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S10'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Carry the source selector and structured log outcome through the admin transport

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Carry the source selector through the import-light admin transport.
- Preserve structured server errors instead of converting failures into empty success.

## Outcome

Live CLI callers receive the selected grouped payload and truthful transport outcomes.

## Notes

No log method was added to the public MCP surface.
