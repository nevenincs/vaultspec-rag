# Installation

vaultspec-rag is GPU-accelerated semantic search over your vault and source code. This guide covers how to install the package, provision its dependencies, verify the install, recover from setup failures, and uninstall. For a guided first run afterward, see the [getting started guide](getting-started.md).

## Before you begin

You need:

- Python 3.13 or newer. The runtime is locked to CPython 3.13.x; 3.14 and later are rejected at import.
- [uv](https://docs.astral.sh/uv/) for dependency and tool management.
- An NVIDIA GPU with a working CUDA driver and roughly 3 GB of free video memory (VRAM).
- Linux or Windows.

Confirm the GPU is visible before you start:

```bash
nvidia-smi
```

If that command lists your card and a driver version, the driver is loaded. macOS, AMD GPUs, and Apple Silicon are unsupported - the stack is CUDA-only and raises at startup without it. For the reasoning behind a GPU-only design, see the [architecture overview](architecture.md).

## Install the package

To add vaultspec-rag as a dependency of an existing project, run:

```bash
uv add vaultspec-rag
```

To install it as a standalone tool instead, run:

```bash
uv tool install vaultspec-rag
```

The commands in this guide use the `uv run` prefix, which runs the command-line interface (CLI) inside the project's environment. If you installed the standalone tool, drop the prefix and call `vaultspec-rag` directly.

## Provision dependencies with the install command

The `install` command enrolls the workspace and provisions three external dependencies:

```bash
uv run vaultspec-rag install
```

By default it does three things:

- Configures the GPU (cu130) PyTorch build as a package source in `pyproject.toml`. This reports `configured, sync pending` - it edits the project config but does not download PyTorch.
- Ensures the dense, sparse, and reranker model files are present in the Hugging Face cache.
- Downloads and verifies the pinned Qdrant server binary.

The PyTorch step prompts before it edits `pyproject.toml`. For non-interactive installs, pass `--yes` to skip the prompt - unless you also pass `--no-torch-config`.

Read the per-dependency outcome report using the shared sync vocabulary: `created` (downloaded), `updated`, `unchanged` (already present), `skipped`, and `failed`. The run is idempotent, so re-running a satisfied dependency reports `unchanged` with no network call.

## Pull the GPU build

The `install` command *configures* the GPU PyTorch build but doesn't *fetch* it. After install configures the PyTorch source, run a sync to fetch the GPU build:

```bash
uv sync
```

This step is required. Until you run it, the configured cu130 source is recorded in `pyproject.toml` but PyTorch is not yet installed. To fold the sync into setup, pass `--sync`, which runs `uv sync --reinstall-package torch` after configuring the source.

## Choose a lighter setup

The defaults provision the supervised Qdrant server for higher throughput under concurrent load. To trim or opt out of the provisioning steps, use these conditional flags.

- If you want a lighter, server-free install, pass `--local-only`. It selects the embedded on-disk store, skips the Qdrant binary download, and persists the local backend so a later `server start` honors it. Throughput is lower under concurrent load. See the [backends guide](backends.md) for the trade-offs.
- To skip an individual dependency, pass `--skip-torch`, `--skip-models`, or `--skip-qdrant`. Each maps onto the `install` command's skip set; `--skip-qdrant` is redundant under `--local-only`, which already drops the Qdrant step.
- If you manage the GPU build yourself, pass `--no-torch-config` to leave `pyproject.toml` untouched.
- To preview the full provisioning report without writing anything, pass `--dry-run`. The dry run reports `preview only` for each step and never prompts, so it's independent of the confirmation prompt.

## Verify the install

Check the installed version:

```bash
uv run vaultspec-rag --version
```

This branch reports `0.2.20`.

Run the readiness report, which checks PyTorch CUDA, the model cache, and the Qdrant binary and server:

```bash
uv run vaultspec-rag server doctor
```

A healthy result reads `Readiness: ready for requests`, with each dependency line showing its status. In server mode, the `qdrant` line is ready once a binary resolves and no supervised child is dead; in local-only mode, an absent binary is reported ready because no server is needed. Add `--json` for a machine-readable envelope.

Check the project's index location and compute device:

```bash
uv run vaultspec-rag status
```

A healthy result names your GPU as the compute device and shows the index data location, even before you've indexed anything.

## Troubleshooting

If `server doctor` reports the `torch` line as not ready and CPU-only, run `uv sync` (or `uv run vaultspec-rag install --sync`). Install configures the GPU build, but the sync fetches it; a CPU-only build means the sync hasn't run yet.

If `nvidia-smi` shows no GPU, the driver isn't loaded. Fix the driver before installing - the stack raises at startup without CUDA and has no CPU fallback.

If install refuses to edit your project config and exits non-zero, it ran the PyTorch step without consent. Re-run with `--yes` to approve the edit, or with `--no-torch-config` to skip it and manage the GPU build yourself.

If `server start` fails because the Qdrant server binary is missing, provision it:

```bash
uv run vaultspec-rag server qdrant install
```

Or run the service without the server:

```bash
uv run vaultspec-rag server start --local-only
```

If the Qdrant download fails with a checksum mismatch, the archive didn't match the committed digest and the partial file is deleted. Retry the download. On an air-gapped host, register your own executable with `server qdrant install --binary PATH`.

## First run notes

The first index or search downloads the dense, sparse, and reranker model files once, so it runs slower than later searches. If a smaller card runs out of memory, tune the embedding batch sizes. If models appear to re-download every run, point the Hugging Face cache (`HF_HOME`) at a persistent location. See the [configuration guide](configuration.md) for the relevant variables.

## Uninstall

Remove the package:

```bash
uv remove vaultspec-rag
```

Revert the project-config change that install made to `pyproject.toml`:

```bash
uv run vaultspec-rag uninstall
```

Delete the managed Qdrant installs (index data is never touched):

```bash
uv run vaultspec-rag server qdrant clean --yes
```

The `--yes` flag is required to delete; without it the command prints a preview only. Pass `--keep-current` to preserve the pinned version. For the full flag set, see the [CLI reference](cli.md).

## Where to go next and where to get help

- [Getting started](getting-started.md) walks through your first index and search.
- [Search and index](search-and-index.md) covers query syntax, filters, and indexing.
- [Backends](backends.md) compares the supervised server and the embedded store.
- For support channels, see [support and help](../README.md#support-and-help).
