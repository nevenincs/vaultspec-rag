---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:87634815e3291205cfe13f373645fe0eaf050c2bfd1968e8a247fbd6681ed9f4'
step_id: 'S11'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Export typed discovery without widening the torch-free service-client import surface

## Scope

- `src/vaultspec_rag/serviceclient/__init__.py`

## Description

- Re-export the resolution record, the state vocabulary, the reason vocabulary, the
  source vocabulary, and the resolver from the service-client package surface.

## Outcome

Operator and transport adapters can consume typed discovery from the shared client
package without reaching into the private discovery module.

## Notes

The export was verified to keep the client surface import-light: a fresh interpreter that
imports the package and calls the resolver loads neither torch, nor sentence-transformers,
nor the store, nor the MCP server. That property is what allows the MCP stdio shell and
the CLI fast path to share this surface, so it was checked rather than assumed.
