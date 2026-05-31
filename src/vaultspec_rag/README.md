# vaultspec-rag

vaultspec-rag is the semantic-search companion to vaultspec-core, providing retrieval-augmented generation (RAG) over your vault of markdown notes and your source code. Semantic search matches on meaning, not on exact words. A query for "how do we authenticate users" finds a note titled "login flow," which a keyword search would miss.

vaultspec-rag is a companion to [vaultspec-core](https://github.com/wgergely/vaultspec-core). vaultspec-core manages the `.vault/` directory of markdown notes and decisions; vaultspec-rag indexes that vault and your source code so you can search both by meaning. Without a vaultspec-core workspace, vaultspec-rag has nothing to search.

## Requirements

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- An NVIDIA GPU with CUDA
- About 3 GB of free GPU memory
- Linux or Windows

macOS, AMD GPUs, and Apple Silicon are not supported.

## Install

```sh
uv add vaultspec-rag
uv run vaultspec-rag install
uv sync
```

The `install` command prepares your project for the GPU build of PyTorch.

## First search

```sh
uv run vaultspec-rag index
uv run vaultspec-rag search "your question here"
```

`index` builds the local search index from your vault and code. `search` returns ranked results in your terminal.

## Documentation

The [GitHub docs tree](https://github.com/wgergely/vaultspec-rag/tree/main/docs) contains a getting-started walkthrough, daily-use guides, CLI and configuration reference, and an architecture explanation.

## Support

Report issues on the [GitHub issue tracker](https://github.com/wgergely/vaultspec-rag/issues). A useful bug report includes the vaultspec-rag version, your operating system, your GPU model, the exact command you ran, and the full stderr output.
