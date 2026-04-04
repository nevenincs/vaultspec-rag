# vaultspec-rag

[![Python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](./pyproject.toml) [![CI](https://github.com/wgergely/vaultspec-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/wgergely/vaultspec-rag/actions/workflows/ci.yml) [![MCP](https://img.shields.io/badge/MCP-vaultspec--search--mcp-informational)](./src/vaultspec_rag/README.md#mcp-integration) [![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv) [![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

______________________________________________________________________

## Semantic search for your vaultspec vault and project codebase

vaultspec-rag adds GPU-accelerated search to projects managed by
[vaultspec-core](https://github.com/wgergely/vaultspec-core). It
indexes your `.vault/` documents — research notes, architecture
decisions, plans, execution logs — alongside your source code, and
lets you search across both with a single query. Runs locally on
your GPU and integrates with Claude through the Model Context
Protocol (MCP).

______________________________________________________________________

## Features

- Hybrid search combining dense and sparse embeddings with
  rank fusion
- Two indexing modes: vault documents and project source code
- Structure-aware code chunking across 16+ programming languages
- Graph-aware reranking using wiki-link relationships between
  vault documents
- Incremental indexing — only re-embeds changed files
- CLI, Python API, and MCP server interfaces
- Runs entirely on your local GPU — no external services

______________________________________________________________________

## Getting started

### Prerequisites

- Python 3.13 or later
- [uv](https://github.com/astral-sh/uv)
- A CUDA GPU with at least 3 GB VRAM (mandatory — no CPU
  fallback)
- [vaultspec-core](https://github.com/wgergely/vaultspec-core)

### Install

```bash
uv add vaultspec-rag
```

### Verify

```bash
vaultspec-rag status
```

### Index and search

Index vault documents and search across them:

```bash
vaultspec-rag index --type vault
vaultspec-rag search "architecture decision"
```

Index source code and search with language filters:

```bash
vaultspec-rag index --type code
vaultspec-rag search --type code "lang:python error handling"
```

Run `vaultspec-rag index` to index both at once.

______________________________________________________________________

## Using the MCP server

Two entry points: `vaultspec-search-mcp` (installed script) or
`vaultspec-rag server mcp start`.

Add the following to your Claude Desktop configuration for stdio
mode:

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

For HTTP mode, pass `--port`. See the
[package documentation](./src/vaultspec_rag/README.md#mcp-integration)
for the full tool reference and HTTP mode details.

______________________________________________________________________

## Further reading

| Guide                                                              | What it covers                         |
| ------------------------------------------------------------------ | -------------------------------------- |
| [CLI reference](./src/vaultspec_rag/README.md#cli-usage)           | Commands, flags, server subgroup       |
| [Python API](./src/vaultspec_rag/README.md#python-api)             | Facade functions and code examples     |
| [Search syntax](./src/vaultspec_rag/README.md#search-query-syntax) | Filter prefixes and query examples     |
| [Configuration](./src/vaultspec_rag/README.md#configuration)       | Defaults and overrides                 |
| [Architecture](./src/vaultspec_rag/README.md#architecture)         | Embedding stack, search flow, indexing |

______________________________________________________________________

## Getting help

Open an issue on
[GitHub](https://github.com/wgergely/vaultspec-rag/issues).

______________________________________________________________________

## Contributing and license

Contributions welcome — bug reports, feature ideas, or pull
requests. vaultspec-rag is released under the
[MIT License](./LICENSE).
