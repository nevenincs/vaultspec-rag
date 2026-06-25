<p align="center"><img src="assets/logo.svg" alt="vaultspec-rag logo" width="160"></p>

# vaultspec-rag: semantic search for a vaultspec-core workspace

[![CI](https://github.com/nevenincs/vaultspec-rag/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/nevenincs/vaultspec-rag/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/vaultspec-rag.svg)](https://pypi.org/project/vaultspec-rag/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Status: Beta](https://img.shields.io/badge/status-beta-yellow.svg)](https://github.com/nevenincs/vaultspec-rag/releases)

A [vaultspec-core](https://github.com/nevenincs/vaultspec-core) project accumulates a durable record of decisions, plans, research, and the code they produced. vaultspec-rag searches that record and your source code by meaning, not by keyword.

Search `"file lock concurrent write per-root"` and vaultspec-rag surfaces the decision that governs it, even when the document never uses those exact words. It is the retrieval layer of the project: it finds and ranks the grounding, and a client such as an AI assistant reads it.

The [architecture overview](docs/architecture.md) explains how it works; the [glossary](docs/glossary.md) defines the terms used across the docs.

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

The first run builds the index. After that, the running service watches your files and reindexes changes automatically, so the index stays current without another command. See the [getting started guide](docs/getting-started.md) for the full walkthrough.

## Searching by meaning

The index is hybrid. A semantic half matches concepts and a keyword half matches exact terms, so write your query as a short phrase that both describes the concept and names the domain terms the target text would use. Pure prose starves the keyword half.

```bash
uv run vaultspec-rag search "reentrant collection lock ordering during indexing"
```

```
1. adr/2026-06-12-service-concurrency-adr
   adr | feature: service-concurrency | status: accepted | 2026-06-12
   Store-layer locking distinguishes local mode (one reentrant lock per
   collection) from server mode (no point locks). The lifecycle lock is
   always acquired before any collection lock.
2. reference/2026-06-12-service-concurrency-reference
   reference | feature: service-concurrency | 2026-06-12
   Per-root locks keep concurrent writers from colliding on the shared store.
```

Each result is a rank, a location you can open, and the matching text. Vault hits carry a metadata line, so a superseded ADR shows as superseded before you read it.

### Searching code and filtering

Search code with `--type code`, and narrow with filters including `--language`, `--path`, and a symbol name. Add `--scores` to see the relevance number beside each rank:

```bash
uv run vaultspec-rag search "gpu section wrapping the reranker predict forward pass" --type code --language python --scores
```

```
1. src/vaultspec_rag/search/_searcher.py:308 (score 0.9241)
   # The GPU lock wraps only the model forward call; the
   # score-to-float conversion below runs after release.
   with self._gpu_section(timings):
       while True:
           try:
               raw_scores = reranker.predict(
```

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

## Support and help

File bugs and ask questions on the [GitHub issue tracker](https://github.com/nevenincs/vaultspec-rag/issues).

A good bug report carries five things: your vaultspec-rag version, your operating system, your GPU model, the exact command you ran, and the full stderr output. With those, a maintainer can reproduce the fault. Without them, the report is hard to act on.

## Changelog and license

The [changelog](CHANGELOG.md) holds release notes and version history.

vaultspec-rag is released under the MIT License. See [LICENSE](./LICENSE) for the full text.
