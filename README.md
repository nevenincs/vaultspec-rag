<p align="center"><img src="assets/logo.svg" alt="vaultspec-rag logo" width="160"></p>

# vaultspec-rag - semantic search for a vaultspec-core workspace

[![PyPI version](https://img.shields.io/pypi/v/vaultspec-rag.svg)](https://pypi.org/project/vaultspec-rag/) [![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

vaultspec-rag is the semantic search companion to [vaultspec-core](https://github.com/wgergely/vaultspec-core), and the RAG in the name stands for retrieval-augmented generation - the pattern of pulling relevant snippets out of your own files so an agent can answer with grounded context. It indexes the markdown documents in your vault and the source code that sits beside them, then lets you search them by meaning rather than by exact keyword match. A query for "how do we handle file locks during indexing" finds a decision record that discusses concurrent writes and per-root locks, even though it never uses the word "indexing."

## Requirements

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/getting-started/installation/) as the package manager
- An NVIDIA GPU with CUDA support
- About 3 GB of free GPU memory
- Linux or Windows

macOS, AMD GPUs, and Apple Silicon are not supported. For the reasoning behind the hardware floor, see the [architecture overview](docs/architecture.md).

## Quickstart

```bash
uv add vaultspec-rag
uv run vaultspec-rag install
uv run vaultspec-rag index
uv run vaultspec-rag search "your question here"
```

The `install` step prepares the GPU build inside your project, `index` reads your vault and code into a local search index, and `search` returns ranked results for the query you pass. The first run is slower than later runs because of one-time model downloads. For a guided walkthrough against a real query, follow the [getting started guide](docs/getting-started.md).

## What's a vault?

A vault is a `.vault/` directory of markdown files - research notes, architecture decision records, plans, and execution logs - that [vaultspec-core](https://github.com/wgergely/vaultspec-core) creates and manages. If you don't have one yet, set one up there first.

vaultspec-rag adds exactly one capability on top of that: semantic search over the vault and the source code beside it. Vault creation, document templates, frontmatter validation, and the spec-driven workflow all stay in vaultspec-core.

Both packages live side by side in the same project. You can use vaultspec-core on its own without ever installing vaultspec-rag. vaultspec-rag without vaultspec-core has nothing to search.

## Documentation

### Getting started

- [Getting started](docs/getting-started.md) - install, index, and run your first query end to end.
- [Installation](docs/installation.md) - GPU build details, supported platforms, and recovery steps.

### Daily use

- [Search and index](docs/search-and-index.md) - run searches, refresh the index, and scope queries.
- [Service mode](docs/service-mode.md) - keep models warm in a background service for faster queries.
- [MCP integration](docs/mcp.md) - expose search to Claude Code and other MCP clients.
- [Automation](docs/automation.md) - reindex on file changes and wire searches into scripts.

### Reference

- [CLI reference](docs/cli.md) - every command, subcommand, and flag.
- [Configuration](docs/configuration.md) - settings, environment variables, and defaults.
- [Glossary](docs/glossary.md) - terms used across the docs and the codebase.

### Concepts

- [Architecture](docs/architecture.md) - how the index is built, why the GPU is required, and how the pieces fit together.

## Support and help

File bugs and ask questions on the [GitHub issue tracker](https://github.com/wgergely/vaultspec-rag/issues).

A useful bug report includes your vaultspec-rag version, your operating system, your GPU model, the exact command you ran, and the full stderr output.

## What changed

See the [changelog](CHANGELOG.md) for release notes and version history.

## License

vaultspec-rag is released under the MIT License. See [LICENSE](./LICENSE) for the full text.
