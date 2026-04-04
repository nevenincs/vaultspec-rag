# vaultspec-rag

vaultspec-rag is a GPU-native retrieval-augmented generation (RAG) pipeline. It
searches vault documents and project source code using hybrid dense and sparse
embeddings with graph-aware reranking.

A "vault" is the `.vault/` directory of structured markdown documents managed by
[vaultspec-core](https://github.com/wgergely/vaultspec-core). The embedding
stack combines
[Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B),
[SPLADE v3](https://huggingface.co/naver/splade-v3),
[Qdrant](https://qdrant.tech/), and
[bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3).

> See the [project README](../README.md) for an introduction.

## Installation

Install with [uv](https://docs.astral.sh/uv/):

```sh
uv add vaultspec-rag
```

vaultspec-rag requires a CUDA GPU with at least 3 GB VRAM. Qwen3 uses ~1.5 GB
and SPLADE ~0.5 GB in fp16. The reranker loads lazily on first use. vaultspec-rag
raises a `RuntimeError` if no CUDA device is available. PyTorch installs from
the cu130 index at `pytorch.org/whl/cu130`.

Dependencies:

- Python >= 3.13
- vaultspec-core >= 0.1.0
- Optional: flash-attn >= 2.5 for flash attention 2 acceleration

Verify your installation:

```sh
vaultspec-rag status
```

This prints GPU device details and storage paths. Run the test suite with:

```sh
vaultspec-rag test
```

Tests exercise real GPU inference and real Qdrant — no mocks.

## Two indexing modes

vaultspec-rag maintains two separate search collections:

- **Vault** — indexes `.vault/` markdown documents (ADRs, plans, research,
  references, audit reports). Parses YAML frontmatter for metadata filters like
  `type:`, `feature:`, and `date:`. Uses the vault's wiki-link graph for
  relationship-aware reranking.
- **Codebase** — indexes project source files across 16+ languages. Uses
  tree-sitter for structure-aware chunking that preserves function and class
  boundaries. Supports filters like `lang:`, `func:`, and `class:`.

Each mode has its own Qdrant collection, indexing pipeline, and filter set. You
can index and search them independently or together.

The codebase indexer respects `.gitignore` files and applies hardcoded
exclusions (`.venv/`, `.git/`, `node_modules/`, `__pycache__/`, `.qdrant/`).
Files are also filtered by supported language extensions and a 10 MB size limit.

## Quickstart

Index vault documents and search:

```sh
vaultspec-rag index --type vault
vaultspec-rag search "architecture decision"
```

Index source code and search:

```sh
vaultspec-rag index --type code
vaultspec-rag search --type code "lang:python error handling"
```

Index both at once:

```sh
vaultspec-rag index
```

Results appear as a table with Score, Location, and Snippet columns.

## CLI usage

Run `vaultspec-rag` directly or via `uv run vaultspec-rag` in uv-managed
environments.

### Global options

```text
--target, -t PATH    Set the project root directory
--verbose, -v        Enable verbose output
--debug, -d          Enable debug logging
--version, -V        Show version and exit
```

### Primary commands

#### search

Run a semantic hybrid search across vault documents, codebase, or both.

```bash
vaultspec-rag search "query string"
vaultspec-rag search --type code --max-results 10 "function signature"
vaultspec-rag search --port 8766 "delegated query"
```

| Option                    | Description                                |
| :------------------------ | :----------------------------------------- |
| `--type {vault,code,all}` | Search scope (default: `vault`)            |
| `--max-results N`         | Number of results to return (default: `5`) |
| `--language`              | Filter by programming language             |
| `--node-type`             | Filter by syntax tree node type            |
| `--function-name`         | Filter by function name                    |
| `--class-name`            | Filter by class name                       |
| `--port PORT`             | Delegate the query to a running MCP server |

Embed filters directly in the query string instead of using flags:

```text
type:adr feature:editor date:2026-03 tag:research
lang:python path:src/ func:reindex class:VaultStore nodetype:function
```

Output is a table with Score, Location, and Snippet columns. When you pass
`--port`, the CLI connects to the MCP server and skips local model loading.

#### index

Index vault documents, source files, or both.

```bash
vaultspec-rag index
vaultspec-rag index --type vault --clean
vaultspec-rag index --port 8766
```

| Option                    | Description                                        |
| :------------------------ | :------------------------------------------------- |
| `--type {vault,code,all}` | Index scope (default: `all`)                       |
| `--clean`                 | Drop existing collections and rebuild from scratch |
| `--port PORT`             | Delegate indexing to a running MCP server          |

Output is a summary table with Added, Updated, Removed, and Total counts plus
elapsed duration.

#### status

Display GPU device details, storage path, and document counts for each
collection.

```bash
vaultspec-rag status
```

#### benchmark

Profile search latency across a batch of queries.

```bash
vaultspec-rag benchmark
vaultspec-rag benchmark --n-queries 50
```

Reports p50, p95, and p99 latencies. Default sample size is 20 queries.

#### test

Run the pytest suite. All extra arguments are forwarded to pytest.

```bash
vaultspec-rag test
vaultspec-rag test -k "test_search" --tb=short
```

### Server commands

#### server mcp start

Start the MCP server. Pass `--port` for HTTP transport; omit it for stdio mode.

```bash
vaultspec-rag server mcp start
vaultspec-rag server mcp start --port 8766
```

The server inherits the project root from `--target` via the `VAULTSPEC_ROOT`
environment variable.

#### server mcp stop

Print instructions for stopping the MCP server process.

```bash
vaultspec-rag server mcp stop
```

#### server mcp status

Show the MCP server configuration, including registered tools, resources, and
prompts.

```bash
vaultspec-rag server mcp status
```

#### server service start

Start a detached background service with health-check polling.

```bash
vaultspec-rag server service start
vaultspec-rag server service start --port 9000
```

| Option        | Description                                            |
| :------------ | :----------------------------------------------------- |
| `--port PORT` | HTTP port (default: `8766`, env: `VAULTSPEC_RAG_PORT`) |

The service acquires a port mutex and checks for stale PIDs. It polls `/health`
with exponential backoff and writes runtime state to
`~/.vaultspec-rag/service.json`.

#### server service stop

Stop the background service. Sends SIGTERM first, then force-kills if the
process does not exit.

```bash
vaultspec-rag server service stop
```

#### server service status

Show runtime state: PID, port, health endpoint response, and uptime.

```bash
vaultspec-rag server service status
```

#### server service warmup

Pre-download GPU models to the local HuggingFace cache without starting the
server.

```bash
vaultspec-rag server service warmup
```

## MCP integration

vaultspec-rag exposes a Model Context Protocol (MCP) server that gives Claude
access to vault and codebase search.

### Starting the server

vaultspec-rag provides two entry points:

- `vaultspec-search-mcp` — installed script, stdio mode by default
- `vaultspec-rag server mcp start` — CLI subcommand

Set `VAULTSPEC_ROOT` to point the server at your project root.

**Stdio mode** (default) connects directly to Claude Desktop or claude-code.
**HTTP mode** (`--port`) runs a Starlette app with MCP transport at `/mcp` and a
health check at `/health`. HTTP mode eagerly loads GPU models before accepting
connections and serializes GPU access with an asyncio semaphore.

### Claude Desktop configuration

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vaultspec-rag": {
      "command": "vaultspec-search-mcp",
      "env": {
        "VAULTSPEC_ROOT": "/path/to/your/project"
      }
    }
  }
}
```

For a persistent server, start in HTTP mode and configure the client to connect
to `http://localhost:<port>/mcp`.

### Available tools

| Tool               | Description                              |
| :----------------- | :--------------------------------------- |
| `search_vault`     | Search vault documents by query          |
| `search_codebase`  | Search source code with optional filters |
| `search_all`       | Search vault and codebase combined       |
| `get_index_status` | Return indexing statistics               |
| `get_code_file`    | Retrieve a source file by path           |
| `reindex_vault`    | Rebuild the vault index                  |
| `reindex_codebase` | Rebuild the codebase index               |

All tools accept an optional `project_root` parameter that overrides
`VAULTSPEC_ROOT`.

The server also exposes a `vault://{doc_id}` resource for retrieving full vault
documents by stem ID and an `analyze_feature(feature_name)` prompt for
multi-step feature analysis.

## Python API

The `vaultspec_rag.api` module provides a thread-safe facade over the indexing
and search engine. A singleton engine per project root is managed by
`get_engine(root_dir)` with a `threading.Lock`.

### Example

```python
from pathlib import Path
from vaultspec_rag.api import index, search_vault

root = Path("/path/to/project")
index(root)  # incremental by default; pass full=True to rebuild

results = search_vault(root, "authentication flow", top_k=3)
for r in results:
    print(f"{r.id} ({r.score:.2f}): {r.title}")
```

### Function reference

Signatures use Python type hints.

```text
index(root_dir, *, full=False) -> IndexResult
index_codebase(root_dir, *, full=False) -> IndexResult
search_vault(root_dir, query, *, top_k=5) -> list[SearchResult]
search_codebase(root_dir, query, *, top_k=5, ...) -> list[SearchResult]
search_all(root_dir, query, *, top_k=5) -> list[SearchResult]
list_documents(root_dir, doc_type=None) -> list[dict[str, object]]
get_related(root_dir, doc_id) -> dict[str, object] | None
reset_engine() -> None
```

- `index` and `index_codebase` perform incremental updates by default. Pass
  `full=True` to rebuild from scratch.
- `search_codebase` accepts optional filters for `language`, `node_type`,
  `function_name`, and `class_name`.
- Call `reset_engine` only in tests — it tears down the cached engine.

## Search query syntax

Prefix any query with structured filters to narrow results. The engine strips
recognized prefixes before encoding the remaining text for semantic search.

### Filter reference

| Prefix      | Field                                                       | Applies to |
| :---------- | :---------------------------------------------------------- | :--------- |
| `type:`     | Document type (adr, plan, research, reference, audit, exec) | Vault      |
| `feature:`  | Feature name                                                | Vault      |
| `date:`     | ISO date prefix (e.g., `2026-03`)                           | Vault      |
| `tag:`      | Tag value (`#` prefix stripped automatically)               | Vault      |
| `lang:`     | Programming language                                        | Codebase   |
| `path:`     | File path substring                                         | Codebase   |
| `func:`     | Function name                                               | Codebase   |
| `class:`    | Class name                                                  | Codebase   |
| `nodetype:` | AST node type                                               | Codebase   |

### Examples

Find architecture decision records about authentication:

```text
type:adr authentication flow
```

Search Python code in the pipeline feature for executor logic:

```text
feature:pipeline lang:python executor
```

Locate a specific function within a class:

```text
func:execute class:Pipeline
```

Find vault documents from a specific month:

```text
date:2026-03 migration strategy
```

## Configuration

`VaultSpecConfigWrapper` layers RAG-specific defaults on top of the base
vaultspec-core configuration.

| Key                    | Default                     | Description        |
| :--------------------- | :-------------------------- | :----------------- |
| `qdrant_dir`           | `.qdrant`                   | Storage directory  |
| `embedding_model`      | `Qwen/Qwen3-Embedding-0.6B` | Dense model        |
| `embedding_dimension`  | `1024`                      | Dense vector size  |
| `sparse_model`         | `naver/splade-v3`           | Sparse model       |
| `reranker_enabled`     | `True`                      | Enable reranking   |
| `reranker_model`       | `BAAI/bge-reranker-v2-m3`   | Reranker model     |
| `embedding_batch_size` | `64`                        | Docs per batch     |
| `max_embed_chars`      | `8000`                      | Max chars to embed |
| `reranker_batch_size`  | `32`                        | Pairs per batch    |
| `graph_ttl_seconds`    | `300.0`                     | Graph cache TTL    |
| `index_metadata_file`  | `index_meta.json`           | Hash store file    |

Override any key by passing a dict to `get_config(overrides={...})` or by
setting values through the vaultspec-core config system.

## Architecture

### Embedding stack

Three GPU-resident models handle dense retrieval, sparse retrieval, and
reranking.

**Qwen3-Embedding-0.6B** produces 1024-dimensional dense vectors in fp16 with
optional flash attention 2. Queries use `prompt_name="query"` for
instruction-following; documents omit the prompt. Requires ~1.5 GB VRAM. See the
[model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B).

**SPLADE v3** (Sparse Lexical and Expansion) produces sparse vectors through
`SparseEncoder`. Encoding is asymmetric: `encode_query()` and
`encode_document()` apply different internal prompts. Requires ~0.5 GB VRAM. See
the [model card](https://huggingface.co/naver/splade-v3).

**bge-reranker-v2-m3** scores query-document pairs via `CrossEncoder` with
sigmoid activation, producing calibrated scores in [0, 1]. Loaded lazily on
first use. Requires ~0.56 GB VRAM. Batch size starts at 32 and halves on OOM.
See the [model card](https://huggingface.co/BAAI/bge-reranker-v2-m3).

### Search flow

1. `parse_query()` extracts filters and clean text from the raw query string.
1. `_encode_query()` produces a dense vector (1024d) and a sparse vector
   (SPLADE). The query is encoded once and reused across collections.
1. `store.hybrid_search()` dispatches dual `Prefetch` operations to Qdrant:
   dense (`limit * 4`) and sparse (`limit * 4`), each with filters applied at
   the prefetch level.
1. Reciprocal Rank Fusion (RRF) with `k=60` merges the two result sets using
   the formula `1 / (k + rank)`.
1. CrossEncoder reranking scores each query-snippet pair through sigmoid
   activation, yielding a [0, 1] confidence score.
1. Graph-aware reranking applies two boosts. The in-link boost:
   `score *= 1 + 0.1 * min(in_links, 10)`. The feature-neighbor boost:
   `score *= 1.15`.
1. `search_all()` encodes once, searches both vault and codebase collections,
   applies min-max normalization to each result set, and merges by score.

### Indexing flow

**Vault indexer.** `VaultIndexer` scans `.vault/`, parses YAML frontmatter via
`prepare_document()`, and extracts `doc_type`, `feature`, `tags`, `related`, and
`title`. Each document ID is the relative path without extension (e.g.,
`adr/overview`). `blake2b` file hashes enable incremental change detection.
Metadata writes are atomic: write to `.tmp`, then `os.replace`.

**Codebase indexer.** `CodebaseIndexer` walks the project tree with `os.walk`,
pruning paths matched by `.gitignore`. It skips binary files (null byte in first
8 KB) and files larger than 10 MB. `ASTChunker` uses tree-sitter for
language-aware splitting across 16+ languages; `TextSplitter` handles the rest.
Chunk IDs follow the pattern `{path}:{line_start}-{line_end}:{blake2b_6bytes}`.

**Full vs. incremental.** `full_index(clean=True)` drops and recreates the
Qdrant collection. Incremental indexing compares `blake2b` hashes against the
stored metadata and re-embeds only changed files.

### Service layer

`ServiceRegistry` holds one shared `EmbeddingModel` and one shared
`CrossEncoder` reranker across all projects, since loading GPU models
takes several seconds and ~2 GB VRAM. Each project gets a `ProjectSlot`
keyed by resolved `Path`, containing a `VaultStore`, `VaultSearcher`,
`VaultIndexer`, `CodebaseIndexer`, and `GraphCache`.

A global `gpu_lock` serializes GPU-bound operations (encoding and
reranking) across concurrent requests. Each project root also gets its
own lock so that indexing one project does not block searches on another.

The registry manages filesystem watcher lifecycle through an
`_on_close_project` callback and a `_shutting_down` guard that prevents
new slots from being created during shutdown.

`GraphCache` uses TTL-based expiry (300 seconds by default) and is
invalidated immediately after a vault reindex.

## Getting help

Report bugs and request features on the
[GitHub issue tracker](https://github.com/wgergely/vaultspec-rag/issues).
