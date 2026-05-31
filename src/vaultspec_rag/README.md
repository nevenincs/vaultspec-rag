# vaultspec-rag

GPU-accelerated hybrid search over vault documents and source code. This is an extension to [vaultspec-core](https://github.com/wgergely/vaultspec-core) and requires it as a dependency. See the [project README](../../README.md) for background. Report issues on the [GitHub tracker](https://github.com/wgergely/vaultspec-rag/issues).

## Prerequisites

- NVIDIA GPU with CUDA support (no CPU fallback; raises `RuntimeError` without one)
- Python >= 3.13
- [vaultspec-core](https://github.com/wgergely/vaultspec-core) >= 0.1.0
- ~3 GB free VRAM (Qwen3 ~1.5 GB, SPLADE ~0.5 GB, reranker ~0.56 GB)

## Installation

Install with `uv`:

```sh
uv add vaultspec-rag
```

PyTorch requires the CUDA package index. The project's `pyproject.toml` configures the `pytorch-cu130` index at `https://download.pytorch.org/whl/cu130` automatically.

Two entry points register on install:

- `vaultspec-rag` -- CLI
- `vaultspec-search-mcp` -- MCP server

Verify the installation:

```sh
vaultspec-rag --version
```

## Quick start

From a directory containing `.vault/` and `.vaultspec/`, run:

```sh
cd your-project
vaultspec-rag index
vaultspec-rag search "your query"
```

`index` builds embeddings for both vault documents and source code. `search` queries the vault by default and returns the top 10 results as a table with Score, Location, and Snippet columns. Override the count with `--max-results`.

## Usage modes

The CLI runs in one of two modes: **ad-hoc** and **service-delegated**.

**Ad-hoc mode** runs everything in-process. Each CLI command loads the GPU models, performs the operation, and exits. This is the default; installation is the only setup. The tradeoff is that loading models takes several seconds per invocation.

```sh
vaultspec-rag index
vaultspec-rag search "your query"
```

**Service-delegated mode** points the CLI at a running HTTP daemon via `--port`. Models stay loaded in VRAM across invocations, so each command returns near-instantly. The CLI sends the current workspace as `project_root` on every call, so one daemon serves any project.

```sh
vaultspec-rag server service start
vaultspec-rag search --port 8766 "your query"
vaultspec-rag index --port 8766
```

Ad-hoc mode owns the local `qdrant-local` storage in the current
process. Because the storage process model is `exclusive`, a second
`vaultspec-rag` process cannot open the same local Qdrant directory;
lock contention is reported with guidance to use one resident service.

Service-delegated mode sends `project_root` to the HTTP MCP service on
every delegated call. If the service is unreachable, `search --port`
hard-fails with remediation steps so the CLI never silently acquires
the Qdrant lock and strands the resident daemon. Pass `--allow-fallback`
to opt in to in-process execution. Structured lock contention renders
the backend contract table and exits instead of retrying unsafely.

Use ad-hoc for one-off tasks or environments where a persistent process isn't practical. Use service-delegated for active development. It keeps one shared daemon across projects and returns results near-instantly.

For AI tools that speak MCP directly (Claude Desktop, Claude Code), see [MCP integration](#mcp-integration). The same daemon serves them, with different project-resolution rules per transport.

## Architecture overview

### Access layers

Three interfaces expose the same underlying engine: the CLI (`vaultspec-rag`), the MCP server (`vaultspec-search-mcp`), and the Python API (`vaultspec_rag.api`).

The CLI runs indexing and search in-process by default. Pass `--port` to delegate to a running MCP service over HTTP. If the service is unreachable, the CLI hard-fails with remediation; add `--allow-fallback` to opt in to in-process execution instead.

The MCP server wraps the engine behind tool endpoints, accepting connections from any MCP-compatible client. The Python API is the underlying facade -- call `index()`, `search_vault()`, and `search_codebase()` directly.

### Backend capability contract

| Capability                    | Value          |
| ----------------------------- | -------------- |
| Backend                       | `qdrant-local` |
| Concurrent search accepted    | `true`         |
| Same-project search strategy  | `serialized`   |
| Cross-project search strategy | `parallel`     |
| Storage process model         | `exclusive`    |

Concurrent search support means requests can be accepted concurrently.
It does not mean same-project Qdrant access runs fully in parallel;
vault and code hybrid searches serialize the local backend portion
inside the process.

### GPU model lifecycle

A single shared `EmbeddingModel` loads three models into VRAM once at initialization:

- **Dense encoder** -- `Qwen/Qwen3-Embedding-0.6B` (1024-dimensional vectors, fp16)
- **Sparse encoder** -- `naver/splade-v3` (asymmetric SPLADE with separate query and document encoding)
- **Reranker** -- `BAAI/bge-reranker-v2-m3` (CrossEncoder with sigmoid activation, loaded lazily on first use)

A shared lock serializes GPU operations. CUDA is mandatory -- the system raises `RuntimeError` if no GPU is available.

### Multi-project support

The MCP service manages isolated per-project slots. Each slot contains its own Qdrant store, indexers, searcher, and relationship graph cache. All slots share the single `EmbeddingModel` instance.

MCP tools accept a `project_root` parameter to target a specific project. Different projects initialize in parallel under per-root locks.

Different project roots can initialize and proceed concurrently under
isolated project slots. Same-root local backend access still serializes.
All project slots share one `EmbeddingModel` instance and the GPU lock.

### File watching

When running as a service, background watchers monitor vault (`.md`) and source files for each registered project. Changes trigger incremental reindexing after a 2-second debounce.

Per-source cooldowns of 30 seconds prevent thrashing. Vault and codebase cooldowns are independent -- a burst of `.md` edits won't delay source reindexing.

Vault changes also invalidate the relationship graph cache.

## CLI commands

Run `vaultspec-rag --help` for the full option list.

### Command tree

```
vaultspec-rag
├── index              Index vault documents and/or codebase source files
├── search             Search documentation or code
├── status             Show engine status, storage metrics, and GPU info
├── benchmark          Run search latency probes (p50/p95/p99)
├── quality            Run precision probes against a synthetic corpus
├── test               Run the test suite (forwards args to pytest)
└── server
    ├── mcp
    │   ├── start      Start MCP server (stdio by default, HTTP with --port)
    │   ├── stop       Guidance for stopping (Ctrl+C)
    │   └── status     Show registered tools, resources, and prompts
    └── service
        ├── start      Spawn background daemon (HTTP, default port 8766)
        ├── stop       Stop the background service
        ├── status     Show daemon health and backend capabilities
        ├── warmup     Pre-download model weights to HuggingFace cache
        └── projects
            ├── list   Show per-project slot table (idle, refs, last access)
            └── evict  Evict an idle project slot by root path
```

**Global options:** `--target` / `-t` sets the workspace root. `--verbose` / `-v` and `--debug` / `-d` control log verbosity. `--version` / `-V` prints the installed version.

**Config overrides:** `--data-dir`, `--qdrant-dir`, `--index-meta`, `--code-index-meta`, `--status-dir`, and `--log-file` override the default storage paths.

### The `--port` fast path

The `index` and `search` commands accept a `--port` flag. When set, the CLI delegates to a running MCP service over HTTP instead of loading GPU models in-process. If the service is unreachable, the CLI hard-fails with remediation steps; add `--allow-fallback` to opt in to in-process execution.

Loading the embedding models takes several seconds on a cold start. Point `--port` at a running `server service` instance to skip that overhead entirely.

When a delegated search receives structured local-store lock contention
from the service, the CLI renders the backend contract table and exits
instead of falling back into another unsafe local open.

## Configuration

### Precedence

Configuration resolves through three tiers: CLI flags override environment variables, which override built-in defaults. Boolean env vars accept `1`, `true`, or `yes` (case-insensitive). The system parses integer and float values from strings.

### Environment variables

| Variable                                 | Default                   | Description                                                    |
| ---------------------------------------- | ------------------------- | -------------------------------------------------------------- |
| `VAULTSPEC_RAG_ROOT`                     | cwd                       | Project root directory                                         |
| `VAULTSPEC_RAG_DATA_DIR`                 | `.vault/data/search-data` | Search data directory                                          |
| `VAULTSPEC_RAG_QDRANT_DIR`               | `qdrant`                  | Qdrant storage subdirectory, relative to data dir              |
| `VAULTSPEC_RAG_INDEX_META`               | `index_meta.json`         | Vault index metadata filename                                  |
| `VAULTSPEC_RAG_CODE_INDEX_META`          | `code_index_meta.json`    | Codebase index metadata filename                               |
| `VAULTSPEC_RAG_STATUS_DIR`               | `~/.vaultspec-rag`        | Service status and log directory                               |
| `VAULTSPEC_RAG_LOG_FILE`                 | `service.log`             | Log filename, relative to status dir                           |
| `VAULTSPEC_RAG_PORT`                     | `8766`                    | MCP HTTP server port                                           |
| `VAULTSPEC_RAG_LOG_LEVEL`                | `WARNING`                 | Logging level                                                  |
| `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS` | `1800`                    | Idle TTL before an unused project slot is evicted (0 disables) |
| `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`     | `16`                      | Maximum concurrent project slots (0 disables the LRU cap)      |
| `VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES`    | `10485760`                | Daemon log rotation threshold in bytes (0 disables rotation)   |
| `VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT` | `5`                       | Number of rotated log backups to retain                        |

The tool also respects two third-party environment variables. Set `HF_HOME` to control where HuggingFace caches downloaded models. Set `HF_HUB_DOWNLOAD_TIMEOUT` to increase the model download timeout.

### `.vaultragignore`

Place a `.vaultragignore` file at the project root to exclude files from codebase indexing. It uses gitignore syntax via `pathspec`. Patterns merge with CLI `--exclude` flags.

Codebase indexing always excludes vaultspec internal directories, including `.vault/` and `.vaultspec/`. Vault documents remain available through vault indexing and `--type vault`; they are not mixed into `--type code` results.

This file operates independently from `.gitignore` -- both apply with OR logic. The indexer skips any file excluded by either spec.

## Service management

### Foreground vs. background

`vaultspec-rag server mcp start` runs the MCP server in the foreground over stdio transport, suitable for direct LLM integration. Pass `--port` to switch to HTTP transport.

`vaultspec-rag server service start` spawns a background HTTP daemon. The default port is 8766; override it with `--port` or the `VAULTSPEC_RAG_PORT` env var.

The daemon is multi-tenant by design. It starts with no baked-in project root. The spawn process strips `VAULTSPEC_RAG_ROOT` from the daemon's environment so it cannot leak across projects. Every MCP tool call must carry an explicit `project_root`. See [MCP integration](#mcp-integration) for the client contract.

On startup, the daemon eagerly loads GPU models and polls `/health` until ready. It writes a status file to `~/.vaultspec-rag/service.json` containing the PID, port, and start time.

Stop the daemon with `vaultspec-rag server service stop`. This sends `SIGTERM` on Unix or `CTRL_BREAK_EVENT` on Windows, waits two seconds, then force-kills the process if needed.

### Health endpoint

The HTTP service exposes a `/health` endpoint returning JSON:

- `status` -- `ready` (models loaded), `degraded` (started but models failed), or `error` (not started)
- `cuda` -- boolean indicating GPU availability
- `models_loaded` -- boolean indicating whether all three models initialized
- `project_count` -- number of registered project slots
- `uptime_s` -- seconds since startup
- `backend_capabilities` -- backend name, search concurrency contract, cross-project strategy, and storage process model

Check health from the CLI with `vaultspec-rag server service status`.

### Model warmup

`vaultspec-rag server service warmup` pre-downloads the three model weights (dense, sparse, reranker) to the local HuggingFace cache. Run this before first use to avoid cold-start delays on the initial server launch.

The command respects `HF_HOME` and `HF_HUB_DOWNLOAD_TIMEOUT` env vars.

### Project slot eviction

The daemon bounds its in-memory per-project state in two dimensions. Each reachable workspace root occupies one `ProjectSlot` (Qdrant store, indexers, searcher, graph cache, watcher). Slots are admitted lazily on first traffic and evicted in two ways:

- **Idle TTL.** A slot with `ref_count == 0` that has not been accessed for at least `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS` (default 1800, i.e. 30 minutes) is evicted opportunistically the next time any request touches the registry. Set the env var to `0` to disable.
- **LRU cap.** At most `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS` slots (default 16) live concurrently. Admitting a new slot at the cap evicts the least-recently-accessed idle slot. If every slot is busy, the MCP tool returns a structured `{"ok": false, "error": "registry_full", "busy_projects": [...]}` response and the caller should retry. Set to `0` to disable.

Inspect and evict slots via `vaultspec-rag server service projects list` and `vaultspec-rag server service projects evict <root>`. The `list` command renders a Rich table (`Root`, `Idle`, `Refs`, `Last access`) plus a footer summarizing `{used}/{max}` slots and the idle TTL. The `evict` command exits `0` on success, `1` if the slot is busy, `2` if the root is unknown, and `3` if the service is unreachable. Both commands accept `--port` to target a specific daemon.

### Log rotation

The daemon installs a `DaemonRotatingFileHandler` on the root logger during `mcp_server.main()`. It wraps Python's `RotatingFileHandler` and, on every `doRollover`, re-`dup2`s file descriptors 1 and 2 onto the freshly opened stream so `print()`, uvicorn access logs, and any bare C-level writes land in the active log file instead of sticking to the rotated backup. Rotation thresholds come from `VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES` (default 10 MiB) and `VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT` (default 5). Setting `max_bytes=0` disables size-based rotation while still installing the handler.

## Indexing

Index vault documents (markdown in `.vault/`) or codebase source files, or both.

- `vaultspec-rag index --type vault` indexes vault documents. One document maps to one index entry.
- `vaultspec-rag index --type code` indexes source files. Tree-sitter handles structural chunking when grammars are available; text splitting serves as the fallback. Supported languages include Python, Rust, TypeScript, JavaScript, Go, Java, C/C++, C#, Ruby, and Kotlin.
- `vaultspec-rag index` (default `--type all`) indexes both.
- `--rebuild` drops the selected collection before re-indexing. It requires
  an explicit `--type` (`vault`, `code`, or `all`). `--rebuild --type vault`
  and `--rebuild --type code` leave the sibling collection intact.
- Use `vaultspec-rag clean {vault|code|all} --yes` to drop and recreate selected Qdrant collections and clear matching metadata sidecars without loading embeddings, scanning files, or indexing. The target is **required** (no default) since 0.2.9 to prevent accidental full wipes; without `--yes`/`-y`, `clean` still prompts for confirmation.
- Incremental indexing (the default) uses blake2b content hashing to detect changes.
- `--dry-run` lists files that would be indexed without writing anything (codebase only).

## Searching

- `vaultspec-rag search "query" --type vault` searches vault documents (default). Filters: `--doc-type`, `--feature`, `--date`, `--tag`. (`--type` is the source switch and cannot be reused for the vault doc-type filter; `--doc-type` mirrors `--node-type`.)
- `vaultspec-rag search "query" --type code` searches source code. Filters: `--language`, `--path` (exact KEYWORD), `--include-path PATTERN` and `--exclude-path PATTERN` (both repeatable, fnmatch glob, post-query), `--node-type`, `--function-name`, `--class-name`. Path globs operate against the POSIX-normalised project-relative path; the indexer normalises separators at write time on every platform, so `'src/**'` works the same on Windows and POSIX. When either glob is supplied, the over-fetch ceiling rises (10x top-k) to compensate for aggressive exclusion.
- Embed filters directly in the query string with tokens: `type:adr`, `feature:auth`, `lang:python`, `path:src/foo.py`, `func:main`, `class:Engine`, `date:2026-03`, `nodetype:function_definition`, `tag:auth`. Tokens and flags are interchangeable for the same underlying filter; flags are the documented surface.
- Default `--max-results` is 10 (raised from 5 to mitigate top-k crowding).
- `--no-truncate` disables the 120-character snippet truncation in the results table so sibling files with long paths stay distinguishable.
- The results-table title is suffixed `(via MCP)` when the fast path answered or `(via in-process)` when the local fallback did, so the execution path is never ambiguous.
- Results include score, file path, snippet, and (for code) line numbers and AST metadata.

### --port fast path (recommended for concurrent agents)

- Pass `--port <N>` to delegate the call to a running RAG service (see `vaultspec-rag server service start`). The service owns the Qdrant lock and shares GPU warm-up across callers; the fast path is the safe path.
- If the service is unreachable on the given port, the CLI hard-fails
  with remediation instead of silently spawning a local model load and
  grabbing the Qdrant lock. Opt back into in-process execution with
  `--allow-fallback` (single-agent use only).
- Pass `--verbose` to re-enable HuggingFace tqdm progress bars during in-process model load / encode. Off by default so the results table stays script-friendly.

### `--json` output mode

Every command supports `--json` and emits exactly one envelope document on stdout. The envelope is

```
{"ok": true,  "command": "<name>", "data": <payload>}
{"ok": false, "command": "<name>", "error": "<code>", "message": "<prose>"}
```

so consumers branch on `ok` first, then on `command` / `error`. Exit codes match the table-mode contract (`0` success, `1`/`2`/`3`/`4` per command). Payload shapes mirror the MCP Pydantic models where they exist (`SearchResultItem`, `IndexResponse`, `IndexStatus`, `HealthResponse`, `BackendCapabilities`).

```bash
vaultspec-rag status --json | jq '.data.vault_documents'
vaultspec-rag search "auth handler" --type code --json \
  | jq '.data.results[0].path'
vaultspec-rag index --type code --port 8766 --json \
  | jq '.data.sources[] | select(.source == "codebase")'
vaultspec-rag server service status --json | jq '.data.state'
```

`vaultspec-rag clean ... --json` requires `--yes` (the interactive confirm would corrupt stdin). HuggingFace tqdm bars and Rich status spinners are suppressed automatically when `--json` is set, so the stream stays pure JSON.

### Service lifecycle (`vaultspec-rag server service status`)

`status` gathers every signal before rendering - `service.json` present, PID alive, port listening, heartbeat fresh - and reports each as its own row plus a derived `State`. The previous "pick one source of truth" verdict could mislead when signals disagreed; this version surfaces the divergence. Exit codes:

- `0` — `running` (all signals green).
- `3` — `stopped` (no `service.json`).
- `4` — `crashed (PID dead)` / `crashed (port silent)` / `crashed (heartbeat stale)` / `crashed (PID reused)`. Scripts can branch on `4` for "known-bad state" without parsing the prose.

The daemon writes `last_heartbeat` into `service.json` every 15 seconds (atomic rewrite). The CLI flags the file stale when the age exceeds 60 seconds — long enough to tolerate three missed beats, short enough to catch a SIGKILL'd daemon before the next `--port` call lands in unsafe fallback territory. Daemon shutdown — clean stop, SIGTERM, SIGINT, atexit — unlinks the file and logs a structured `service.lifecycle event=shutdown reason=...` entry at WARNING level so the line is visible at the default log threshold.

## MCP integration

The MCP server exposes eight tools:

| Tool               | Purpose                                                                                                                                                                           |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `search_vault`     | Search vault documents. Filters: `doc_type`, `feature`, `date`, `tag` (all KEYWORD exact)                                                                                         |
| `search_codebase`  | Search source code. Filters: `language`, `path`, `node_type`, `function_name`, `class_name` (KEYWORD exact), plus `include_paths`/`exclude_paths` (list[str], fnmatch post-query) |
| `reindex_vault`    | Re-index vault (incremental or clean)                                                                                                                                             |
| `reindex_codebase` | Re-index codebase (incremental or clean)                                                                                                                                          |
| `get_index_status` | Return index stats and GPU status                                                                                                                                                 |
| `get_code_file`    | Retrieve full source file content                                                                                                                                                 |
| `list_projects`    | Enumerate projects warm in the registry                                                                                                                                           |
| `evict_project`    | Drop a project's models + Qdrant lock from the registry                                                                                                                           |

The server runs in one of two transport modes, and the rules for the `project_root` parameter differ between them.

### stdio mode (single-project)

The MCP client launches `vaultspec-search-mcp` as a subprocess, one process per project. The server reads `VAULTSPEC_RAG_ROOT` from its environment, falling back to its current working directory.

- `project_root` is **optional** on every tool call. Omit it to use the env var or cwd.
- The `vault://{doc_id}` resource returns full document content.
- Suitable for Claude Desktop, Claude Code, or any client that spawns one MCP server per workspace.

Local storage remains process-exclusive. Use one stdio process per
project root; route concurrent clients for the same project through
HTTP mode.

Configure a Claude Desktop client like this:

```json
{
  "mcpServers": {
    "vaultspec-rag": {
      "command": "vaultspec-search-mcp",
      "env": {
        "VAULTSPEC_RAG_ROOT": "/path/to/your/project"
      }
    }
  }
}
```

### HTTP mode (multi-project)

The server runs as a persistent daemon at `http://127.0.0.1:{port}/mcp` and serves multiple projects concurrently. The daemon starts with **no default project** -- `VAULTSPEC_RAG_ROOT` is stripped from its environment at spawn time.

- `project_root` is **required** on every tool call. Omitting it raises `ValueError: project_root is required in HTTP service mode -- the multi-tenant service has no default project`.
- The `vault://{doc_id}` resource is **not available** -- use `search_vault` or `get_code_file` with an explicit `project_root` instead.
- Suitable for shared services across multiple workspaces or CI environments.

HTTP mode has no default project. Every tool call must include
`project_root`; stdio mode is the only transport that falls back to
`VAULTSPEC_RAG_ROOT` or cwd.

Start the daemon and connect a client:

```sh
vaultspec-rag server service start --port 8766
```

Then point your MCP client at `http://127.0.0.1:8766/mcp` and pass `project_root` (an absolute path to a directory containing `.vault/`) on each tool invocation.

### Choosing a mode

Use stdio for desktop AI tools that work in one project at a time. The simpler config matches how those tools operate. Use HTTP to handle several projects from one service, or to share one GPU-loaded daemon across CLI and AI clients.

See [Service management](#service-management) for daemon lifecycle details.

## Python API

The `vaultspec_rag` package exports a facade in `vaultspec_rag.api`:

| Function                                                                                                                                                              | Purpose                                           |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `index(root_dir, *, full=False)`                                                                                                                                      | Index vault documents                             |
| `index_codebase(root_dir, *, full=False)`                                                                                                                             | Index source files                                |
| `search_vault(root_dir, query, *, top_k=5, doc_type=None, feature=None, date=None, tag=None)`                                                                         | Search vault                                      |
| `search_codebase(root_dir, query, *, top_k=5, language=None, path=None, node_type=None, function_name=None, class_name=None, include_paths=None, exclude_paths=None)` | Search code                                       |
| `list_documents(root_dir, doc_type=None)`                                                                                                                             | List indexed documents                            |
| `get_related(root_dir, doc_id)`                                                                                                                                       | Get graph relationships (outgoing/incoming links) |

All functions accept a `root_dir: Path` and manage a thread-safe singleton engine internally. The engine loads GPU models on first call.

## Models

| Component         | Model                                                                         | Role                                             |
| ----------------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| Dense embeddings  | [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | 1024-dimensional semantic vectors                |
| Sparse embeddings | [naver/splade-v3](https://huggingface.co/naver/splade-v3)                     | Learned term-weight vectors for keyword matching |
| Reranker          | [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)     | Cross-encoder rescoring with sigmoid activation  |
| Vector storage    | [Qdrant](https://qdrant.tech/documentation/) (local mode)                     | Hybrid dense + sparse search with RRF fusion     |

Qdrant's universal query API searches dense and sparse vectors together using reciprocal rank fusion. The reranker optionally rescores top candidates for improved precision.

## See also

- [Project background](../../README.md)
- [vaultspec-core](https://github.com/wgergely/vaultspec-core) -- the spec-driven development framework
- [MCP specification](https://modelcontextprotocol.io)
- [Qdrant documentation](https://qdrant.tech/documentation/)
- Model cards: [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [splade-v3](https://huggingface.co/naver/splade-v3), [bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- [GitHub issues](https://github.com/wgergely/vaultspec-rag/issues)
