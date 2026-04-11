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

`index` builds embeddings for both vault documents and source code. `search` queries the vault by default, returning the top 5 results as a table with Score, Location, and Snippet columns.

## Usage modes

vaultspec-rag operates in two modes: **ad-hoc** and **service**.

**Ad-hoc mode** runs everything in-process. Each CLI command loads the GPU models, performs the operation, and exits. This is the default -- no setup beyond installation is needed. The tradeoff is that loading models takes several seconds per invocation.

```sh
vaultspec-rag index
vaultspec-rag search "your query"
```

**Service mode** runs a persistent background daemon that keeps models loaded in VRAM. CLI commands delegate to the service via `--port`, avoiding repeated model loading. The service also watches for file changes and reindexes automatically.

Start the service, then use `--port` on CLI commands:

```sh
vaultspec-rag server service start
vaultspec-rag search --port 8766 "your query"
vaultspec-rag index --port 8766
```

Ad-hoc mode suits one-off tasks or environments where a persistent process isn't practical. Service mode suits active development where you search frequently and want the index to stay current as files change.

## Architecture overview

### Access layers

Three interfaces expose the same underlying engine: the CLI (`vaultspec-rag`), the MCP server (`vaultspec-search-mcp`), and the Python API (`vaultspec_rag.api`).

The CLI runs indexing and search in-process by default. Pass `--port` to delegate to a running MCP service over HTTP. If the service is unreachable, the CLI falls back to in-process execution.

The MCP server wraps the engine behind tool endpoints, accepting connections from any MCP-compatible client. The Python API is the underlying facade -- call `index()`, `search_vault()`, and `search_codebase()` directly.

### GPU model lifecycle

A single shared `EmbeddingModel` loads three models into VRAM once at initialization:

- **Dense encoder** -- `Qwen/Qwen3-Embedding-0.6B` (1024-dimensional vectors, fp16)
- **Sparse encoder** -- `naver/splade-v3` (asymmetric SPLADE with separate query and document encoding)
- **Reranker** -- `BAAI/bge-reranker-v2-m3` (CrossEncoder with sigmoid activation, loaded lazily on first use)

A shared lock serializes GPU operations. CUDA is mandatory -- the system raises `RuntimeError` if no GPU is available.

### Multi-project support

The MCP service manages isolated per-project slots. Each slot contains its own Qdrant store, indexers, searcher, and relationship graph cache. All slots share the single `EmbeddingModel` instance.

MCP tools accept a `project_root` parameter to target a specific project. Different projects initialize in parallel under per-root locks.

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
        ├── status     Show daemon health and connected projects
        └── warmup     Pre-download model weights to HuggingFace cache
```

**Global options:** `--target` / `-t` sets the workspace root. `--verbose` / `-v` and `--debug` / `-d` control log verbosity. `--version` / `-V` prints the installed version.

**Config overrides:** `--data-dir`, `--qdrant-dir`, `--index-meta`, `--code-index-meta`, `--status-dir`, and `--log-file` override the default storage paths.

### The `--port` fast path

The `index` and `search` commands accept a `--port` flag. When set, the CLI delegates to a running MCP service over HTTP instead of loading GPU models in-process. If the service is unavailable, the CLI falls back to in-process operation with a warning.

Loading the embedding models takes several seconds on a cold start. Point `--port` at a running `server service` instance to skip that overhead entirely.

## Configuration

### Precedence

Configuration resolves through three tiers: CLI flags override environment variables, which override built-in defaults. Boolean env vars accept `1`, `true`, or `yes` (case-insensitive). The system parses integer and float values from strings.

### Environment variables

| Variable                        | Default                   | Description                                       |
| ------------------------------- | ------------------------- | ------------------------------------------------- |
| `VAULTSPEC_RAG_ROOT`            | cwd                       | Project root directory                            |
| `VAULTSPEC_RAG_DATA_DIR`        | `.vault/data/search-data` | Search data directory                             |
| `VAULTSPEC_RAG_QDRANT_DIR`      | `qdrant`                  | Qdrant storage subdirectory, relative to data dir |
| `VAULTSPEC_RAG_INDEX_META`      | `index_meta.json`         | Vault index metadata filename                     |
| `VAULTSPEC_RAG_CODE_INDEX_META` | `code_index_meta.json`    | Codebase index metadata filename                  |
| `VAULTSPEC_RAG_STATUS_DIR`      | `~/.vaultspec-rag`        | Service status and log directory                  |
| `VAULTSPEC_RAG_LOG_FILE`        | `service.log`             | Log filename, relative to status dir              |
| `VAULTSPEC_RAG_PORT`            | `8766`                    | MCP HTTP server port                              |
| `VAULTSPEC_RAG_LOG_LEVEL`       | `WARNING`                 | Logging level                                     |

The tool also respects two third-party environment variables. Set `HF_HOME` to control where HuggingFace caches downloaded models. Set `HF_HUB_DOWNLOAD_TIMEOUT` to increase the model download timeout.

### `.vaultragignore`

Place a `.vaultragignore` file at the project root to exclude files from codebase indexing. It uses gitignore syntax via `pathspec`. Patterns merge with CLI `--exclude` flags.

This file operates independently from `.gitignore` -- both apply with OR logic. The indexer skips any file excluded by either spec.

## Service management

### Foreground vs. background

`vaultspec-rag server mcp start` runs the MCP server in the foreground over stdio transport, suitable for direct LLM integration. Pass `--port` to switch to HTTP transport.

`vaultspec-rag server service start` spawns a background HTTP daemon. The default port is 8766; override it with `--port` or the `VAULTSPEC_RAG_PORT` env var.

On startup, the daemon eagerly loads GPU models and polls `/health` until ready. It writes a status file to `~/.vaultspec-rag/service.json` containing the PID, port, and start time.

Stop the daemon with `vaultspec-rag server service stop`. This sends `SIGTERM` on Unix or `CTRL_BREAK_EVENT` on Windows, waits two seconds, then force-kills the process if needed.

### Health endpoint

The HTTP service exposes a `/health` endpoint returning JSON:

- `status` -- `ready` (models loaded), `degraded` (started but models failed), or `error` (not started)
- `cuda` -- boolean indicating GPU availability
- `models_loaded` -- boolean indicating whether all three models initialized
- `project_count` -- number of connected projects
- `uptime_s` -- seconds since startup

Check health from the CLI with `vaultspec-rag server service status`.

### Model warmup

`vaultspec-rag server service warmup` pre-downloads the three model weights (dense, sparse, reranker) to the local HuggingFace cache. Run this before first use to avoid cold-start delays on the initial server launch.

The command respects `HF_HOME` and `HF_HUB_DOWNLOAD_TIMEOUT` env vars.

## Indexing

Index vault documents (markdown in `.vault/`) or codebase source files, or both.

- `vaultspec-rag index --type vault` indexes vault documents. One document maps to one index entry.
- `vaultspec-rag index --type code` indexes source files. Tree-sitter handles structural chunking when grammars are available; text splitting serves as the fallback. Supported languages include Python, Rust, TypeScript, JavaScript, Go, Java, C/C++, C#, Ruby, and Kotlin.
- `vaultspec-rag index` (default `--type all`) indexes both.
- Add `--clean` to drop and recreate the index from scratch.
- Incremental indexing (the default) uses blake2b content hashing to detect changes.
- `--dry-run` lists files that would be indexed without writing anything (codebase only).

## Searching

- `vaultspec-rag search "query" --type vault` searches vault documents (default).
- `vaultspec-rag search "query" --type code` searches source code. Filters: `--language`, `--node-type`, `--function-name`, `--class-name`.
- Embed filters directly in the query string with tokens: `type:adr`, `feature:auth`, `lang:python`, `func:main`, `class:Engine`, `date:2026-03`.
- Results include score, file path, snippet, and (for code) line numbers and AST metadata.

## MCP integration

The MCP server exposes six tools:

| Tool               | Purpose                                  |
| ------------------ | ---------------------------------------- |
| `search_vault`     | Search vault documents                   |
| `search_codebase`  | Search source code with optional filters |
| `reindex_vault`    | Re-index vault (incremental or clean)    |
| `reindex_codebase` | Re-index codebase (incremental or clean) |
| `get_index_status` | Return index stats and GPU status        |
| `get_code_file`    | Retrieve full source file content        |

All tools accept an optional `project_root` parameter for multi-project use.

The server also exposes a `vault://{doc_id}` resource for retrieving vault document content, and an `analyze_feature` prompt.

**Connecting a client.** For stdio, configure the MCP client to run `vaultspec-search-mcp`. For HTTP, point to `http://127.0.0.1:{port}/mcp`.

## Python API

The `vaultspec_rag` package exports a facade in `vaultspec_rag.api`:

| Function                                                           | Purpose                                           |
| ------------------------------------------------------------------ | ------------------------------------------------- |
| `index(root_dir, *, full=False)`                                   | Index vault documents                             |
| `index_codebase(root_dir, *, full=False)`                          | Index source files                                |
| `search_vault(root_dir, query, *, top_k=5)`                        | Search vault                                      |
| `search_codebase(root_dir, query, *, top_k=5, language=None, ...)` | Search code                                       |
| `list_documents(root_dir, doc_type=None)`                          | List indexed documents                            |
| `get_related(root_dir, doc_id)`                                    | Get graph relationships (outgoing/incoming links) |

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
