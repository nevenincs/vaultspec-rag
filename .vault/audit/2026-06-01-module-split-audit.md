---
tags:
  - '#audit'
  - '#module-split'
date: '2026-06-01'
modified: '2026-06-30'
related: []
---

# `module-split` audit: python module reaudit + monolith-to-package split blueprint

## Scope

Complete reaudit of every non-test Python module under `src/vaultspec_rag/`
(per the user mandate to break monolithic files into manageable chunks). The
audit sizes each module, judges cohesion, and — for oversized modules — designs
a split from a single `module.py` into a package `module/` whose `__init__.py`
re-exports the exact public surface so no import (production or test) breaks.

## Findings

### Size inventory (non-test source)

Oversized (split candidates), largest first:

- `cli.py` — 4286 lines. The flagged monolith.
- `indexer.py` — 2099 lines.
- `mcp_server.py` — 1641 lines.
- `torch_config.py` — 1263 lines.
- `store.py` — 984 lines.
- `search.py` — 952 lines.
- `commands.py` — 943 lines.

Below threshold (leave as single files): `service.py` (669), `embeddings.py`
(447), `synthetic.py` (316), `logging_config.py` (301), `memory_probe.py`
(295), `config.py` (274), `api.py` (255), `watcher.py` (239), `progress.py`
(183), and the small modules (`graph_cache.py`, `registry.py`,
`capabilities.py`, `workspace.py`, `__main__.py`).

### Per-module verdicts

- **`cli.py` — SPLIT.** No circular dependencies; the risk is breadth, not
  cycles. ~20 cohesive sections (Typer app/state, render helpers, GPU-error
  messages, store open, MCP-admin + MCP-search client seams, index/clean,
  search, status, mcp lifecycle, service status-file I/O, process helpers,
  service lifecycle, projects, watcher, benchmark, quality, test, install).
  **24 symbols are imported externally** (`app` plus 23 `_`-prefixed helpers
  used by tests — e.g. `_spawn_service`, `_terminate_pid`, `_is_pid_alive`,
  `_read_service_status`, `_write_service_status`, `_status_file`,
  `_health_probe`, `_service_child_env`, `_try_mcp_search`,
  `_display_search_results`, `_add_backend_contract_rows`, `_display_mcp_error`,
  `_is_our_service`, `_port_is_listening`, `_heartbeat_age_seconds`,
  `_suppress_hf_progress`, `_cpu_only_message`, `_no_gpu_message`,
  `_no_torch_message`). Invariant: the Typer app + sub-apps must be created and
  nested before any command decorator runs, so the app module imports first and
  command modules import after.

- **`mcp_server.py` — SPLIT (highest risk).** A module-level `mcp = FastMCP(...)`
  drives every `@mcp.tool()` / `@mcp.resource()` / `@mcp.prompt()`; all tool
  submodules must decorate against the same instance, so the package init owns
  the shared globals (`mcp`, `_registry`, `_watcher_tasks`, `_watcher_stops`,
  `_watcher_lock`, `_SERVICE_TOKEN`, `_http_mode`, `_start_time`) and imports
  the tool submodules to trigger registration. The console-script entry point
  `vaultspec_rag.mcp_server:main` must stay importable (keep `main` re-exported
  from the package root). ~30 symbols imported externally (mostly by
  `test_mcp_server.py` / `test_adr_regression.py`): the tools, the Pydantic
  models (`SearchResponse`, `IndexStatus`, `IndexResponse`, `HealthResponse`,
  `SearchResultItem`, `BackendCapabilities`), `mcp`, `_registry`,
  `_watcher_tasks`, `_watcher_stops`, `_ensure_watcher`, `_stop_watcher`,
  `_stop_all_watchers`, `_http_mode`, `_resolve_root`, `_default_root`,
  `_validate_vault_root`, `_is_sensitive_path`, `_clamp_top_k`,
  `health_handler`, `_lifecycle_log`, `_registry_full_error_dict`,
  `_local_store_locked_error_dict`. Circular-import hazard: tool submodules
  import `mcp` from the package, and the package imports the submodules — order
  the package init so globals are defined before submodule import.

- **`indexer.py` — SPLIT (low risk).** Clean public surface: `VaultIndexer`,
  `CodebaseIndexer`, `IndexResult`, `prepare_document` (+ optional
  `ASTChunker`, `TextSplitter`, `LANGUAGE_MAP`, `SUPPORTED_EXTENSIONS`). Shared
  AST/language constants must sit in one submodule both the chunker and the
  codebase indexer import. No module-level mutable state.

- **`torch_config.py` — SPLIT.** Pure functions + dataclasses, zero module
  state, no cycles. Natural seams: constants/models, TOML inspection,
  classification, mutation, direct-dep management, diagnosis. Public surface:
  `TorchConfigAction`, `detect_state`, `preview_patch`, `apply_patch`,
  `remove_patch`, `diagnose_torch`, `manual_snippet`, `ensure_direct_torch_dep`,
  `remove_managed_direct_torch_dep`, `has_direct_torch_dep`,
  `DIRECT_TORCH_REQUIREMENT` (+ tests import the module as a whole and several
  `_`-helpers).

- **`search.py` — SPLIT.** `VaultSearcher` orchestrator + orthogonal pure
  helpers (query parsing, locale dedup, chunk classification, graph rerank).
  Public surface: `VaultSearcher`, `ParsedQuery`, `SearchResult`, `parse_query`,
  `rerank_with_graph` (+ tests import `_locale_variant_key`,
  `_classify_chunk_type`, `_collapse_locale_variants`).

- **`commands.py` — SPLIT.** Symmetric `install_run` / `uninstall_run`
  orchestrators + torch-config sub-flow + uv-sync subprocess + report
  dataclasses + workspace helpers. Public surface: `install_run`,
  `uninstall_run`, `InstallReport`, `UninstallReport` (+ tests import
  `_classify_uv_sync_result`).

- **`store.py` — KEEP.** A single cohesive `VaultStore` class plus its
  dataclasses (`VaultDocument`, `CodeChunk`) and exception
  (`VaultStoreLockedError`); the helpers exist only to serve the one class. No
  architectural seam — splitting would scatter one unit. 984 lines is
  manageable for a single well-formed class.

## Recommendations

- Run the standard pipeline: this audit → an ADR fixing the package pattern and
  the re-export contract → a plan with one phase per module → test-gated
  execution.
- The package pattern: `module/__init__.py` re-exports the verbatim public
  surface (an explicit `__all__` that includes the externally-imported
  `_`-prefixed helpers, since tests depend on them); cohesive code moves into
  `_`-prefixed submodules; shared module-level state lives in the package init.
- Order execution low-risk → high-risk to validate the pattern early:
  `commands` (or `torch_config`) first, then `search`, `indexer`, `cli`, and
  `mcp_server` last (FastMCP registration + entry point).
- Gate every module split on the **full** relevant test suite passing
  unchanged, plus ruff/ruff-format/ty clean. Do not change the public import
  surface; tests must pass without edits.
- Keep `store.py` a single file.

## Codification candidates

- **Source:** the package-split pattern adopted across six modules.
  **Rule slug:** `module-package-reexport-preserves-surface`.
  **Rule:** When a module is split into a package, its `__init__.py` must
  re-export the verbatim pre-split public surface (via an explicit `__all__`,
  including any `_`-prefixed names imported elsewhere) so no import changes.
