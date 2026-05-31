<p align="center">
  <img src="assets/logo.svg" alt="vaultspec-rag logo" width="160">
</p>

# vaultspec-rag

[![PyPI](https://img.shields.io/pypi/v/vaultspec-rag)](https://pypi.org/project/vaultspec-rag/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](./pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

vaultspec-rag is a command-line tool that finds files in your project by what
they mean, not by what they say. It runs entirely on your machine and needs an
NVIDIA GPU.

The tool runs on the GPU only. You need an NVIDIA card with CUDA, roughly
3 GB of free VRAM, and Linux or Windows. macOS and AMD GPUs are not supported.
If your machine doesn't meet that bar, the rest of this page won't help you.

## First command

```sh
uv add vaultspec-rag
uv run vaultspec-rag install
uv run vaultspec-rag index
uv run vaultspec-rag search "your question here"
```

The `install` step patches your `pyproject.toml` so `uv` resolves the CUDA build
of `torch`. The `index` step embeds your vault and code into a local Qdrant
collection. After that, `search` returns ranked results from the terminal.

## Documentation

The four guides under `docs/` are split by purpose. Pick the one that matches
what you're trying to do.

- [Tutorial: your first search](./docs/tutorial/first-search.md) - run your
  first search in five minutes.
- [How-to guides](./docs/how-to/) - recipes for installing, running as a
  service, scripting with `--json`, and integrating with MCP clients.
- [Reference](./docs/reference/) - CLI flags, configuration, MCP tools, the
  JSON envelope, and the glossary.
- [Explanation](./docs/explanation/) - how the tool works, and why semantic
  search is worth its costs.

## Support and help

Report bugs and ask questions on the
[GitHub issue tracker](https://github.com/wgergely/vaultspec-rag/issues).

A useful bug report includes the `vaultspec-rag` version (`vaultspec-rag --version`), your operating system, your GPU model, the exact command you ran,
and the full stderr output.

## What changed

Release notes for every version are in [CHANGELOG.md](./CHANGELOG.md).

## License

vaultspec-rag is published under the [MIT License](./LICENSE).
