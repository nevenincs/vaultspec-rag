# How to install and configure vaultspec-rag

This guide covers hardware prerequisites, package install, the
`vaultspec-rag install` command, and what to do when each step fails.

## Hardware prerequisites

vaultspec-rag requires:

- An NVIDIA GPU with CUDA support. The tool raises an error at startup
  if it can't find a GPU; there's no CPU fallback.
- About 3 GB of free GPU memory. The three models the tool loads use
  roughly 1.9 GB; the rest covers working memory and OS overhead.
- Linux or Windows. Both are tested. macOS is not supported because the
  GPU stack is CUDA-specific.

If you don't have an NVIDIA GPU, vaultspec-rag won't run on your
machine. See [Why a GPU is required](../explanation/why-gpu.md).

## Install the package

Add vaultspec-rag to your project with uv:

```sh
uv add vaultspec-rag
```

If you need to install it as a standalone tool rather than a project
dependency, use uv's tool surface:

```sh
uv tool install vaultspec-rag
```

Either form pulls the same package. The rest of this guide assumes the
project-dependency form; if you used `uv tool install`, drop the
`uv run` prefix from every command shown.

## Run the install command

After `uv add`, run:

```sh
uv run vaultspec-rag install
```

This patches your `pyproject.toml` to declare the cu130 PyTorch index,
so subsequent `uv sync` runs pull the GPU build of PyTorch. The command
prompts before making changes; review the diff and confirm with **y**.

To approve all prompts up front:

```sh
uv run vaultspec-rag install --yes
```

To skip the PyTorch configuration entirely (because you've already set
it up, or because your project pins PyTorch from another source):

```sh
uv run vaultspec-rag install --no-torch-config
```

After the install command finishes, run:

```sh
uv sync
```

uv installs the GPU build of PyTorch using the newly declared index.
This download is large (around 2 GB) and only happens once per machine.

## Verify the install

Confirm the binary works:

```sh
uv run vaultspec-rag --version
```

Confirm the GPU stack works:

```sh
uv run vaultspec-rag status
```

The status output includes a GPU row. If the row shows a real device
name (for example `NVIDIA RTX 4080`), you're ready. If it shows `N/A`
or an error, your CUDA install isn't visible to PyTorch.

## Configuration

vaultspec-rag reads optional configuration from environment variables.
See the [Configuration reference](../reference/configuration.md) for
the complete list with defaults.

## When things go wrong

### "No GPU available"

vaultspec-rag couldn't find a CUDA device. Check both:

- `nvidia-smi` runs and lists your GPU. If not, your NVIDIA driver is
  missing or broken.
- PyTorch is the CUDA build. Run
  `uv run python -c "import torch; print(torch.cuda.is_available())"`.
  If it prints `False`, you have the CPU build. Re-run
  `uv run vaultspec-rag install` and then `uv sync`.

### "PyTorch is not installed"

You ran `vaultspec-rag` before `uv sync` picked up the cu130 build.
Run `uv sync`, then retry the command.

### Install declines to edit `pyproject.toml`

You answered **n** to the prompt, or the tool detected a conflict (an
existing `[[tool.uv.index]]` that targets a different PyTorch wheel).
Run:

```sh
uv run vaultspec-rag install --dry-run
```

This prints the proposed edit without writing. Compare against your
file. If the conflict is intentional, pass `--no-torch-config` to skip
the patch on every install.

### Out-of-memory errors during search or index

The default batch sizes target 16 GB of GPU memory. If your card has
less than 16 GB, lower the batch sizes via environment variables
before running the command:

```sh
VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE=16 \
  VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE=4 \
  uv run vaultspec-rag index
```

The defaults are `64` for `EMBEDDING_BATCH_SIZE` (outer batch) and `8`
for `EMBEDDING_ENCODE_BATCH_SIZE` (inner sub-batch passed to the
dense encoder). Smaller values use less memory at the cost of
indexing speed.

## Next steps

- [Run your first search](../tutorial/first-search.md) if you haven't
  yet.
- [Run as a background service](run-as-a-service.md) once you've
  confirmed the install works.
