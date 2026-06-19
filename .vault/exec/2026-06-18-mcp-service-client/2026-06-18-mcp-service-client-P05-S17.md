---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S17'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Add the fresh-interpreter subprocess runtime check and broaden the static forbidden-import set to include cli and api

## Scope

- `src/vaultspec_rag/tests/test_mcp_import_isolation.py`

## Description

- Add a fresh-interpreter subprocess test that imports the MCP package and asserts `sys.modules` contains none of `torch`, `sentence_transformers`, `qdrant_client`, `transformers`, or `onnxruntime`, copying the subprocess technique from the chunk-worker no-torch parity test. A fresh interpreter is essential so a torch-loading test elsewhere in the session cannot leave the heavy libraries resident and mask a regression.
- Broaden the static AST guard's forbidden submodule set to additionally forbid `cli` and `api`, since importing either transitively drags the GPU facade — the vector store, search, embeddings, and indexer — into the process; the thin client must reach the service only through the import-light service-client layer.
- Introduce a shared heavy-library tuple reused by the runtime check, and refresh the module docstring to describe both the static AST guard and the new runtime guard.

## Outcome

The new runtime test and the five existing AST-guard cases pass together. The broadened forbidden set holds because the MCP package no longer imports `cli` or `api` after the earlier phases, so the static guard now catches the transitive heavy pull as well as the direct server-internal imports it already covered.

## Notes

No incidents. The runtime guard runs in roughly a second; no skips, mocks, or fakes were introduced.
