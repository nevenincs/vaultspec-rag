---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
step_id: 'S05'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Export the service-client public surface from the package init

## Scope

- `src/vaultspec_rag/serviceclient/__init__.py`

## Description

- Export the public service-client surface from the package init via explicit imports plus an `__all__`: the three search/reindex/admin client functions, the wire-call primitive, the three new benchmark/quality/code-file wrappers, the connection-refused predicate, the timeout-diagnostics builder, the search-timeout constant, and the discovery helpers.
- Pull the transport names from the transport module and the discovery names from the discovery module, keeping the package init free of any heavy import.

## Outcome

- Both the CLI and the MCP can import one shared surface from the service-client package.
- Importing the assembled package pulls none of the heavy modules, verified directly: the import-isolation probe reports a clean `sys.modules` with no Torch, sentence-transformers, qdrant-client, transformers, onnxruntime, or the heavy first-party facade modules.

## Notes

None.
