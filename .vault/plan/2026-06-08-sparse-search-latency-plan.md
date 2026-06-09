---
tags:
  - '#plan'
  - '#sparse-search-latency'
date: '2026-06-08'
tier: L2
related:
  - '[[2026-06-07-sparse-search-latency-adr]]'
  - '[[2026-06-07-sparse-search-latency-research]]'
---

<!-- RETIRED: S09 -->

# `sparse-search-latency` `Scaling Bottlenecks` plan

## Description

This plan implements latency optimizations for the VaultSpec RAG service to address issue #165. Based on the findings in `[[2026-06-07-sparse-search-latency-research]]` and authorized by `[[2026-06-07-sparse-search-latency-adr]]`, we are introducing a fast-path dense-only fallback by adding a `sparse_enabled` toggle. Additionally, we are pushing the python `fnmatch` filtering down into Qdrant using native `MatchPattern` regex filters to heavily narrow the candidate space prior to costly RRF evaluation during sparse codebase searches.

## Steps

### Phase `P01` - Dense-Only Fallback

Introduce sparse_enabled toggle in configuration to bypass SPLADE and accelerate dense-only queries.

- [x] `P01.S01` - Add sparse_enabled to \_RAG_DEFAULTS; `src/vaultspec_rag/config.py`.
- [x] `P01.S02` - Skip SPLADE computation and index fetching when sparse_enabled is False; `src/vaultspec_rag/search/_searcher.py`.
- [x] `P01.S03` - Update tests to assert dense-only fallback works; `src/vaultspec_rag/tests/`.

### Phase `P02` - Glob Pre-Filtering via Qdrant MatchPattern

Map glob filters to Qdrant native filters before search to skip post-query Python filtering.

- [x] `P02.S04` - Translate include_paths and exclude_paths globs to Regex strings; `src/vaultspec_rag/search/_searcher.py`.
- [x] `P02.S05` - Update VaultStore.hybrid_search_codebase to accept regex filters and construct MatchPattern; `src/vaultspec_rag/store.py`.
- [x] `P02.S06` - Remove post-query \_filter_raw_codebase_results logic; `src/vaultspec_rag/search/_searcher.py`.
- [x] `P02.S07` - Update tests to assert Qdrant glob filtering works correctly; `src/vaultspec_rag/tests/`.

### Phase `P03` - Comprehensive Code Review

Run extensive code reviews to identify and mitigate any hidden exceptions, edge cases, or performance cliffs introduced during the latency optimizations.

- [x] `P03.S08` - Run Vaultspec Code Reviewer subagent for full scope audit; `src/vaultspec_rag/`.
- [x] `P03.S10` - Resolve MCP Deconflation Gap (CRITICAL); `src/vaultspec_rag/mcp/`.
- [x] `P03.S11` - Resolve Execution Paths & Latency Bottlenecks (HIGH); `src/vaultspec_rag/store.py`.
- [x] `P03.S12` - Resolve Sparse Fallback Boundaries Leak (HIGH); `src/vaultspec_rag/indexer/_streaming.py`.

### Phase `P04` - Test Suite Harmonization

Fix all 43 failing tests caused by the CLI refactor drift and the new MCP REST boundary requirements without using mocks.

- [x] `P04.S13` - Fix CLI test drift and MCP tool REST boundary tests; `src/vaultspec_rag/tests/`.
- [x] `P04.S14` - Fix MCP Starlette mount missing `streamable_http_app` and Typer CLI handler regression; `src/vaultspec_rag/server/_main.py`.

### Phase `P05` - MCP Business Logic Elimination

The `mcp/` package must be a pure protocol adapter: translate MCP stdio/HTTP requests into REST calls to the daemon. No direct imports from `server`, `store`, `service`, or `registry`.

- [x] `P05.S15` - Remove `_resources.py` direct Qdrant access: replace `_m._registry.lease(root)` + `slot.store.get_by_id()` with a REST call to a new `/vault-document` daemon endpoint; `src/vaultspec_rag/mcp/_resources.py`, `src/vaultspec_rag/server/_routes.py`.
- [x] `P05.S16` - Remove `_resources.py` server internal imports: eliminate `import vaultspec_rag.server as _m`, `from ..server._utils import _default_root`, and `_m._http_mode` reads; `src/vaultspec_rag/mcp/_resources.py`.
- [x] `P05.S17` - Add `/vault-document` REST route to daemon serving document content by stem ID; `src/vaultspec_rag/server/_routes.py`.
- [x] `P05.S18` - Integration tests asserting `mcp/` has zero imports from `server/`, `store`, `service`, or `registry`; `src/vaultspec_rag/tests/`.

### Phase `P06` - Semantic Deconflation of MCP/Service Naming

Purge all semantic conflation where "MCP server" is used to mean "REST daemon" or where function/variable/docstring names use `mcp` when they mean `service` or `daemon`. The CLI in-process fallback path is acceptable per existing ADRs and stays.

- [x] `P06.S19` - Rename `server/__init__.py` docstring from "MCP server" to "RAG daemon HTTP service"; rename `_main.py` docstring from "Console-script entry point for the MCP server" to "Console-script entry point for the RAG daemon"; `src/vaultspec_rag/server/__init__.py, src/vaultspec_rag/server/_main.py, src/vaultspec_rag/server/_models.py, src/vaultspec_rag/server/_state.py`.
- [x] `P06.S20` - Rename CLI identifiers: `_handle_mcp_results` → `_handle_service_results`, `mcp_results` → `service_results`, `_display_mcp_error` → `_display_service_error`, `_try_mcp_delegation` → `_try_service_delegation`, `_print_mcp_results` → `_print_service_results`; `src/vaultspec_rag/cli/_search.py`, `src/vaultspec_rag/cli/_index.py`, `src/vaultspec_rag/cli/_render.py`, `src/vaultspec_rag/cli/__init__.py`.
- [x] `P06.S21` - Fix CLI user-facing strings: replace "Port of running MCP server" with "Port of running RAG service", replace `"via": "mcp"` with `"via": "service"`, fix all `--help` text and error messages that say "MCP server" when they mean the daemon; `src/vaultspec_rag/cli/_search.py`, `src/vaultspec_rag/cli/_index.py`, `src/vaultspec_rag/cli/_store.py`, `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P06.S22` - Fix stale docstring references: update `registry.py` and `service.py` docstrings that reference the deleted `mcp_server.py` module name; `src/vaultspec_rag/registry.py`, `src/vaultspec_rag/service.py`.
- [x] `P06.S23` - Integration test asserting no `.py` file in `cli/` or `server/` contains the string "MCP server" in docstrings, help text, or user-facing output (the `mcp/` package itself is exempt); `src/vaultspec_rag/tests/`.

### Phase `P07` - Pre-Merge Code Review

Formal vaultspec-code-reviewer pass on the P05/P06 deconflation diff before merge to main.

- [ ] `P07.S24` - Run vaultspec-code-reviewer on the deconflation diff (commit 671dcd3); `src/vaultspec_rag/`.

### Phase `P08` - Empirical Service Validation

Empirically validate the live RAG service end-to-end: lifecycle, index, search/filter, reindex/incremental, concurrency, eviction, local fallback, and degraded recovery.

- [ ] `P08.S25` - Capture baseline service, index, GPU, project-slot, and watcher state; `src/vaultspec_rag/service.py`.
- [ ] `P08.S26` - Validate service lifecycle: start detached, status, warmup, stop; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [ ] `P08.S27` - Validate indexing of vault docs and codebase via CLI and daemon REST; `src/vaultspec_rag/indexer/`.
- [ ] `P08.S28` - Validate search and all filters for vault and codebase via delegation and REST; `src/vaultspec_rag/search/`.
- [ ] `P08.S29` - Validate reindex and incremental watcher-driven update of changed sources; `src/vaultspec_rag/watcher.py`.
- [ ] `P08.S30` - Validate concurrent multi-client requests against the running daemon; `src/vaultspec_rag/registry.py`.
- [ ] `P08.S31` - Validate service vacate: project-slot eviction and clean stop releasing the Qdrant lock; `src/vaultspec_rag/cli/_service_projects.py`.
- [ ] `P08.S32` - Validate local in-process fallback when the server is down or degraded; `src/vaultspec_rag/cli/_http_search.py`.
- [ ] `P08.S33` - Validate degraded-server detection exit-4 and recovery on restart; `src/vaultspec_rag/cli/_service_status.py`.

## Parallelization

- Phases `P01` and `P02` modify different orthogonal paths within the search implementation. They can be implemented sequentially or in parallel without conflict.
- Phases `P05` and `P06` are sequential: P05 (MCP deconflation) must land first so the MCP package stops importing server internals, then P06 (naming) is a safe cosmetic sweep.

## Verification

- Running codebase search with `--no-sparse` (or `sparse_enabled=False`) skips the SPLADE encoding and executes in ~0.5s instead of ~20s.
- `include_paths` and `exclude_paths` glob parameters continue to correctly filter results, but the filtering executes natively inside Qdrant.
- Integration tests and search unit tests fully pass.
- `mcp/` imports nothing from `server/`, `store`, `service`, or `registry`.
- No `.py` file outside `mcp/` uses "MCP server" in docstrings or user-facing strings.
