<div align="center">

<img src="assets/logo.png" alt="vaultspec-rag family logo" width="150" />

# vaultspec-rag

**Semantic search for vault records, source code, and extracted documents.**

[![install](https://img.shields.io/badge/install-uvx%20vaultspec--rag%20install%20%28NVIDIA%20GPU%29-2E6B45?style=for-the-badge&logo=uv&logoColor=white&labelColor=1b1a16)](#getting-started)
[![build](https://img.shields.io/github/actions/workflow/status/nevenincs/vaultspec-rag/ci.yml?branch=main&style=for-the-badge&label=build&logo=githubactions&logoColor=white&labelColor=1b1a16)](https://github.com/nevenincs/vaultspec-rag/actions/workflows/ci.yml)
[![release](https://img.shields.io/pypi/v/vaultspec-rag?style=for-the-badge&label=release&logo=pypi&logoColor=white&labelColor=1b1a16&color=8A72B5)](https://pypi.org/project/vaultspec-rag/)
[![runtime](https://img.shields.io/badge/runtime-Python%203.13%20%7C%203.14%20%7C%20CUDA%20%7C%20MPS-3F9AA6?style=for-the-badge&labelColor=1b1a16)](#getting-started)
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

Local indexing and search need CPython 3.13 or 3.14, the `[gpu]` extra, and a supported accelerator: an NVIDIA GPU with CUDA on Linux or Windows (about 3 GB of free VRAM), or Apple silicon with MPS on macOS. An 8 GiB unified-memory Mac is the measured Apple silicon floor. CPU inference and AMD GPUs are unsupported. The bare package remains a lightweight control-plane install without torch, sentence-transformers, or CUDA. See the [architecture overview](docs/architecture.md) for why the hardware floor sits where it does.

### Install

Try it now with no project setup, straight from PyPI:

```bash
uvx --from "vaultspec-rag[gpu]" vaultspec-rag install
```

Runs `install` in an ephemeral `uv` environment: it enrolls the current directory as a workspace, provisions the platform PyTorch build, downloads the search models, and fetches the pinned Qdrant server binary, asking once before touching any config. The `[gpu]` extra supplies the local inference stack. The managed torch edit selects CUDA on Linux and Windows; its platform marker leaves macOS on PyTorch's standard MPS-capable wheel. Switch to a durable project or tool installation once you're keeping vaultspec-rag around.

Add vaultspec-rag to your project and set it up:

```bash
uv add "vaultspec-rag[gpu]"
uv run vaultspec-rag install --sync
```

`install` downloads the search models, provisions the managed search server, and asks before writing the managed torch configuration. The `[gpu]` extra carries the local inference libraries. On Linux and Windows, `--sync` applies the pinned CUDA build; on macOS the source marker is inactive, so it installs the standard MPS-capable PyTorch wheel. The bare package avoids the inference footprint but cannot index or search locally.

On Linux or Windows, a standalone tool must pin the GPU torch wheel in its receipt so `uv tool upgrade` keeps the CUDA build. The command is environment-specific; `vaultspec-rag server start` and `install` print the exact one when they detect a CPU-only tool environment. Its shape (here Python 3.13, torch 2.13.0, Windows) is:

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.13.0%2Bcu130-cp313-cp313-win_amd64.whl"
vaultspec-rag install
```

The `--python` request must match the wheel's `cp3XX` tag; without it, uv resolves the tool env on its default python, and a default that differs from the wheel's interpreter fails the install on a tag mismatch.

On Apple silicon, the standard macOS PyTorch wheel supplies MPS, so the durable tool install needs no CUDA wheel pin:

```bash
uv tool install --python 3.13 "vaultspec-rag[mcp]"
vaultspec-rag install
```

See the [installation guide](docs/installation.md) for tool-environment repair and upgrade caveats.

#### Standalone binaries

Every release also publishes standalone binaries through the account channel
root, `nevenincs/homebrew-tap`, which needs no Python toolchain on the machine:

```powershell
# Windows x86-64, via Scoop
scoop bucket add nevenincs https://github.com/nevenincs/homebrew-tap
scoop install vaultspec-rag
```

```bash
# Linux x86-64 and arm64, via Homebrew
brew tap nevenincs/tap https://github.com/nevenincs/homebrew-tap
brew install vaultspec-rag
```

These place `vaultspec-rag` and `vaultspec-search-mcp`. The first launch of
either resolves the package from PyPI, and the binaries carry the accelerated
torch pin, so the GPU build arrives without the `--with` dance the tool-install
path needs above.

The tap is the **account** root rather than this repository, so it is added once
and carries every vaultspec product. The standalone packaging lane currently
publishes Windows and Linux artifacts only; Apple silicon support uses the
Python project or tool installation above. Linux binaries have a glibc floor -
see the [installation guide](docs/installation.md).

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

Watch that reindexing as it happens. `server jobs --watch` opens a full-screen interface over the running service: live progress per job, the jobs queued behind the GPU slot, what the watcher started versus what you did, per-row pause, retry and cancel, and the selected job's log beside the table.

<p align="center">
<img src="assets/term-jobs-watch.svg" alt="vaultspec-rag server jobs --watch - the live jobs interface showing an active vault index, two jobs waiting on the GPU slot, and the selected job's service log" width="880" />
</p>

See [search and index](docs/search-and-index.md) for the full filter set, [MCP integration](docs/mcp.md) for client setup, and [preprocessing hooks](docs/preprocessing-hooks.md) for the extraction rule syntax and its trust model.

## The vaultspec family

- [vaultspec-core](https://github.com/nevenincs/vaultspec-core) - Beta - The agent harness: the pipeline, the vault, and the CLI that drives them.
- **vaultspec-rag** - Beta - Semantic search across vault, code, and document domains.
- [vaultspec-dashboard](https://github.com/nevenincs/vaultspec-dashboard) - Beta - The application that runs it all as a UI.

## Documentation

### Getting started guide

- [Getting started](docs/getting-started.md) - install, index, and run your first query end to end.
- [Installation](docs/installation.md) - accelerator-specific PyTorch behavior, dependency provisioning, and recovery steps.

### Daily use

- [Search and index](docs/search-and-index.md) - run searches and refresh the index.
- [Writing a query that finds it](docs/query-craft.md) - phrasing, the full filter surface, and what to do when a result looks wrong.
- [Retrieval recipes](docs/examples.md) - worked searches for the questions it answers well, and the ones it answers badly.
- [Verify the index](docs/verification.md) - confirm the service is healthy, the index is current, and it covers the tree you meant.
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

- [Architecture](docs/architecture.md) - how it works, why an accelerator is required, and the server and local-only modes.
- [Indexing](docs/indexing.md) - indexing and retrieval internals.

## Status, help, and license

vaultspec-rag is Beta. File bugs and ask questions on the [GitHub issue tracker](https://github.com/nevenincs/vaultspec-rag/issues).

A good bug report carries five things: your vaultspec-rag version, your operating system, your GPU model, the exact command you ran, and the full stderr output. With those, a maintainer can reproduce the fault. Without them, the report is hard to act on.

The [changelog](CHANGELOG.md) holds release notes and version history. vaultspec-rag is released under the [MIT License](./LICENSE).
