---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:202bd476cefc1a055bb8a9e7eeef98f7b4df4ee86b33871c1f195cd342ae2f2f'
step_id: 'S11'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Verify authenticated live responses, bounds, filters, and source-group schema

## Scope

- `src/vaultspec_rag/tests/integration/test_service_logs.py`

## Description

- Exercise authenticated ASGI and live Uvicorn requests for plaintext and JSON logs.
- Assert source groups, filters, bounds, malformed-source errors, and transport error preservation.

## Outcome

Integration coverage proves live server and transport parity for the managed-log contract.

## Notes

Tests use real routes, files, sockets, and transport calls.
