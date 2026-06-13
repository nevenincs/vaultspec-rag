---
name: vaultspec-rag
---

# Vaultspec RAG — GPU-accelerated search

vaultspec-rag is a companion package to vaultspec-core. It provides
GPU-accelerated semantic search across vault documents and codebase
using dense/sparse hybrid embeddings and a Qdrant vector store (an
embedded local store by default, or a managed Qdrant server).

Both packages share the same workspace (`.vault/`, `.vaultspec/`) but
operate independently: core handles structured vault CRUD and health
checks, RAG handles semantic search and retrieval.

## Auto-reindex (DO / DO NOT)

The resident HTTP service runs a filesystem watcher that incrementally
re-indexes on change. Default is **on**. The CLI calls this feature
"automatic index updates".

- **DO NOT manually reindex during normal work.** The running service watches
  `.vault/` docs and tracked source and re-indexes incrementally; manual
  reindex is redundant and competes for the single-writer GPU/Qdrant path.
- **DO use `--no-updates` (or `VAULTSPEC_RAG_WATCH_ENABLED=0`)** to make the
  service pull-only when you want manual or externally-scheduled indexing.
- **DO check update state before assuming staleness:** run
  `vaultspec-rag server updates status` (or the `get_watcher_state`
  MCP tool) instead of guessing whether the index is current.
- **DO tune, don't disable, for noise:** raise `--update-delay-ms` /
  `--same-project-delay-s` rather than turning updates off. `0` on either knob
  means "no delay", not "disabled" — only `watch_enabled=false` disables.
- **DO reindex explicitly only** for a first-time index, after `--no-updates`,
  or to force a clean rebuild (`index --rebuild`, or `reindex_*(clean=true)`).

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
index [--type vault|code|all] [--rebuild] [--port N] [--allow-fallback]
      [--dry-run] [--exclude PATTERN] [--model NAME] [--verbose] [--json]
                             Build or update the index. Uses the running
                             service when available; otherwise runs locally.
                             --type defaults to all. --rebuild deletes the
                             selected index data before rebuilding it. --port
                             targets a running service; on a dead port the CLI
                             hard-fails unless --allow-fallback is set.
                             --dry-run lists files that would be indexed.
search QUERY [--type vault|code] [--max-results/--limit N=10] [--port N]
       [--allow-fallback] [--json]
                             Vault filters: --doc-type --feature --date --tag
                             Code filters: --language --path --function-name
                             --class-name --structure --prefer --dedup-locales
                             Code path globs (post-query fnmatch, repeatable):
                             --include-path PATTERN, --exclude-path PATTERN
                             Or use in-query tokens: type:adr feature:auth
                             path:src/foo lang:python func:main class:Engine
                             date:2026-03 tag:auth nodetype:function_definition
status                       Show index counts, index data location, and
                             compute device.
clean vault|code|all [-y] [--json]
                             Delete selected index data without rebuilding it.
                             The target is required so nothing is wiped by
                             accident; --json requires --yes.
```

Path indicator: the search results table title is suffixed `(via MCP)` when
the query was delegated to the running service, `(via in-process)` when the
local fallback ran. Default `--max-results` is 10.

Most commands accept `--json` for machine-readable output; exit codes match
human mode.

Server management:

```
server start [--updates/--no-updates] [--update-delay-ms N]
             [--same-project-delay-s S] [--qdrant/--no-qdrant]
             [--qdrant-auto-provision] [--port N]
                             Start the background HTTP search service and wait
                             until it is ready. --updates toggles automatic
                             index updates. --qdrant selects the managed Qdrant
                             server; --qdrant-auto-provision downloads it if
                             missing (otherwise start prints the install
                             command).
server stop                  Stop the background search service.
server status [--verbose] [--json]
                             Human operator summary for service health, work,
                             and next checks. Exit codes: 0 running, 3 stopped
                             (no service.json), 4 crashed or divergent (file
                             present but PID dead, port silent, heartbeat
                             stale, or PID reused). --verbose adds process,
                             heartbeat, identity, and model detail.
server warmup                Download GPU model files before they are needed.
server logs [--limit N] [--job-id ID] [--contains TEXT] [--raw]
                             Show recent activity from the service log
                             (rotated-set aware), filtered to a bounded window.
server jobs [--limit N] [--state S] [--index vault|code]
            [--started-by WHO] [-q TEXT] [--running] [--failed]
            [--job-id ID] [--since SECONDS] [--watch]
                             Recent and in-flight index update activity,
                             bounded and filterable.
server projects list|unload  Inspect or unload projects held by the service.
server updates status|start|stop|timing
                             Inspect and control automatic index updates.
                             start/stop/timing take a PROJECT argument; timing
                             accepts --update-delay-ms / --same-project-delay-s.
server qdrant install|status|clean
                             Install, inspect, or remove the managed Qdrant
                             server binary.
```

Read-only HTTP routes on the running service (loopback-bound). `GET /health`
is ungated; `GET /logs?lines=N` (text), `GET /jobs` (JSON), and `GET /metrics`
(Prometheus text) require the `service_token` as a bearer
(`Authorization: Bearer <token>`, found in `service.json` / `/health`). These
are monitoring surfaces, not an auth boundary — keep the service on loopback.

Development:

```
benchmark                    Measure search speed on the current index.
quality                      Run built-in search quality checks.
test [PYTEST_ARGS...]        Run the test suite.
preprocess list|check|run-one  Inspect and validate document preprocessing
                             rules (.vaultragpreprocess.toml).
```

## MCP Tools

The `vaultspec-search-mcp` server exposes the following tools. The admin tool
names retain `watcher`/`evict` even though the CLI renamed those surfaces to
`updates`/`unload`.

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
  mirrors `server projects list`.
- `evict_project(root)` — evict a project's resident slot; mirrors
  `server projects unload`.
- `get_watcher_state(project_root?)` — report update config
  (`watch_enabled`, `debounce_ms`, `cooldown_s`) and watched roots;
  mirrors `server updates status`.
- `start_watcher(root)` — eagerly start updates for a root
  (no-op when `watch_enabled` is false).
- `stop_watcher(root)` — stop updating a root (pull-only for it).
- `reconfigure_watcher(root, debounce_ms?, cooldown_s?)` — restart a
  root's updates with new tuning (stop + restart).
- `get_service_state(project_root?)` — consolidated read: per-source index
  counts, GPU/device, project slots, and an update rollup.
- `get_logs(lines?)` — tail of the service log across the rotated set.
- `get_jobs(limit?)` — recent and in-flight index update activity from the
  in-flight registry.
- `benchmark(...)` / `quality()` — run search speed or quality checks against
  the running service.

Resource: `vault://{doc_id}` — retrieve full vault document content by
stem ID (e.g., `vault://adr/gpu-only-rag-stack`).

Prompt: `analyze_feature(feature_name)` — generates a structured prompt
to analyze a feature across docs and code.

## Entry Points

- `vaultspec-rag` — CLI (package: `vaultspec_rag.__main__:main`)
- `vaultspec-search-mcp` — MCP server, stdio mode
  (package: `vaultspec_rag.server:main`)
- `vaultspec-rag server start` — HTTP RAG service

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
- `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS` — update debounce window (default: 2000)
- `VAULTSPEC_RAG_WATCH_COOLDOWN_S` — per-source re-index cooldown
  (default: 30)
- `VAULTSPEC_RAG_QDRANT_SERVER` / `VAULTSPEC_RAG_QDRANT_URL` — opt into and
  address a managed or external Qdrant server (the `--qdrant` flags are the
  CLI equivalents)
