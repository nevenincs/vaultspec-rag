# vaultspec-rag

vaultspec-rag is the semantic-search companion to [vaultspec-core](https://github.com/wgergely/vaultspec-core). It indexes your vault's markdown documents and the source code beside them, then searches both by meaning rather than by exact words. A query for "how do we authenticate users" finds a note titled "login flow," which a keyword search would miss.

vaultspec-core manages a `.vault/` directory of markdown documents - research notes, decisions, and plans. vaultspec-rag reads that vault and your code so you can search across both. Without a vaultspec-core workspace, vaultspec-rag has nothing to search.

## Requirements

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- An NVIDIA GPU with CUDA
- About 3 GB of free GPU memory
- Linux or Windows

macOS, AMD GPUs, and Apple Silicon are not supported.

## Install

```bash
uv add vaultspec-rag
uv run vaultspec-rag install
uv sync
```

`install` configures the GPU PyTorch build and provisions the search models and the managed Qdrant server. `uv sync` then fetches the GPU PyTorch build.

## First search

```bash
uv run vaultspec-rag index
uv run vaultspec-rag search "your question here"
```

For repeat use, start the server-backed service first - it keeps the models warm between queries. See the getting-started guide.

## Documentation

The [GitHub docs tree](https://github.com/wgergely/vaultspec-rag/tree/main/docs) holds the getting-started walkthrough, daily-use guides, CLI and configuration reference, and an architecture explanation.

## Support

Report issues on the [GitHub issue tracker](https://github.com/wgergely/vaultspec-rag/issues). A good bug report includes the vaultspec-rag version, your operating system, your GPU model, the exact command you ran, and the full stderr output.
