<img src="assets/logo.png" width="150" alt="vaultspec-rag logo">

# vaultspec-rag

The semantic search component for vault and code.

Search code and feature records by meaning through the command line or Model Context
Protocol (MCP). Inference runs on your GPU.

[![build](https://img.shields.io/github/actions/workflow/status/nevenincs/vaultspec-rag/ci.yml?branch=main&style=flat&label=build&logo=githubactions&logoColor=white&labelColor=24292f&color=57606a)](https://github.com/nevenincs/vaultspec-rag/actions/workflows/ci.yml)
[![release](https://img.shields.io/pypi/v/vaultspec-rag?style=flat&label=release&logo=pypi&logoColor=white&labelColor=24292f&color=57606a)](https://pypi.org/project/vaultspec-rag/)
[![runtime](https://img.shields.io/badge/runtime-Python%203.13%20%7C%203.14%20%7C%20CUDA%20%7C%20MPS-57606a?style=flat&logo=python&logoColor=white&labelColor=24292f)](#what-you-need)
[![license](https://img.shields.io/github/license/nevenincs/vaultspec-rag?style=flat&label=license&logo=opensourceinitiative&logoColor=white&labelColor=24292f&color=57606a)](./LICENSE)

[Install](#install) · [Use it](#use-it) ·
[Docs](#documentation) · [Help](#status-and-help)

Use it with [vaultspec-core](https://github.com/nevenincs/vaultspec-core) or
independently in another repository. To index PDFs and other formats,
[connect a converter](#read-pdfs-and-other-formats).

## What you need

For the Python installation below, use Python 3.13 or 3.14 and
[uv](https://docs.astral.sh/uv/getting-started/installation/).
Local indexing and search require NVIDIA CUDA on Linux or Windows, or Apple silicon
on macOS. CPU inference and AMD GPUs are unsupported.

Check the [memory and disk requirements](docs/installation.md#what-you-need-before-you-start)
before installing. That section also covers the smaller resource profile.

## Install

Install a standalone tool for use across repositories. Choose the command for your
platform. These CUDA commands use Python 3.13 and pin the GPU wheel so later tool
upgrades retain it.

Windows x64:

```powershell
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.13.0%2Bcu130-cp313-cp313-win_amd64.whl"
```

Linux x86_64 (glibc 2.28 or newer):

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.13.0%2Bcu130-cp313-cp313-manylinux_2_28_x86_64.whl"
```

Apple silicon macOS:

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]"
```

For other Python versions or Linux architectures, see [GPU wheel selection](docs/installation.md#pin-the-gpu-build).
If uv reports that its executables directory is missing from `PATH`, follow its
instructions before continuing. For an existing tool installation, follow the
[upgrade and repair instructions](docs/installation.md#pin-the-gpu-build) before
replacing its environment.

Once installation succeeds, open the repository you want to search and run:

```bash
vaultspec-rag install --no-torch-config
```

This installs the repository's agent integration, downloads the three search models,
and provisions Qdrant, the index server. The GPU packages are already installed, so
`--no-torch-config` leaves the project's PyTorch configuration alone. The first setup
downloads several gigabytes; subsequent projects share the models and server binary.

Check the installation:

```bash
vaultspec-rag server doctor
```

<p align="center">
<img src="assets/term-doctor.svg" alt="vaultspec-rag server doctor - service, GPU, model, and Qdrant readiness at a glance" width="880" />
</p>

Check that the report detects your GPU and finds all three models and the Qdrant
binary. If it reports a problem, use the [installation troubleshooting guide](docs/installation.md#when-something-goes-wrong).

## Use it

Start the service to load the models. The command waits until it is ready:

```bash
vaultspec-rag server start
```

Index the repository from its root:

```bash
vaultspec-rag index
```

Wait for indexing to finish before searching. Use `vaultspec-rag server jobs --watch`
to follow progress. The service watches for file changes and updates the index
automatically afterwards.

Search source code with `--type code`, or feature records with `--type vault`:

```bash
vaultspec-rag search "parse query text into filters" --type code
```

If results are missing or incomplete, [check the index](docs/verification.md) and
[adjust the query](docs/query-craft.md).

One service handles all your repositories. Run `index` in each repository you want
to search. See [index maintenance](docs/search-and-index.md) for rebuilding or
removing indexed content.

### Other ways to install

For a Python project that should carry the dependency, run:

```bash
uv add "vaultspec-rag[gpu]"
uv run vaultspec-rag install --sync
```

Approve the PyTorch configuration prompt. On Linux and Windows, `--sync` applies the
CUDA package source; macOS uses the standard MPS-capable wheel. Prefix subsequent
commands with `uv run`, for example `uv run vaultspec-rag server start`.

Without a Python toolchain, use the [prebuilt Windows or Linux binaries](docs/installation.md#install-without-python).

<p id="where-it-puts-things-and-how-to-remove-it"></p>

### Remove RAG

Follow the [removal guide](docs/installation.md#remove-it) to preview project changes,
choose whether to clean up indexes, and remove the package.

<p id="write-a-query-that-finds-it"></p>
<p id="narrow-the-results"></p>
<p id="check-on-the-index"></p>

## Refine searches

- [Choose query terms](docs/query-craft.md#name-the-nouns-and-ask-one-thing).
- [Filter by language, path, or document type](docs/query-craft.md#the-filter-surface).
- [Investigate missing results and index coverage](docs/verification.md).
- [Monitor indexing jobs](docs/service-mode.md#observe-activity).

## Use it from an AI assistant

Follow [MCP setup](docs/mcp.md) to connect your coding agent. The default toolset
includes tools that change or delete indexes. To restrict access, see
[withholding the mutating tools](docs/mcp.md#withholding-the-mutating-tools).

<p id="run-without-the-search-server"></p>

## Use an on-disk index

By default, vaultspec-rag uses managed Qdrant in a separate process. The optional
local-only backend keeps an embedded on-disk index inside the RAG process. It still
requires a GPU and models.

Switching backends does not migrate your existing index. Follow
[backend setup](docs/backends.md).

## Read PDFs and other formats

Converters extract content from unsupported formats for indexing. See
[converter setup](docs/preprocessing-hooks.md).

<p id="what-a-converter-is-allowed-to-do"></p>

Converters run without a sandbox, with the permissions of the account running RAG.
They can access files and the network. They can run during explicit indexing,
watched changes, and agent-triggered reindexing.

Before indexing, inspect `.vaultragpreprocess.toml` and its commands. Use
`vaultspec-rag preprocess status` to inspect configuration without running converters.
See [security and disable options](docs/preprocessing-hooks.md#security-posture).

## Scripting it

For JSON output and result handling, follow [scripting and automation](docs/automation.md).

<p id="how-it-works"></p>

## Documentation

- [Run your first search](docs/getting-started.md)
- [Installation and troubleshooting](docs/installation.md)
- [Worked searches](docs/examples.md)
- [Commands and flags](docs/cli.md)
- [Configuration reference](docs/configuration.md)
- [Architecture](docs/architecture.md) and [indexing internals](docs/indexing.md)
- [Release notes](CHANGELOG.md)

## Status and help

vaultspec-rag is Beta. [Report issues](https://github.com/nevenincs/vaultspec-rag/issues)
with your version, operating system, GPU, command, and error output.
Redact credentials and private content before posting.

## Related projects

- [vaultspec-core](https://github.com/nevenincs/vaultspec-core):
  Decision-driven harness for coding agents, and humans.
- [vaultspec-dashboard](https://github.com/nevenincs/vaultspec-dashboard):
  The human-facing visual workspace for a Vaultspec project.

## License

vaultspec-rag is released under the [MIT License](./LICENSE).
