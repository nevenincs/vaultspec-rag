<div align="center">

<img src="assets/logo.svg" alt="vaultspec-rag family logo" width="150" />

# vaultspec-rag

**Semantic search for vault records, source code, and extracted documents.**

[![build](https://img.shields.io/github/actions/workflow/status/nevenincs/vaultspec-rag/ci.yml?branch=main&style=for-the-badge&label=build&logo=githubactions&logoColor=white&labelColor=1b1a16)](https://github.com/nevenincs/vaultspec-rag/actions/workflows/ci.yml)
[![release](https://img.shields.io/pypi/v/vaultspec-rag?style=for-the-badge&label=release&logo=pypi&logoColor=white&labelColor=1b1a16&color=8A72B5)](https://pypi.org/project/vaultspec-rag/)
[![runtime](https://img.shields.io/badge/runtime-Python%203.13%2B%20%7C%20CUDA-3F9AA6?style=for-the-badge&logo=nvidia&logoColor=white&labelColor=1b1a16)](#getting-started)
[![license](https://img.shields.io/github/license/nevenincs/vaultspec-rag?style=for-the-badge&label=license&logo=opensourceinitiative&logoColor=white&labelColor=1b1a16&color=B3823C)](./LICENSE)

[![cli](https://img.shields.io/badge/cli-bundled-B5703F?style=for-the-badge&logo=gnubash&logoColor=white&labelColor=1b1a16)](./docs/cli.md)
[![mcp](https://img.shields.io/badge/mcp-optional-B05A6B?style=for-the-badge&logo=modelcontextprotocol&logoColor=white&labelColor=1b1a16)](./docs/mcp.md)

[Get started](#getting-started) ·
[Product](#capabilities) ·
[Documentation](#documentation) ·
[Family](#the-vaultspec-family) ·
[Support](#status-help-and-license)

</div>

<p align="center">
<img src="assets/term-search-vault.svg" alt="vaultspec-rag search - a plain-English query surfacing the governing ADR from this repository's own vault" width="880" />
</p>

A [vaultspec-core](https://github.com/nevenincs/vaultspec-core) project accumulates a
durable record of decisions, plans, research, and the code they produced. vaultspec-rag
searches that record, conventional source code, and explicitly routed extracted documents
by meaning, not by keyword.

Search `"file lock concurrent write per-root"` and vaultspec-rag surfaces the decision that governs it, even when the document never uses those exact words. It is the retrieval layer of the project: it finds and ranks the grounding, and a client such as a coding agent reads it.

The terminal renders on this page are real output from this repository's vault and code
searches and its service diagnostics. The same runtime exposes independent document
search for explicitly routed extractor output. The [architecture overview](docs/architecture.md)
explains how it works; the [glossary](docs/glossary.md) defines the terms used across the docs.

## Getting started

vaultspec-rag needs an NVIDIA GPU with CUDA support (about 3 GB free) and Python 3.13+ on Linux or Windows; macOS, AMD GPUs, and Apple Silicon are not supported. See the [architecture overview](docs/architecture.md) for why the hardware floor sits where it does.

### Install

Try it now with no project setup, straight from PyPI:

```bash
uvx vaultspec-rag install
```

Runs `install` in an ephemeral `uv tool` environment: it enrolls the current directory as a workspace, provisions the GPU PyTorch build, downloads the search models, and fetches the pinned Qdrant server binary, asking once before touching any config. Good for a first try. A bare `uvx` run does not pin the GPU torch build across invocations the way the project-dependency and standalone-tool paths do, so switch to one of those once you're keeping vaultspec-rag around.

Add vaultspec-rag to your project and set it up:

```bash
uv add vaultspec-rag
uv run vaultspec-rag install
uv sync
```

`install` configures the GPU PyTorch build, downloads the search models, and provisions the managed search server. `uv sync` then pulls in that GPU build. The models total a few gigabytes, so the first download takes several minutes, but it runs only once.

To install as a standalone tool instead, pin the GPU torch wheel in the tool receipt so `uv tool upgrade` keeps the CUDA build. A bare `uv tool install` re-resolves torch to a CPU-only wheel on every upgrade, and `--index` is not recorded in tool receipts, so the `--with` pin is the durable fix:

```bash
uv tool install "vaultspec-rag[mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.13.0%2Bcu130-cp313-cp313-win_amd64.whl"
uvx vaultspec-rag install
```

On Linux, use the matching `manylinux_2_28_x86_64` wheel from the same index.

See the [installation guide](docs/installation.md) for tool-environment repair and upgrade caveats.

### Index and search

1. Start the server:

   ```bash
   uv run vaultspec-rag server start
   ```

1. Index your project:

   ```bash
   uv run vaultspec-rag index
   ```

1. Search:

   ```bash
   uv run vaultspec-rag search "concept plus the domain terms"
   ```

The first run builds the index. After that, the running service watches your files and reindexes changes automatically, so the index stays current without another command. Check readiness at any time with `server doctor`:

<p align="center">
<img src="assets/term-doctor.svg" alt="vaultspec-rag server doctor - service, GPU, model, and Qdrant readiness at a glance" width="880" />
</p>

See the [getting started guide](docs/getting-started.md) for the full walkthrough.

## Capabilities

| Capability               | What it gives you                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------ |
| Hybrid search            | Dense (semantic) and sparse (keyword) matching, cross-encoder reranked               |
| Independent search       | Search `vault`, `code`, or extracted `document` content, or combine all three        |
| Managed or local backend | A supervised Qdrant server for throughput, or `--local-only` for a zero-server setup |
| MCP integration          | Search, reindex, clean, and inspect vault, code, and document domains                |
| Live reindexing          | The running service watches your files and reindexes changes automatically           |
| Preprocessing hooks      | Route project-defined extractor output explicitly to code or document indexing       |

<p align="center">
<img src="assets/term-search-code.svg" alt="vaultspec-rag code search - the reranker implementation surfaced from a plain-English description" width="880" />
</p>

See [search and index](docs/search-and-index.md) for the full filter set, [MCP integration](docs/mcp.md) for client setup, and [preprocessing hooks](docs/preprocessing-hooks.md) for the extraction rule syntax and its trust model.

## The vaultspec family

- [vaultspec-core](https://github.com/nevenincs/vaultspec-core) - Beta - The agent harness: the pipeline, the vault, and the CLI that drives them.
- **vaultspec-rag** - Beta - Semantic search across vault, code, and document domains.
- [vaultspec-dashboard](https://github.com/nevenincs/vaultspec-dashboard) - Beta - The application that runs it all as a UI.

## Documentation

### Getting started guide

- [Getting started](docs/getting-started.md) - install, index, and run your first query end to end.
- [Installation](docs/installation.md) - the GPU build, dependency provisioning, and recovery steps.

### Daily use

- [Search and index](docs/search-and-index.md) - run searches and refresh the index.
- [Service mode](docs/service-mode.md) - keep models warm in a background service for faster queries.
- [Backends](docs/backends.md) - the managed Qdrant server versus local-only mode.
- [MCP integration](docs/mcp.md) - wire search into Claude Code and other MCP clients.
- [Automation](docs/automation.md) - JSON output and scripting.
- [Preprocessing hooks](docs/preprocessing-hooks.md) - connect project-defined extractors for PDFs, spreadsheets, and other formats.

### Reference

- [CLI reference](docs/cli.md) - every command and flag.
- [Configuration](docs/configuration.md) - settings, environment variables, and defaults.
- [Service discovery](docs/service-discovery.md) - the `service.json` contract for integrators.
- [Glossary](docs/glossary.md) - terms used across the docs.

### Concepts

- [Architecture](docs/architecture.md) - how it works, why a GPU is required, and the server and local-only modes.
- [Indexing](docs/indexing.md) - indexing and retrieval internals.

## Status, help, and license

vaultspec-rag is Beta. File bugs and ask questions on the [GitHub issue tracker](https://github.com/nevenincs/vaultspec-rag/issues).

A good bug report carries five things: your vaultspec-rag version, your operating system, your GPU model, the exact command you ran, and the full stderr output. With those, a maintainer can reproduce the fault. Without them, the report is hard to act on.

The [changelog](CHANGELOG.md) holds release notes and version history. vaultspec-rag is released under the [MIT License](./LICENSE).
