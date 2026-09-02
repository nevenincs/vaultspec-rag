# Installation

This guide covers how to install the package, provision its dependencies, verify the install, recover from setup failures, and uninstall. For what vaultspec-rag is and why it needs an accelerator, see the [architecture overview](architecture.md). For a guided first run afterward, see the [getting started guide](getting-started.md).

## Before you begin

You need:

- CPython 3.13 or 3.14. The runtime accepts that range and rejects anything outside it at import; 3.15 and later are refused until the test matrix covers them.

- [uv](https://docs.astral.sh/uv/) for dependency and tool management.

- A supported accelerator: an NVIDIA GPU with a working CUDA driver and roughly 3 GB of free video memory (VRAM), or Apple silicon with MPS. The measured Apple silicon floor is 8 GiB of unified memory. CPU-only and AMD GPU hosts are unsupported.

- Linux, Windows, or Apple silicon macOS for Python installs. The published Linux binaries state a glibc floor, because
  a binary links against whatever C library built it and a bare "Linux" is not
  a promise a download can keep:

  | binary                      | requires                                               | covers                                                                              |
  | --------------------------- | ------------------------------------------------------ | ----------------------------------------------------------------------------------- |
  | `x86_64-unknown-linux-gnu`  | glibc 2.28                                             | Debian 10+, Ubuntu 20.04+, RHEL 8+, Amazon Linux 2023                               |
  | `aarch64-unknown-linux-gnu` | glibc 2.28, or 2.39 if built before this floor dropped | Debian 10+, Ubuntu 20.04+, RHEL 8+, Amazon Linux 2023 (older builds: Ubuntu 24.04+) |

  On an older distribution the binary does not start, and the error names a
  missing symbol version rather than the distribution being too old — so it is
  worth checking `ldd --version` first. Installing from PyPI with `uv` has no
  such floor and works wherever the Python and accelerator requirements above are met.

  The two floors match from the first release that builds aarch64 in the same
  pinned image x86_64 uses. Earlier aarch64 downloads were built on a host whose
  own glibc was 2.39 and still require it, so the floor is a property of the
  binary you downloaded rather than of the project. If an older aarch64 download
  refuses to start, that is this difference and a current one will work.

On Linux or Windows, confirm the NVIDIA GPU is visible before you start:

```bash
nvidia-smi
```

If that command lists your card and a driver version, the driver is loaded. On Apple silicon, macOS supplies the GPU driver and PyTorch's standard macOS wheel exposes MPS; no CUDA install is involved. vaultspec-rag refuses to start if neither CUDA nor MPS is available, and it refuses MPS when `PYTORCH_ENABLE_MPS_FALLBACK` enables CPU execution. For the accelerator-only design, see the [architecture overview](architecture.md).

## Install the package

Try GPU setup now, directly from PyPI:

```bash
uvx --from "vaultspec-rag[gpu]" vaultspec-rag install
```

Runs `install` in an ephemeral `uv` environment: it enrolls the current directory as a workspace, provisions the platform PyTorch build, downloads the search models, and fetches the pinned Qdrant server binary, prompting before it edits any config (see [Provision dependencies with the install command](#provision-dependencies-with-the-install-command) below). The `[gpu]` extra is required for local inference; a bare package deliberately omits that stack. Linux and Windows select the CUDA source, while its marker leaves macOS on the standard MPS-capable wheel. For a lasting install, use one of the paths below.

To add vaultspec-rag as a dependency of an existing project, run:

```bash
uv add "vaultspec-rag[gpu]"
```

On Linux or Windows, install it as a standalone tool by pinning the CUDA torch wheel as a `--with` requirement. The command is environment-specific - the wheel names a python version, ABI, platform, and torch release - so do not copy it from documentation: `vaultspec-rag server start` and `vaultspec-rag install` print the exact command derived from your interpreter and installed torch whenever they detect a CPU-only tool environment. For orientation, the shape it takes (here Python 3.13, torch 2.13.0, Windows) is:

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.13.0%2Bcu130-cp313-cp313-win_amd64.whl"
```

The `--python` request must match the wheel's `cp3XX` tag (both are recorded in the tool receipt): without it, uv resolves the tool env on its default python, and a default that differs from the wheel's interpreter - a newer version, or a free-threaded build - fails the install on a tag mismatch. The `--with` pin matters: uv records it in the tool receipt and re-applies it on every `uv tool upgrade`, so torch keeps resolving to the GPU (cu130) wheel. Without it, every upgrade or forced reinstall re-resolves torch from PyPI and silently replaces the GPU build with a CPU-only wheel that the service refuses to start with. Do not rely on `--index` instead: current uv (verified on 0.11.x) does not record `--index` in the tool receipt, so an upgrade silently drops it. The project-scoped pin that `vaultspec-rag install` writes into `pyproject.toml` never reaches tool environments, and uv's `--torch-backend` selector is `uv pip`-only.

If a tool environment has already lost its GPU torch, repair it in place (this is undone by the next upgrade; the `--with` pin above is the durable fix):

```bash
uv pip install --python "<tool-env python>" --reinstall --torch-backend=cu130 torch
```

On Apple silicon, install the standalone tool normally. The standard macOS
PyTorch wheel supplies MPS and no CUDA receipt pin is needed:

```bash
uv tool install --python 3.13 "vaultspec-rag[mcp]"
vaultspec-rag install
```

Two tool-lifecycle warnings:

- Stop the service before `uv tool install --force` or an upgrade that replaces the environment. The running service's executable holds the tool's `Scripts` directory, so a forced reinstall fails half-way ("Access is denied") and leaves the environment broken.
- After such a partial failure, `uvx vaultspec-rag` can silently fall back to a cached ephemeral environment (a `uv` cache path containing `archive-v0`) instead of the installed tool. `server start` warns loudly when it detects this; reinstall the tool with the service stopped to recover.

The commands in this guide use the `uv run` prefix, which runs the command-line interface (CLI) inside the project's environment. If you installed the standalone tool, drop the prefix and call `vaultspec-rag` directly.

## Install the standalone binaries

Once a binaries release has published, `vaultspec-rag` and `vaultspec-search-mcp` are also available as standalone binaries that need no Python toolchain on the machine:

```powershell
scoop bucket add vaultspec-rag https://github.com/nevenincs/vaultspec-rag
scoop install vaultspec-rag
```

```sh
brew tap nevenincs/vaultspec-rag https://github.com/nevenincs/vaultspec-rag
brew install vaultspec-rag
```

**Windows and Linux only, and the accelerator requirement is unchanged.** The standalone packaging lane does not currently publish a macOS artifact or offer a macOS formula. Apple silicon users install the Python project or tool described above; MPS runtime support does not imply a standalone macOS binary.

The binaries bootstrap the **same accelerated torch build this project resolves** - the `cu130` wheel, pinned from `uv.lock`, so the binary cannot drift onto a different torch than `uv sync` installs. That pin is load-bearing rather than cosmetic: `tool.uv.sources` is a workspace setting, not wheel metadata, so it does not survive into an install of the published wheel from PyPI. Without it the bootstrap resolves plain PyPI torch, which on Windows declares no CUDA dependency at all - and the service then refuses to start, exactly as it does for a CPU-only tool environment.

First launch is a large download: about 1.8 GB on Windows, 500 MB on Linux. That is the same download `uv tool install` with the torch pin performs; the binary does not add to it, it just does it on first run.

## Provision dependencies with the install command

The `install` command enrolls the workspace and provisions three external dependencies:

```bash
uv run vaultspec-rag install
```

By default it does three things:

- Configures the CUDA (cu130) PyTorch build as a Linux/Windows-only package source in `pyproject.toml`. This reports `configured, sync pending`. The source marker is inactive on macOS, where normal dependency resolution installs the MPS-capable standard wheel.
- Ensures the dense, sparse, and reranker model files are present in the Hugging Face cache.
- Downloads and verifies the pinned Qdrant server binary.

The PyTorch config step prompts before it edits `pyproject.toml`. For non-interactive installs, pass `--yes` to skip the prompt, unless you also pass `--no-torch-config`. The resulting entry is harmless on macOS because its platform marker excludes Darwin.

Read the per-dependency outcome report using the shared sync vocabulary: `created` (downloaded), `updated`, `unchanged` (already present), `skipped`, and `failed`. The run is idempotent, so re-running a satisfied dependency reports `unchanged` with no network call.

## Choose a provisioning mode

The `install` command records how vaultspec-rag is placed in your workspace and, from that, how its integration server is launched. Pass `--mode` to choose one of three placements:

```bash
uv run vaultspec-rag install --mode tool
```

- `tool` is the standalone placement. The integration server launches through an ephemeral `uvx` invocation, independent of any project environment. This is the default when your project does not depend on vaultspec-rag.
- `dependency` is for a project that lists vaultspec-rag in its runtime dependencies. The server launches through `uv run` inside the project environment. A runtime dependency ships with your project's published distribution.
- `dev` is for a project that keeps vaultspec-rag in its default development dependency group. It launches exactly like `dependency` but records that the placement is development-only and will not ship with a published distribution.

With no `--mode` flag, the placement is detected from your `pyproject.toml`: a runtime dependency resolves to `dependency`, a default dev-group entry resolves to `dev`, and anything else falls through to the `tool` default. An explicit `--mode dependency` or `--mode dev` with no `pyproject.toml` to declare against is refused rather than guessed.

The chosen placement is committed to `.vaultspec/workspace.json`, a per-package declaration shared with vaultspec-core. Each package records its own mode there, so a workspace that installs vaultspec-core in one placement and vaultspec-rag in another keeps both choices side by side without one overwriting the other.

The `--mode` placement is independent of the `--local-only` backend choice covered below: `--mode` selects where vaultspec-rag lives and how its server launches, while `--local-only` selects the storage backend. You can combine any mode with or without `--local-only`.

## Install the platform PyTorch build

The install is not complete until you run `uv sync`. The `[gpu]` extra supplies the local inference libraries. On Linux and Windows, `install` records the cu130 PyTorch source; on macOS, the same sync resolves the standard MPS-capable wheel. Until the environment has a supported accelerator build, it cannot run searches:

```bash
uv sync
```

To fold the sync into setup, pass `install --sync`, which runs `uv sync --reinstall-package torch` after the config step.

## Choose a lighter setup

The defaults provision the supervised Qdrant server for higher throughput under concurrent load. To trim or opt out of the provisioning steps, use these conditional flags.

- If you want a lighter, server-free install, pass `--local-only`. It selects the embedded on-disk store, skips the Qdrant binary download, and persists the local backend so a later `server start` honors it. It does not change Python dependencies, CUDA, or model downloads. Throughput is lower under concurrent load. See the [backends guide](backends.md) for the trade-offs.
- To skip an individual dependency, pass `--skip-torch`, `--skip-models`, or `--skip-qdrant`. Each maps onto the `install` command's skip set; `--skip-qdrant` is redundant under `--local-only`, which already drops the Qdrant step.
- If you manage PyTorch yourself, pass `--no-torch-config` to leave `pyproject.toml` untouched.
- To preview the full provisioning report without writing anything, pass `--dry-run`. The dry run reports `preview only` for each step and never prompts, so it's independent of the confirmation prompt.

For the complete `install` flag set, see the [CLI reference](cli.md).

## Choose the package footprint

A bare `uv add vaultspec-rag` or `uv tool install vaultspec-rag` installs the control plane only. It does not resolve torch, sentence-transformers, transformers, or Linux NVIDIA packages, so it avoids the roughly 5 GB CUDA footprint reported for a GPU install. It can run service-control and diagnostic commands, but it cannot index or search locally.

For local GPU inference, install `vaultspec-rag[gpu]` and run `install --sync`. On Linux this intentionally resolves the CUDA stack; budget roughly 5 GB for those packages and several additional gigabytes for the first model download. `--local-only` is independent of this choice: it saves the managed Qdrant binary only.

## Verify the install

Check the installed version:

```bash
uv run vaultspec-rag --version
```

This reports `vaultspec-rag v0.4.21`. <!-- x-release-please-version -->

Run the readiness report, which checks PyTorch and the resolved accelerator, the model cache, and the Qdrant binary and server:

```bash
uv run vaultspec-rag server doctor
```

A healthy result reads `Readiness: ready for requests`, with each dependency line showing its status. In server mode, the `qdrant` line is ready once a binary resolves and the supervised child is running. In local-only mode, an absent binary is reported ready because no server is needed. Add `--json` for a machine-readable envelope.

When a workspace has a committed provisioning mode, `server doctor` also reports a `Provisioning (vaultspec-rag)` block naming the declared mode, whether the deployed integration server matches it, and whether the running vaultspec-core meets the version floor your declaration requires. A deployed server that no longer matches the declared mode is a warning; a vaultspec-core below the required floor is an error. Re-run `install --mode` (or `install --upgrade`) to bring the deployed launch back into line.

Check the project's index location and compute device:

```bash
uv run vaultspec-rag status
```

A healthy result names `cuda` or `mps` as the compute backend and shows the index data location, even before you've indexed anything. CUDA memory is reported as discrete VRAM; MPS memory is reported as unified memory and is never represented as zero VRAM.

## Troubleshooting

If `server doctor` reports the `torch` line as not ready and CPU-only on Linux or Windows, run `uv sync` (or `uv run vaultspec-rag install --sync`). On Apple silicon, sync the standard wheel and check that `torch.backends.mps.is_available()` is true.

If `nvidia-smi` shows no GPU, the NVIDIA driver is not loaded. Fix it before installing. On Apple silicon, an unavailable MPS backend or `PYTORCH_ENABLE_MPS_FALLBACK=1` is an explicit startup failure. Neither platform falls back to CPU.

If the PyTorch step needs consent it does not have, install refuses to edit `pyproject.toml` and exits non-zero. Re-run with `--yes` to approve the edit, or with `--no-torch-config` to skip it and manage PyTorch yourself.

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

The first index or search downloads the dense, sparse, and reranker model files once, so it runs slower than later searches. If accelerator memory is exhausted, see [tuning for memory and speed](configuration.md#tuning-for-memory-and-speed). On MPS, memory is unified with the rest of the system rather than dedicated VRAM. If models appear to re-download every run, point the Hugging Face cache (`HF_HOME`) at a persistent location. See the [configuration guide](configuration.md) for the relevant variables.

## Upgrade

To move to a new release, bump the dependency and sync:

```bash
uv add --upgrade vaultspec-rag
uv sync
```

`uv sync` refetches the platform PyTorch build if it changed. Two optional follow-ups apply only when a release changes bundled content. Run `uv run vaultspec-rag install --upgrade` to refresh the bundled rules and integration files. If the release pins a newer Qdrant version, run `uv run vaultspec-rag server qdrant install --upgrade`. There is no migration step and no automatic reindex. If a release notes a changed embedding or reranker model, reindex by hand with `index --rebuild`.

One refresh matters for MCP launch hygiene: workspaces set up before the tokenized launch format still carry a static MCP seed (`.vaultspec/mcps/vaultspec-rag.builtin.json` with a literal `uv run vaultspec-search-mcp` entry) that bypasses vaultspec-core's launch renderer. `install --upgrade` rewrites that seed to the tokenized form, which the renderer turns into a side-effect-free launch for the workspace's declared mode (including the `[mcp]` extra spec that tool mode needs). If an assistant's MCP config predates the refresh, re-run the client's MCP setup afterwards so the rendered entry lands in its config.

The `server updates` commands are unrelated to upgrades. They control the automatic-reindex watcher, covered in the [service mode guide](service-mode.md).

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

## Where to go next

- [Getting started](getting-started.md) walks through your first index and search.
- [Search and index](search-and-index.md) covers query syntax, filters, and indexing.
- [Backends](backends.md) compares the supervised server and the embedded store.
- For support channels, see [support and help](../README.md#support-and-help).
