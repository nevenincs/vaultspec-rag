# vaultspec-rag

[![Python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](./pyproject.toml)
[![CI](https://github.com/wgergely/vaultspec-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/wgergely/vaultspec-rag/actions/workflows/ci.yml)
[![MCP](https://img.shields.io/badge/MCP-vaultspec--search--mcp-informational)](./src/vaultspec_rag/README.md#mcp-integration)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

______________________________________________________________________

## Semantic search for your vaultspec vault and project codebase

vaultspec-rag adds GPU-accelerated search to projects managed by [vaultspec-core](https://github.com/wgergely/vaultspec-core). It indexes your `.vault/` documents -- research notes, architecture decisions, plans, execution logs -- alongside your source code. Query both with natural language so your AI tools find relevant context on their own.

______________________________________________________________________

## Getting started

### Prerequisites

- Python 3.13 or later
- [uv](https://github.com/astral-sh/uv)
- A CUDA GPU with at least 3 GB VRAM (mandatory -- no CPU fallback)
- [vaultspec-core](https://github.com/wgergely/vaultspec-core)

### Install

```bash
uv add vaultspec-rag
```

This pulls in vaultspec-core and all GPU dependencies.

### Verify

```bash
vaultspec-rag --version
```

### Index and search

vaultspec-rag indexes two sources: **vault** (`.vault/` documents) and **code** (project source files).

```bash
vaultspec-rag index                          # both
vaultspec-rag index --type vault             # vault only
vaultspec-rag index --type code              # code only

vaultspec-rag search "architecture decision"
vaultspec-rag search --type code "error handling"
```

______________________________________________________________________

## Using the MCP server

The [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server gives AI assistants direct access to vault and codebase search. It runs in two transport modes with different project-resolution rules.

**stdio mode** -- one process per project. The MCP client launches `vaultspec-search-mcp` as a subprocess, scoped to a single workspace via `VAULTSPEC_RAG_ROOT`. Use this for Claude Desktop, Claude Code, and similar single-project AI tools.

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

**HTTP mode** -- one daemon, many projects. Start `vaultspec-rag server service start` as a background daemon, then connect any MCP client to `http://127.0.0.1:8766/mcp`. The daemon has no default project; every tool call must include `project_root`. Use this to share one GPU-loaded service across workspaces.

See the [MCP integration reference](./src/vaultspec_rag/README.md#mcp-integration) for the full tool list, both modes' contracts, and choosing between them.

______________________________________________________________________

## Further reading

| Guide                                                                        | What it covers                                       |
| ---------------------------------------------------------------------------- | ---------------------------------------------------- |
| [Usage modes](./src/vaultspec_rag/README.md#usage-modes)                     | Ad-hoc vs. service operation                         |
| [CLI commands](./src/vaultspec_rag/README.md#cli-commands)                   | Command tree, flags, `--port` fast path              |
| [Configuration](./src/vaultspec_rag/README.md#configuration)                 | Precedence, environment variables, `.vaultragignore` |
| [Service management](./src/vaultspec_rag/README.md#service-management)       | Background daemon, health endpoint, model warmup     |
| [Python API](./src/vaultspec_rag/README.md#python-api)                       | Facade functions for programmatic use                |
| [Architecture overview](./src/vaultspec_rag/README.md#architecture-overview) | Access layers, GPU lifecycle, multi-project support  |
| [Models](./src/vaultspec_rag/README.md#models)                               | Embedding stack and model cards                      |

______________________________________________________________________

## Getting help

Open an issue on [GitHub](https://github.com/wgergely/vaultspec-rag/issues).

______________________________________________________________________

## Contributing and license

Contributions welcome -- bug reports, feature ideas, or pull requests. vaultspec-rag uses the [MIT License](./LICENSE).
