# Installation

This page covers hardware requirements, the package install, the `install` command, verification, and what to do when each step fails. If you'd rather follow a guided walkthrough, see the [getting-started tutorial](getting-started.md).

## Hardware requirements

vaultspec-rag runs on the GPU. There is no CPU fallback.

- NVIDIA GPU with CUDA support
- About 3 GB of free GPU memory
- Linux or Windows
- No CPU fallback

CUDA is NVIDIA's GPU compute platform; the driver is what lets PyTorch and other tools talk to the card. To confirm CUDA is installed, run:

```bash
nvidia-smi
```

If the output lists your GPU and a driver version, CUDA is ready. If the command is missing or errors, install NVIDIA's driver first, then come back.

macOS, AMD GPUs, and Apple Silicon are not supported. For the reasoning behind the GPU requirement, see [architecture](architecture.md).

## Install the package

You can install vaultspec-rag as a project dependency or as a standalone tool.

As a project dependency, from the workspace root:

```bash
uv add vaultspec-rag
```

As a standalone tool:

```bash
uv tool install vaultspec-rag
```

The rest of this page assumes the project dependency form. For the standalone tool form, drop the `uv run` prefix from every command.

## Run the install command

Run the install command from the workspace root:

```bash
uv run vaultspec-rag install
```

This patches `pyproject.toml` so uv resolves the GPU build of PyTorch instead of the CPU build. The patch adds the `cu130` index, which is PyTorch's package name for the CUDA 13.0 build and is what NVIDIA's CUDA toolkit looks like to PyTorch. The command prompts for confirmation before editing `pyproject.toml`.

To skip the prompt:

```bash
uv run vaultspec-rag install --yes
```

To skip the patch entirely, if you manage PyTorch yourself:

```bash
uv run vaultspec-rag install --no-torch-config
```

After install, pull the GPU PyTorch build:

```bash
uv sync
```

## Verify the install

Confirm the binary works:

```bash
uv run vaultspec-rag --version
```

You should see a version line.

Confirm the GPU is visible:

```bash
uv run vaultspec-rag status
```

The status output should list a real GPU name. If you see `N/A` or an error in the GPU row, jump to troubleshooting.

## Configuration

vaultspec-rag reads optional configuration from environment variables. See [configuration](configuration.md) for the complete list and defaults.

## Troubleshooting

### No GPU available

If `vaultspec-rag status` reports no GPU, first confirm `nvidia-smi` works. If it does, PyTorch is likely the CPU build. Run `uv run vaultspec-rag install` to apply the cu130 patch, then `uv sync` to pull the GPU build.

### PyTorch is not installed

If `vaultspec-rag` errors with a missing PyTorch import, you ran it before `uv sync`. Run `uv sync` and retry.

### Install refuses to edit pyproject.toml

If the install command exits without applying the patch, either you declined the prompt or a conflicting PyTorch index is already configured. Use `--dry-run` to preview the change, or `--no-torch-config` to skip the patch and manage PyTorch yourself.

### Out-of-memory errors during search or index

If you see CUDA out-of-memory errors, your card has less memory than the defaults assume. Lower the batch sizes:

```bash
export VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE=32
export VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE=4
```

The defaults are 64 and 8. See [configuration](configuration.md) for the full list of tuning variables.

### First indexing run is much slower than subsequent runs

The first run downloads model files to the HuggingFace cache. Subsequent runs reuse the cached files. This is expected.

### Models keep re-downloading

If models download every run, the `HF_HOME` variable points to a path that does not persist between runs. This is common in containers without a mounted volume. Point `HF_HOME` at a persistent directory:

```bash
export HF_HOME=/path/to/persistent/dir
```

The default is `~/.cache/huggingface`. See [configuration](configuration.md) for the full HuggingFace cache variables.

## Uninstall

To remove the package:

```bash
uv remove vaultspec-rag
```

To revert the `pyproject.toml` patch:

```bash
uv run vaultspec-rag uninstall
```

For the full uninstall flag list, see the [CLI reference](cli.md).

## Need help?

If you're stuck, see the [Support](../README.md#support-and-help) section of the repository README. In a bug report, include the vaultspec-rag version, your OS, the GPU model, the exact command you ran, and the full stderr output.
