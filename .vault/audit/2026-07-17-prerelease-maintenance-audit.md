---
tags:
  - '#audit'
  - '#prerelease-maintenance'
date: '2026-07-17'
modified: '2026-07-27'
related: []
---

# `prerelease-maintenance` audit: `pre-release maintenance, robustness, and correctness sweep`

## Scope

Pre-release (post 0.3.0, pre next release) maintenance audit requested by
the operator: factual review of README and every `docs/` page against the
code; dead-code hunt across production sources; module-size review against
the 1000-line ratchet with split decisions; all `just` lint/check gates and
the test suites as the verification floor. Driven by a fleet of runner and
fact-checker agents with fixes applied by dedicated fixer agents; module
architecture judgments made by the orchestrating session directly.

## Findings

### mcp-doc-fictional-http-transport | high | docs/mcp.md documents an MCP-over-HTTP transport that does not exist

The "Configure an HTTP client" section instructs users to point an
`.mcp.json` entry at `http://127.0.0.1:8766/mcp/`. The daemon serves
native REST only and mounts no MCP app (`server/_main.py` states stdio is
the sole MCP transport; no `/mcp/` route exists in `server/_routes.py`).
A user following the section gets a silently dead integration.

### mcp-doc-wrong-tool-list | high | docs/mcp.md lists ten-plus MCP tools; five exist

Registered tools are exactly `search_vault`, `search_codebase`,
`get_code_file`, `reindex_vault`, `reindex_codebase`
(`mcp/_tools.py`). The documented `get_index_status` and the entire
"admin tools" set (`list_projects`, `evict_project`, `get_service_state`,
`get_jobs`, `get_logs`, watcher controls) are HTTP REST routes, not MCP
tools; the page predates the five-tool narrowing.

### cli-doc-flag-gaps | medium | cli.md omits install --mode and --torch-group

The canonical flag reference omits `--mode {tool,dependency,dev}`
(documented only narratively in installation.md) and `--torch-group`
(documented nowhere), both real typer options in `cli/_install.py`.

### config-doc-intent-knobs-gap | medium | configuration.md omits the three vault intent-ranking env vars

`VAULTSPEC_RAG_VAULT_INTENT_DEFAULT`, `..._INTENT_RANKING_ENABLED`, and
`..._INTENT_TYPE_CAP` (config.py) are operator-facing and undocumented.

### stale-version-examples | low | getting-started.md and installation.md show v0.2.23 example output

Both version-check walkthroughs print `vaultspec-rag v0.2.23`; current is
0.3.x. Illustrative only, but confusing for new users.

### oversized-modules | medium | 13 modules exceed the 1000-line ratchet (7 production)

`cli/_service_lifecycle.py` 2232, `indexer/_codebase_indexer.py` 1827,
`store.py` 1774, `server/_routes.py` 1350, `cli/_service_jobs.py` 1172,
`search/_searcher.py` 1164, `qdrant_runtime/_supervise.py` 1001; tests:
`test_cli.py` 6113, `integration/test_service_jobs.py` 1745,
`test_server.py` 1531, `test_torch_config.py` 1318,
`test_indexer_unit.py` 1314, `test_install_torch_config.py` 1197.
Split decisions recorded under Recommendations.

### absolute-imports-in-tests | medium | 14 absolute vaultspec_rag imports in test files fail the local gate

`just dev lint absolute-imports` fails on Windows with 14 function-local
`from vaultspec_rag....` imports across five test modules (10 of them in
`test_cli.py`). The Linux CI variant of the recipe globs shallower and
misses them, so CI stays green while the local gate fails - both an
import-convention violation and a gate-parity inconsistency worth noting.
All other gates pass: ruff, ty, basedpyright strict, taplo, mdformat and
pymarkdown, actionlint, complexity, module-length (report-only), and the
dependency audit (0 vulnerabilities across 140 packages).

### stale-hook-sandbox-comment | low | \_hook_sandbox.py still describes a scratch-dir cwd

The module's own prose still says hooks run with "a fresh scratch
directory as its cwd", but the call site runs them with the project root
as cwd (`_preprocess_runner.py`), the deliberate post-sandbox-removal
behavior (scratch cwd broke uv-run hooks). Code-comment staleness only;
README/docs describe the current behavior correctly - the seven pages in
the third docs slice (README, architecture, indexing, search-and-index,
preprocessing-hooks, automation, glossary) all verified CLEAN, including
exact numeric claims (embed caps, RRF k=60, reranker OOM backoff) and the
torch 2.13.0+cu130 pin.

### absolute-imports-gate-parity | medium | The gate's backslash globs made CI pass vacuously and missed deep paths

Root cause of the CI/local disagreement: the justfile recipe globbed
`src\vaultspec_rag\*.py, src\vaultspec_rag\*\*.py` - backslash paths
match nothing under Linux pwsh (CI green with zero files scanned) and
miss three-level paths everywhere (tests/integration). RESOLVED: the
recipe now scans recursively with forward-slash-safe `Get-ChildItem -Recurse`, honors an explicit `absolute-import-ok` marker for the four
fresh-interpreter subprocess snippets where relative imports are
impossible, and one genuinely wrong function-local absolute import the
old glob never reached (`test_ecosystem_integration.py`) was converted
to relative. Gate now exits 0 locally and scans identically on CI.

### dead-code-trio | low | Three dead symbols; production tree otherwise clean

The dead-code sweep (ruff F401/F811/F841/ERA001 plus an AST
cross-reference scan of src and tests, with decorator-registration
awareness for typer/pydantic/HTMLParser/Route/FastMCP surfaces) found
exactly three dead symbols and nothing else: `EmbeddingModel. _default_batch_size` in `embeddings.py` (never called; the live slice
sizing reads `get_config().embedding_batch_size` directly at the call
sites, so the env knob itself stays), and `_build_gitignore_spec` plus
`_get_language` in `indexer/_codebase_indexer.py` (both orphaned
duplicates of inline logic). No test-only production exports, no orphan
modules, no orphaned EnvVar members (all 59 trace to live reads).
RESOLVED: all three deleted during the fix wave.

### duplicated-cli-format-helper | low | \_counted_unit duplicated across two CLI modules

`cli/_service_lifecycle.py` and `cli/_service_jobs.py` both define
`_counted_unit` verbatim; CLI formatting helpers lack a single home.

### split-campaign-results | low | Split outcomes and accepted deviations

Executed as pure moves with facade re-exports; every splitter verified
ruff/basedpyright/ty plus its area's tests before handing back.

- `cli/_service_lifecycle.py` 2233 -> 205 facade + `_service_start` 698,
  `_service_stop` 370, `_status_render` (label cluster further split
  into `_status_labels`), `_cli_format` 65 (deduplicates
  `_counted_unit`). `_service_jobs.py` 1129 ACCEPTED over the mark:
  pushing job-vocabulary helpers into the generic formatter module would
  make it a domain grab-bag.
- `store.py` 1774 -> 1041 + `_store_models` 274, `_store_locks` 97,
  `_store_search` 474 (search mixin; `_point_lock`/lifecycle lock stay
  in `store.py`, acquisition sites byte-identical). Search log records
  now emit under `vaultspec_rag._store_search` (idiomatic per-module
  logger; nothing asserts the old name).
- `server/_routes.py` 1350 -> 992 + `_routes_jobs` 249,
  `_routes_storage` 128 (lifecycle-inert, cli-import-free),
  `_routes_logs` 76. `_gather_storage_survey` deliberately stayed:
  tests monkeypatch `_routes._fetch_surveys` through the module
  namespace.
- `indexer/_codebase_indexer.py` 1827 -> 1625 + `_ignore_specs` 126,
  `_preprocess_glue` 133, `_code_meta` 152. ACCEPTED over the mark:
  the remainder is the rule-bound GPU pipeline plus orchestration
  coupled through indexer state; a delegator split threading private
  state across modules would reduce correctness legibility for a
  report-only ratchet number.
- `search/_searcher.py` 1164 -> 1020 + `_result_shaping` 228; the
  GPU-lock and reranker-content invariant code deliberately unmoved.
- `tests/test_cli.py` 6113 -> nine modules (largest 927-line shared
  `_cli_helpers.py`, non-collected), collected-test count 261 -> 261
  verified identical, all passing.

### final-verification | low | Combined tree green across every gate and the full unit suite

Post-wave central verification: ruff, ty, basedpyright strict,
complexity, absolute-imports, mdformat and pymarkdown all pass; the
module ratchet drops from 13 to 10 over-mark modules (every production
module at or under the mark except the two accepted deviations and
`store.py` at 1041); the full unit suite reports 1417 passed (baseline
1409 - the delta is the preserved-but-recounted split modules plus the
watchdog additions), and the stdio-lifetime and ecosystem integration
suites pass. One stale integration assertion surfaced and was fixed:
core 0.1.39+ renders the seeded MCP entry in module form
(`uv run python -m vaultspec_rag.server`), an equivalent stdio entry
point the test now accepts alongside the console script.

## Recommendations

- Rewrite `docs/mcp.md`: drop the HTTP-MCP section (stdio is the only MCP
  transport), correct the tool list to the five real tools, and point
  admin capabilities at the HTTP routes in service-mode.md.
- Close the cli.md / configuration.md gaps and refresh the stale version
  examples.
- Module splits (facade-preserving so rule/regression references stay
  true): `_service_lifecycle` into start/stop/status-render modules with
  the original as re-exporting facade; `_codebase_indexer` extracts
  ignore-spec building and preprocess glue (GPU pipeline stays);
  `store.py` extracts models/payloads and file-lock primitives with
  re-exports; `_routes` extracts jobs and storage shaping helpers;
  `_service_jobs` extracts label/format helpers into a shared CLI
  formatting module (also resolves the `_counted_unit` duplication);
  `_searcher` light extraction only (rerank and GPU-lock rules bind it);
  `_supervise` at 1001 stays. `test_cli.py` splits by command domain.

## Recommendations
Evidence gap: the retained audit body and complete git log --follow history state no additional recommendations beyond the preceding section. No recommendation is asserted.
