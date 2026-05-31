# vaultspec-rag

vaultspec-rag is a command-line tool that finds files in your project by what they mean, not by what they say. It runs entirely on your machine and needs an NVIDIA GPU.

## Hardware prerequisites

- NVIDIA GPU with CUDA support
- About 3 GB of free VRAM
- Linux or Windows

vaultspec-rag has no CPU fallback. Without a CUDA-capable GPU it exits with an error.

## Install

Run these three commands in your project:

```sh
uv add vaultspec-rag
uv run vaultspec-rag install
uv sync
```

The `install` command patches your `pyproject.toml` to use the CUDA build of PyTorch.

## First search

Index your project, then ask a question in plain English:

```sh
uv run vaultspec-rag index
uv run vaultspec-rag search "how authentication works"
```

The first index pass downloads model weights and takes a few minutes. Subsequent runs are incremental.

## Documentation

Full documentation lives in the [GitHub docs tree](https://github.com/wgergely/vaultspec-rag/tree/main/docs): a tutorial for first-time setup, how-to guides for common tasks, a CLI and MCP reference, and explanations of the architecture.

## Support and help

Report bugs on the [GitHub issue tracker](https://github.com/wgergely/vaultspec-rag/issues). Include the vaultspec-rag version, your operating system, your GPU model, the command you ran, and the full stderr output.
