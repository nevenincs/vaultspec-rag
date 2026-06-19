---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S10'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Rewrite the MCP vault-document resource to delegate to the service-client

## Scope

- `src/vaultspec_rag/mcp/_resources.py`

## Description

- Rewrote the `vault://{doc_id}` resource to delegate to the daemon's vault-document route
  through a new shared service-client vault-document wrapper, sharing the port resolution,
  worker-thread offload, and one service-down error with the search and admin tools.
- Added the vault-document wrapper and its route mapping to the shared client transport,
  mirroring the existing code-file wrapper, so the resource stays a pure delegate rather
  than carrying its own wire logic; exported the wrapper from the service-client package.
- Preserved the resource's not-found-to-`FileNotFoundError` and structured-error-to-
  `RuntimeError` unwrapping; left the pure-string `analyze_feature` prompt template
  untouched.

## Outcome

The vault-document resource is a thin delegation with no daemon-call seam of its own; with
an empty status directory it raises the single clear service-not-running error. The server
suite's vault-document not-running assertion passes against the realigned error phrasing.

## Notes

The daemon's vault-document route had no shared-client wrapper before this change, so one
was added to the shared transport mirroring the existing code-file wrapper; the resource
delegates through it rather than re-implementing the wire call, honoring the one-shared-
client-surface contract.
