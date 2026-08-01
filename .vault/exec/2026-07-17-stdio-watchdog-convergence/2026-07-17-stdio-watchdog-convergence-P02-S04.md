---
tags:
  - '#exec'
  - '#stdio-watchdog-convergence'
date: '2026-07-17'
modified: '2026-07-17'
body_hash: 'sha256:6e161b3cd3f675bfb09825e106daf001412302a32523ad970b667b2253b33cd3'
step_id: 'S04'
related:
  - "[[2026-07-17-stdio-watchdog-convergence-plan]]"
---

# Raise the e2e suite to the floor: stdlib wire harness, handshake plus five-tool surface before EOF, intermediary-client kill with instant reap, degraded-mode search_vault guidance through the wire

## Scope

- `src/vaultspec_rag/tests/integration/test_stdio_lifetime_e2e.py`

## Description

- Rewrite the e2e suite to the functional floor with a stdlib
  line-delimited JSON-RPC harness: EOF test performs the initialize
  handshake (asserting server identity) and the exact five-tool surface
  before closing stdin; a degraded `search_vault` call proves the
  service-down guidance through the wire under full machine isolation
  (status dir AND qdrant storage dir - discovery is machine-singleton
  authoritative); the client-kill test has an intermediary client prove
  served capability then die, with the shim reaped in seconds (precise
  anchor, no grace).

## Outcome

3 e2e tests pass in ~4s; the synthetic watchdog-only worker is gone.

## Notes

None.
