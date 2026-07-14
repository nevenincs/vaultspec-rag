<div align="center">

<img src="assets/logo.svg" alt="vaultspec-rag family logo" width="150" />

# vaultspec-rag

**The semantic retrieval layer for finding decisions and code by meaning.**

[![build](https://img.shields.io/github/actions/workflow/status/nevenincs/vaultspec-rag/ci.yml?branch=main&style=for-the-badge&label=build&logo=githubactions&logoColor=white&labelColor=1b1a16)](https://github.com/nevenincs/vaultspec-rag/actions/workflows/ci.yml)
[![release](https://img.shields.io/pypi/v/vaultspec-rag?style=for-the-badge&label=release&logo=pypi&logoColor=white&labelColor=1b1a16&color=8A72B5)](https://pypi.org/project/vaultspec-rag/)
[![runtime](https://img.shields.io/badge/runtime-Python%203.13%2B%20%7C%20CUDA-3F9AA6?style=for-the-badge&logo=nvidia&logoColor=white&labelColor=1b1a16)](#requirements)
[![license](https://img.shields.io/github/license/nevenincs/vaultspec-rag?style=for-the-badge&label=license&logo=opensourceinitiative&logoColor=white&labelColor=1b1a16&color=B3823C)](./LICENSE)

[![cli](https://img.shields.io/badge/cli-bundled-B5703F?style=for-the-badge&logo=gnubash&logoColor=white&labelColor=1b1a16)](./docs/cli.md)
[![mcp](https://img.shields.io/badge/mcp-bundled-B05A6B?style=for-the-badge&logo=modelcontextprotocol&logoColor=white&labelColor=1b1a16)](./docs/mcp.md)

[Get started](#quickstart) ·
[Product](#searching-by-meaning) ·
[Documentation](#documentation) ·
[Family](#the-vaultspec-family) ·
[Support](#support-and-help)

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

To install as a standalone tool instead, pin the GPU torch wheel in the tool receipt so `uv tool upgrade` keeps the CUDA build (a bare `uv tool install` re-resolves torch to a CPU-only wheel on every upgrade, and `--index` is not recorded in tool receipts):

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

### Preprocessing hooks

A root's `.vaultragpreprocess.toml` can shell out to convert PDFs, spreadsheets, and other non-text formats into indexable text. Preprocessing is on by default and needs no trust step: a root's preprocess config **is code execution with your privileges**, the same trust class as running that repo's build scripts, so do not index a repository you would not build. Its rules run directly as bounded subprocesses - a curated environment with the daemon's secrets stripped, the project root as the working directory, and a wall-clock timeout and output caps - but with the filesystem and network access of the account running the service.

`preprocess status` reports the mode, config presence, and rule count for a root. Set `VAULTSPEC_RAG_PREPROCESS=off` to disable preprocessing everywhere (the kill switch, mirrored as `--no-preprocess`). Edits to `.gitignore`, `.vaultragignore`, or `.vaultragpreprocess.toml` are detected automatically: the next index run - including the watcher's - reconciles or rebuilds as needed, with no manual reindex required.

See [preprocessing hooks](docs/preprocessing-hooks.md) for the full rule syntax and supported formats.

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

The family has three focused responsibilities: vaultspec-core governs the workflow and
vault; vaultspec-rag retrieves decisions and code by meaning; and vaultspec-dashboard is
the visual workspace that aggregates those views.

- [vaultspec-core](https://github.com/nevenincs/vaultspec-core) - the governed `Research → Decide (ADRs) → Plan → Execute → Verify` workflow, git-tracked Markdown vault, CLI, and MCP server.
- [vaultspec-dashboard](https://github.com/nevenincs/vaultspec-dashboard) - the visual workspace for exploring the vault, source tree, document graph, workflow state, and semantic search.

## Support and help

File bugs and ask questions on the [GitHub issue tracker](https://github.com/nevenincs/vaultspec-rag/issues).

A good bug report carries five things: your vaultspec-rag version, your operating system, your GPU model, the exact command you ran, and the full stderr output. With those, a maintainer can reproduce the fault. Without them, the report is hard to act on.

## Changelog and license

The [changelog](CHANGELOG.md) holds release notes and version history.

vaultspec-rag is released under the MIT License. See [LICENSE](./LICENSE) for the full text.
