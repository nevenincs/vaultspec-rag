---
name: vaultspec-rag
---

# Vaultspec RAG — GPU-accelerated search

vaultspec-rag is a companion package to vaultspec-core. It provides
GPU-accelerated semantic search across vault documents and codebase
using dense/sparse hybrid embeddings and a local Qdrant vector store.

Both packages share the same workspace (`.vault/`, `.vaultspec/`) but
operate independently: core handles structured vault CRUD and health
checks, RAG handles semantic search and retrieval.

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
                             unless --allow-fallback is set.
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
server service start         Start the HTTP RAG service
server service stop          Stop the HTTP RAG service
server service status        Show service status. Exit codes: 0 running,
                             3 stopped (no service.json), 4 crashed or
                             divergent (file present but PID dead, port
                             silent, heartbeat stale, or PID reused).
                             Daemon writes last_heartbeat every 15s;
                             stale threshold 60s.
server service warmup        Pre-load GPU models without serving
```

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

Resource: `vault://{doc_id}` — retrieve full vault document content by
stem ID (e.g., `vault://adr/gpu-only-rag-stack`).

Prompt: `analyze_feature(feature_name)` — generates a structured prompt
to analyze a feature across docs and code.

## Entry Points

- `vaultspec-rag` — CLI (package: `vaultspec_rag.__main__:main`)
- `vaultspec-search-mcp` — MCP server stdio mode
  (package: `vaultspec_rag.mcp_server:main`)
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
