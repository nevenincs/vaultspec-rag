<div align="center">

<img src="assets/logo.svg" alt="vaultspec-rag logo" width="150" />

# vaultspec-rag

**Semantic search for a vaultspec-core workspace - find decisions and code by meaning.**

[![CI](https://github.com/nevenincs/vaultspec-rag/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/nevenincs/vaultspec-rag/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/vaultspec-rag.svg)](https://pypi.org/project/vaultspec-rag/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Status: Beta](https://img.shields.io/badge/status-beta-yellow.svg)](https://github.com/nevenincs/vaultspec-rag/releases)

[Quickstart](#quickstart) ·
[Searching by meaning](#searching-by-meaning) ·
[Documentation](#documentation) ·
[The family](#the-vaultspec-family)

</div>

A [vaultspec-core](https://github.com/nevenincs/vaultspec-core) project accumulates a durable record of decisions, plans, research, and the code they produced. vaultspec-rag searches that record and your source code by meaning, not by keyword.

Search `"file lock concurrent write per-root"` and vaultspec-rag surfaces the decision that governs it, even when the document never uses those exact words. It is the retrieval layer of the project: it finds and ranks the grounding, and a client such as a coding agent reads it.

<p align="center">
<img src="assets/term-search-vault.svg" alt="vaultspec-rag search - a plain-English query surfacing the governing ADR from this repository's own vault" width="880" />
</p>

Every terminal render on this page is real output against this repository's own vault and code. The [architecture overview](docs/architecture.md) explains how it works; the [glossary](docs/glossary.md) defines the terms used across the docs.

## Requirements

Before you install, confirm your machine meets these minimum requirements:

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/getting-started/installation/) as the package manager
- An NVIDIA GPU with CUDA support
- About 3 GB of free GPU memory
- Linux or Windows

macOS, AMD GPUs, and Apple Silicon are not supported. The [architecture overview](docs/architecture.md) explains why the hardware floor sits where it does.

## Quickstart

### Install

Add vaultspec-rag to your project and set it up:

```bash
uv add vaultspec-rag
uv run vaultspec-rag install
uv sync
```

`install` configures the GPU PyTorch build, downloads the search models, and provisions the managed search server. `uv sync` then pulls in that GPU build. The models total a few gigabytes, so the first download takes several minutes, but it runs only once.

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

## Searching by meaning

The index is hybrid. A semantic half matches concepts and a keyword half matches exact terms, so write your query as a short phrase that both describes the concept and names the domain terms the target text would use. Pure prose starves the keyword half.

```bash
uv run vaultspec-rag search "store-layer locking reentrant lock per collection local mode" --type vault
```

The render at the top of this page is that query against this repository's vault: the top hit is the accepted concurrency ADR, with its rationale ready to read. Each result is a rank, a location you can open, and the matching text. Vault hits carry a metadata line, so a superseded ADR shows as superseded before you read it.

### Searching code and filtering

Search code with `--type code`, and narrow with filters including `--language`, `--path`, and a symbol name. Add `--scores` to see the relevance number beside each rank:

```bash
uv run vaultspec-rag search "gpu section wrapping the reranker predict forward pass" --type code --language python --scores
```

<p align="center">
<img src="assets/term-search-code.svg" alt="vaultspec-rag code search - the reranker implementation surfaced from a plain-English description" width="880" />
</p>

For the full filter set (path globs, document type, feature, date), see [search and index](docs/search-and-index.md).

## Documentation

### Getting started

- [Getting started](docs/getting-started.md) - install, index, and run your first query end to end.
- [Installation](docs/installation.md) - the GPU build, dependency provisioning, and recovery steps.

### Daily use

- [Search and index](docs/search-and-index.md) - run searches and refresh the index.
- [Service mode](docs/service-mode.md) - keep models warm in a background service for faster queries.
- [Backends](docs/backends.md) - the managed Qdrant server versus local-only mode.
- [MCP integration](docs/mcp.md) - wire search into Claude Code and other MCP clients.
- [Automation](docs/automation.md) - JSON output and scripting.
- [Preprocessing hooks](docs/preprocessing-hooks.md) - index PDFs, spreadsheets, and other formats.

### Reference

- [CLI reference](docs/cli.md) - every command and flag.
- [Configuration](docs/configuration.md) - settings, environment variables, and defaults.
- [Service discovery](docs/service-discovery.md) - the `service.json` contract for integrators.
- [Glossary](docs/glossary.md) - terms used across the docs.

### Concepts

- [Architecture](docs/architecture.md) - how it works, why a GPU is required, and the server and local-only modes.
- [Indexing](docs/indexing.md) - indexing and retrieval internals.

## The vaultspec family

vaultspec-rag is the retrieval layer of the vaultspec family - a set of tools built around one shared vault:

- [vaultspec-core](https://github.com/nevenincs/vaultspec-core) - the hub: the `Research → Decide → Plan → Code → Review` pipeline, the git-tracked Markdown vault, and the CLI that drives them.
- vaultspec-dashboard - a visual companion for vault health, decision graphs, and search activity. In development.
- vaultspec-a2a - agent-to-agent orchestration across your coding agents. Early.

## Support and help

File bugs and ask questions on the [GitHub issue tracker](https://github.com/nevenincs/vaultspec-rag/issues).

A good bug report carries five things: your vaultspec-rag version, your operating system, your GPU model, the exact command you ran, and the full stderr output. With those, a maintainer can reproduce the fault. Without them, the report is hard to act on.

## Changelog and license

The [changelog](CHANGELOG.md) holds release notes and version history.

vaultspec-rag is released under the MIT License. See [LICENSE](./LICENSE) for the full text.
