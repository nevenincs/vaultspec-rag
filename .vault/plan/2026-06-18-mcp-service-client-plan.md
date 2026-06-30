---
tags:
  - '#plan'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-30'
tier: L2
related:
  - '[[2026-06-18-mcp-service-client-adr]]'
  - '[[2026-06-18-mcp-service-client-research]]'
---

# `mcp-service-client` plan

### Phase `P01` - factor an import-light shared service-client layer

Extract the production-proven HTTP service-client into an import-light package so both the CLI and the MCP consume one surface without loading Torch, models, or the store.

- [x] `P01.S01` - Convert the top-level package init to lazy attribute loading so importing any submodule no longer eager-loads the heavy facade; `src/vaultspec_rag/__init__.py`.
- [x] `P01.S02` - Create the import-light service-client transport housing the HTTP call primitive and the search, reindex, and admin client functions; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `P01.S03` - Create the import-light service-discovery module housing the status-file reader and default-port resolver; `src/vaultspec_rag/serviceclient/_discovery.py`.
- [x] `P01.S04` - Add thin client wrappers for benchmark, quality, and code-file so the MCP inherits them without bespoke logic; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `P01.S05` - Export the service-client public surface from the package init; `src/vaultspec_rag/serviceclient/__init__.py`.
- [x] `P01.S06` - Repoint the CLI HTTP search module to re-export from the service-client package, preserving the CLI surface; `src/vaultspec_rag/cli/_http_search.py`.
- [x] `P01.S07` - Repoint the CLI service-status discovery helpers to re-export from the service-client package; `src/vaultspec_rag/cli/_service_status.py`.

### Phase `P02` - rewrite the MCP tools as thin client delegations

Repoint every MCP tool, admin tool, and resource at the shared service-client, delete the duplicate daemon-call seam, and surface one clear service-down error.

- [x] `P02.S08` - Rewrite the MCP search and index tools to delegate to the service-client, delete the duplicate daemon-call seam, route index-status to the service-state route, and map the unreachable return to one clear service-not-running error; `src/vaultspec_rag/mcp/_tools.py`.
- [x] `P02.S09` - Rewrite the MCP admin and observability tools to delegate to the service-client admin function; `src/vaultspec_rag/mcp/_admin_tools.py`.
- [x] `P02.S10` - Rewrite the MCP vault-document resource to delegate to the service-client; `src/vaultspec_rag/mcp/_resources.py`.

### Phase `P03` - remove the daemon mount and in-process model load

Make stdio the sole MCP transport by removing the daemon's in-process MCP mount, its redirect wrapper, and the stdio branch's GPU model load.

- [x] `P03.S11` - Remove the in-process MCP mount and the redirect ASGI wrapper from the server entry point; `src/vaultspec_rag/server/_main.py`.
- [x] `P03.S12` - Remove the in-process GPU model load from the stdio branch and make stdio the sole MCP transport in the entry point; `src/vaultspec_rag/server/_main.py`.

### Phase `P04` - remove dead and phantom MCP artifacts

Delete references to commands and modules that do not exist and correct stale documentation so the shipped surface matches its description.

- [x] `P04.S13` - Correct the stale server-owns-mcp docstring in the server package init; `src/vaultspec_rag/server/__init__.py`.
- [x] `P04.S14` - Correct the stale server-owns-mcp docstring in the server state module; `src/vaultspec_rag/server/_state.py`.
- [x] `P04.S15` - Remove the phantom mcp-start and mcp-admin exemption from the conflation guard test; `src/vaultspec_rag/tests/test_no_mcp_server_conflation.py`.
- [x] `P04.S16` - Align the ecosystem test's documented MCP command surface with the commands that actually ship; `src/vaultspec_rag/tests/integration/test_ecosystem_integration.py`.

### Phase `P05` - lock the thin-client invariants with mock-free tests

Add fresh-interpreter import-isolation and no-local-fallback regression tests and broaden the static isolation guard to catch the transitive heavy pull.

- [x] `P05.S17` - Add the fresh-interpreter subprocess runtime check and broaden the static forbidden-import set to include cli and api; `src/vaultspec_rag/tests/test_mcp_import_isolation.py`.
- [x] `P05.S18` - Add the no-local-fallback test asserting each tool raises a clear service-not-running error against an isolated empty status dir; `src/vaultspec_rag/tests/test_mcp_no_local_fallback.py`.
- [x] `P05.S19` - Update the server tests that bind the removed HTTP mount and in-process model-load expectations; `src/vaultspec_rag/tests/test_server.py`.

### Phase `P06` - verify and review

Run the full unit and GPU integration suite locally and conduct a formal code review before the work is considered done.

- [x] `P06.S20` - Run the full unit and GPU integration suite locally and confirm green; `src/vaultspec_rag/tests`.
- [x] `P06.S21` - Conduct a formal vaultspec code review and record the audit; `.vault/audit`.

## Description

This plan executes the accepted ADR that reframes the MCP server as a thin service
client, grounded in the feature's research. The service backend is the only
production-ready path; the MCP must become a thin stdio client that reuses the CLI's
proven HTTP service-client, loads no Torch or models, holds no lock or local resource,
and fails with a clear service-not-running error when the daemon is down. The work is
mostly collapse-and-delete: the production client already exists in the CLI and is
extracted into an import-light `serviceclient` package that both the CLI and the MCP
consume.

Phase `P01` factors that shared layer and makes the top-level package init lazy so
importing the MCP no longer drags in the heavy facade through
`vaultspec_rag/__init__.py`. Phase `P02` rewrites the MCP tools, admin tools, and
resource to delegate to it and deletes the duplicate daemon-call seam. Phase `P03` makes
stdio the sole transport by removing the daemon's in-process MCP mount and its redirect
wrapper and the stdio branch's model load. Phase `P04` removes dead and phantom
artifacts so the shipped surface matches its description. Phase `P05` locks the
invariants with mock-free import-isolation and no-local-fallback tests. Phase `P06`
verifies and reviews. Backward compatibility is explicitly not a goal: the cut is clean,
with no shims, shadows, or dual-mode fallbacks.

## Parallelization

`P01` is the foundation and must land first: every later phase imports the
`serviceclient` package it creates, and the lazy package-init change (`P01.S01`) is the
prerequisite for the import-isolation guarantee. Within `P01`, the transport
(`P01.S02`, `P01.S04`) and discovery (`P01.S03`) modules can be written in parallel,
then the export (`P01.S05`) and the CLI re-export steps (`P01.S06`, `P01.S07`) follow
once they exist.

`P02`, `P03`, and `P04` touch disjoint files and may proceed in parallel once `P01`
lands, with one ordering caveat: `P03.S11` and `P03.S12` edit the same entry point and
run sequentially. `P05` depends on `P02` and `P03` being in place, because its tests
assert the new delegation and no-model-load behavior. `P06` runs last, after every
implementation and test step is closed.

## Verification

The plan is complete when every Step is closed. Mission success criteria, each a
verifiable check:

- A fresh-interpreter import of the MCP package loads none of `torch`,
  `sentence_transformers`, `qdrant_client`, `transformers`, or `onnxruntime` (`P05.S17`).
- Every MCP tool raises a clear service-not-running error against an empty status dir,
  with no local machinery spun up afterward (`P05.S18`).
- The daemon no longer mounts the MCP app and the stdio entry point loads no model;
  stdio is the sole transport (`P03`).
- No MCP tool, test, or docstring references a route, command, or module that does not
  ship, and `get_index_status` resolves against the live service-state route (`P02`,
  `P04`).
- The full unit and GPU integration suite passes locally with zero mocks, fakes, or
  skips (`P06.S20`).
- The vaultspec code review signs off with the audit recorded (`P06.S21`).
