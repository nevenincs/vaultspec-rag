---
name: vaultspec-rag.builtin
trigger: always_on
---

# Vaultspec RAG — GPU-accelerated search

vaultspec-rag is a companion package to vaultspec-core. It provides
GPU-accelerated semantic search across vault documents and codebase
using dense/sparse hybrid embeddings and a local Qdrant vector store.

Both packages share the same workspace (`.vault/`, `.vaultspec/`) but
operate independently: core handles structured vault CRUD and health
checks, RAG handles semantic search and retrieval.

## Auto-reindex (DO / DO NOT)

The resident HTTP service runs a filesystem watcher that incrementally
re-indexes on change. Default is **on**.

- **DO NOT manually reindex during normal work.** The running service watches
  `.vault/` docs and tracked source and re-indexes incrementally; manual
  reindex is redundant and competes for the single-writer GPU/Qdrant path.
- **DO use `--no-watch` (or `VAULTSPEC_RAG_WATCH_ENABLED=0`)** to make the
  service pull-only when you want manual or externally-scheduled indexing.
- **DO check watcher state before assuming staleness:** run
  `vaultspec-rag server service watcher status` (or the `get_watcher_state`
  MCP tool) instead of guessing whether the index is current.
- **DO tune, don't disable, for noise:** raise `--watch-debounce-ms` /
  `--watch-cooldown-s` rather than turning the watcher off. `0` on either knob
  means "no delay", not "disabled" — only `watch_enabled=false` disables.
- **DO reindex explicitly only** for a first-time index, after `--no-watch`, or
  to force a clean rebuild (`reindex_*(clean=true)`).

## When to use RAG vs Core

- **Use `vaultspec-rag search`** (CLI) or `search_vault`/`search_codebase`
  (MCP tools) for semantic, natural-language queries across vault documents
  and source code. RAG finds conceptually related content even when exact
  keywords don't match.
- **Use `vaultspec-core vault list/check`** for structured operations:
  listing documents, checking vault health, managing frontmatter, and
  running integrity checks.

## CLI Commands

If the current virtual environment has `vaultspec-rag` installed, run it
directly as `vaultspec-rag` or `uv run vaultspec-rag` in uv managed
environments.

Search and indexing:

```
index [--type vault|code|all] [--rebuild] [--port N] [--allow-fallback] [--verbose]
                             Index vault docs and/or codebase. --port delegates to
                             a running service; on dead port, the CLI hard-fails
                             unless --allow-fallback is set. --rebuild REQUIRES
                             an explicit --type since 0.2.9 (#115); bare `index`
                             stays incremental + safe. --rebuild --type X is now
                             scoped to X (was: whole-directory rmtree).
search <query> [--type vault|code] [--max-results N=10] [--no-truncate]
       [--port N] [--allow-fallback] [--verbose]
                             Code filters: --language --path --node-type
                             --function-name --class-name
                             Code path globs (post-query fnmatch, repeatable):
                             --include-path PATTERN, --exclude-path PATTERN
                             Vault filters: --doc-type --feature --date --tag
                             Or use in-query tokens: type:adr feature:auth
                             path:src/foo lang:python func:main class:Engine
                             date:2026-03 tag:auth nodetype:function_definition
status                       Show index status and GPU info.
```

Path indicator: search results table title is suffixed `(via MCP)` when
delegated, `(via in-process)` when the local fallback ran. Default
`--max-results` is 10 (raised from 5 to mitigate top-k crowding).
`clean` requires an explicit target since 0.2.9 — `vaultspec-rag clean`
without an argument errors out instead of wiping everything.

Every command supports `--json` for structured stdout. Envelope:
`{"ok": bool, "command": str, "data" | "error" + "message"}`.
`clean --json` requires `--yes`. Exit codes match table-mode.

Server management:

```
server mcp start             Start the MCP server (stdio)
server mcp stop              Stop the MCP server
server mcp status            Show MCP server status
server service start [--watch/--no-watch] [--watch-debounce-ms N]
                     [--watch-cooldown-s S]
                             Start the HTTP RAG service. Watcher flags are
                             translated to VAULTSPEC_RAG_WATCH* env on the
                             daemon (it inherits only env). Unset flags leave
                             any operator-set env untouched.
server service stop          Stop the HTTP RAG service
server service status        Show service status. Exit codes: 0 running,
                             3 stopped (no service.json), 4 crashed or
                             divergent (file present but PID dead, port
                             silent, heartbeat stale, or PID reused).
                             Daemon writes last_heartbeat every 15s;
                             stale threshold 60s.
server service warmup        Pre-load GPU models without serving
server service projects list|evict   Inspect / evict project slots.
server service info          Consolidated state: index counts + GPU + projects
                             + watcher rollup (get_service_state).
server service logs [--lines N]      Tail the service log (rotated-set aware).
server service jobs [--limit N]      Recent + in-flight index/reindex activity.
server service watcher status        Show watcher config + watched roots.
server service watcher start <root>  Eagerly watch a root (no-op if disabled).
server service watcher stop <root>   Stop watching a root (pull-only for it).
server service watcher reconfigure <root> [--debounce-ms N] [--cooldown-s S]
                             Restart a root's watcher with new tuning.
```

Read-only HTTP routes on the running service (loopback-bound). `GET /health`
is ungated; `GET /logs?lines=N` (text), `GET /jobs` (JSON), and `GET /metrics`
(Prometheus text) require the `service_token` as a bearer
(`Authorization: Bearer <token>`, found in `service.json` / `/health`). These
are monitoring surfaces, not an auth boundary — keep the service on loopback.

Development:

```
benchmark                    Run search quality benchmarks
quality                      Run search quality checks
test [PYTEST_ARGS...]        Run the test suite
```

## MCP Tools

The `vaultspec-search-mcp` server exposes the following tools:

- `search_vault(query, top_k, doc_type?, feature?, date?, tag?, project_root?)` —
  semantic search across vault documents. Filters mirror the CLI
  `--doc-type`/`--feature`/`--date`/`--tag` flags. Returns ranked
  results with scores and metadata.
- `search_codebase(query, top_k, language?, path?, node_type?, function_name?, class_name?, include_paths?, exclude_paths?, project_root?)` —
  semantic search across indexed source code. Filters mirror the CLI
  `--language` / `--path` / `--node-type` / `--function-name` /
  `--class-name` (exact KEYWORD) plus `--include-path` /
  `--exclude-path` (`list[str]`, fnmatch glob, applied post-query
  against the POSIX-normalised project-relative path).
- `get_index_status(project_root)` — returns index statistics, document
  counts, and GPU hardware info.
- `get_code_file(path, project_root)` — retrieve full source file content
  by path.
- `reindex_vault(clean, project_root)` — re-index vault documents.
  Incremental by default; `clean=true` drops and rebuilds.
- `reindex_codebase(clean, project_root)` — re-index source code.
  Incremental by default; `clean=true` drops and rebuilds.
- `list_projects()` — list active project slots (root, idle, refs);
  mirrors `server service projects list`.
- `evict_project(root)` — evict a project's resident slot; mirrors
  `server service projects evict`.
- `get_watcher_state(project_root?)` — report watcher config
  (`watch_enabled`, `debounce_ms`, `cooldown_s`) and watched roots.
- `start_watcher(root)` — eagerly start the watcher for a root
  (no-op when `watch_enabled` is false).
- `stop_watcher(root)` — stop watching a root (pull-only for it).
- `reconfigure_watcher(root, debounce_ms?, cooldown_s?)` — restart a
  root's watcher with new tuning (stop + restart).
- `get_service_state(project_root?)` — consolidated read: per-source index
  counts, GPU/device, project slots, and a watcher rollup.
- `get_logs(lines?)` — tail of the service log across the rotated set.
- `get_jobs(limit?)` — recent and in-flight index/reindex activity from the
  in-flight registry.

Resource: `vault://{doc_id}` — retrieve full vault document content by
stem ID (e.g., `vault://adr/gpu-only-rag-stack`).

Prompt: `analyze_feature(feature_name)` — generates a structured prompt
to analyze a feature across docs and code.

## Entry Points

- `vaultspec-rag` — CLI (package: `vaultspec_rag.__main__:main`)
- `vaultspec-search-mcp` — MCP server stdio mode
  (package: `vaultspec_rag.mcp:main`)
- `vaultspec-rag server mcp start` — MCP server via CLI
- `vaultspec-rag server service start` — HTTP RAG service

## Data Directory

RAG stores its index data at `.vault/data/search-data/`. This directory
is gitignored and invisible to core's vault scanner. Do not manually
modify files in this directory.

## Environment Variables

RAG-specific configuration uses the `VAULTSPEC_RAG_` prefix:

- `VAULTSPEC_RAG_ROOT` — override project root resolution
- `VAULTSPEC_RAG_DATA_DIR` — override data directory location
- `VAULTSPEC_RAG_PORT` — HTTP server port (default: 8766)
- `VAULTSPEC_RAG_LOG_LEVEL` — logging verbosity
- `VAULTSPEC_RAG_WATCH_ENABLED` — auto-reindex on/off (default: `1`; set
  `0` for a pull-only service)
- `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS` — watcher debounce window (default: 2000)
- `VAULTSPEC_RAG_WATCH_COOLDOWN_S` — per-source re-index cooldown
  (default: 30)
