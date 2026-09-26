# Installing vaultspec-rag

vaultspec-rag searches a repository's source code and its design decision records by
meaning, from the terminal or from an AI coding assistant. Decision records are
markdown files kept in a `.vault/` folder. The repository setup creates the folder, and
code search works while it's empty. This guide installs vaultspec-rag on one machine and
connects repositories to it.

vaultspec-rag needs a supported graphics processing unit (GPU): an NVIDIA GPU with CUDA,
NVIDIA's GPU computing platform, on Linux or Windows, or Apple silicon on macOS. It
doesn't run on a central processing unit (CPU) or on AMD GPUs. The
[architecture overview](architecture.md#why-vaultspec-rag-needs-a-gpu) explains why a
GPU is required, and the [glossary](glossary.md) defines the terms this guide uses.

<p id="choose-an-install-route"></p>
<p id="choose-what-this-environment-runs"></p>

## Choose an installation

Every machine that uses vaultspec-rag runs one background [service](glossary.md#service).
The service runs the search models on the GPU, and the `vaultspec-rag server` commands
control it. Two kinds of installation work with it:

- A [host installation](glossary.md#host-installation) carries the `gpu` extra. It runs
  the models and is the only kind of installation that can start the service.
- A [client installation](glossary.md#client-installation) carries no `gpu` extra. It
  loads no models and sends every request to the service a host installation started.

Run every installation under the same user account. A client can't reach a service
that another account started.

Find out where this machine stands:

- If the `vaultspec-rag` command isn't found, and no project on this machine depends on
  `vaultspec-rag[gpu]`, no host installation exists yet.
  [Set up a host installation](#set-up-a-host-installation).
- If `vaultspec-rag server status` reports the service stopped, don't reinstall. Start
  the service from the host installation with `vaultspec-rag server start`.
- If `vaultspec-rag server status` reports the service running,
  [set up each repository](#set-up-each-repository) from the host installation.

Choose where the host installation lives:

- [Install as a standalone tool](#install-as-a-standalone-tool) by default. One
  installation serves every repository on the machine, in any language.
- [Install as a project dependency](#install-as-a-project-dependency) when one Python
  project's environment should run the service.
- [Install a prebuilt binary](#install-a-prebuilt-binary) when the machine has no Python
  toolchain.
- [Try a temporary run](#try-a-temporary-run) before installing anything. On Windows, it
  can't start the service.

If a Python project managed with uv must list vaultspec-rag without GPU packages,
[add a client](#add-a-client-to-a-python-project) to it. Collaborators' AI assistants
then launch the search tools from the project's environment. Every collaborator still
needs their own host installation, running exactly the release the project pins. The
[package table](#packages-and-what-they-can-run) lists what each package can run.

## Set up a host installation

### What you need before you start

- A supported GPU. On Linux and Windows, install an NVIDIA driver that supports CUDA 13.
  On macOS, the system provides the driver.
- The system memory (RAM), disk, and GPU memory of a resource profile, from the
  following table.
- Several gigabytes of free disk for the model download, which every repository shares.
- Network access to the Python Package Index (PyPI), the PyTorch download server
  (`download.pytorch.org`) on Windows and Linux, the Hugging Face model server, and
  GitHub release downloads.

| Profile                     | Total system RAM | Free index-store space | Free CUDA memory at startup |
| --------------------------- | ---------------- | ---------------------- | --------------------------- |
| `managed-service` (default) | 16 GiB           | 8 GiB                  | 12 GiB                      |
| `embedded-local`            | 8 GiB            | 5 GiB                  | 6 GiB                       |

Indexing compares the RAM figure with the total the operating system reports, which is
usually a little below the installed amount. A machine with exactly 16 GiB installed
can fall short of the default profile. The CUDA figures are the default model-loading
admission limits; they don't apply to Apple silicon. See
[index resource bounds and memory ceilings](configuration.md#index-resource-bounds-and-memory-ceilings).

Use `embedded-local` for smaller corpora or a machine with 8 GiB of unified memory. It
lowers how much one repository can index, and it's the only profile that accepts the
local-only backend. It also works with the managed Qdrant server.

To select it, set `VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local` in the
environment that starts the service. Setting it only in a client's shell doesn't
configure the service. While the service runs, `vaultspec-rag status --verbose` shows
the profile it uses and its corpus limits.

The Python routes also need [uv](https://docs.astral.sh/uv/getting-started/installation/)
and CPython 3.13 or 3.14. A prebuilt binary needs neither.

### Confirm your GPU is visible

On Linux or Windows, run:

```bash
nvidia-smi
```

If it lists your card, the driver is loaded. The `CUDA Version` it prints is the newest
CUDA the driver supports, and it must be 13.0 or later. If `nvidia-smi` isn't found,
doesn't list your card, or reports an older CUDA version, install or update the NVIDIA
driver.

On Apple silicon, macOS supplies the driver, and the readiness report confirms the GPU
once vaultspec-rag is installed. The service uses Metal Performance Shaders (MPS),
Apple's GPU framework. It refuses MPS while `PYTORCH_ENABLE_MPS_FALLBACK` lets
operations run on the CPU, so unset that variable in the environment that starts the
service. Neither platform falls back to the CPU.

### The model cache and its first download

By default, search uses a sparse model,
[`naver/splade-v3`](https://huggingface.co/naver/splade-v3), which matches exact terms.
The model is gated, and its CC-BY-NC-SA-4.0 licence restricts commercial use and adds
attribution and share-alike obligations.

If the licence doesn't fit your use, or you don't want a Hugging Face account, turn the
sparse model off and skip the login:

- Set `VAULTSPEC_RAG_SPARSE_ENABLED=0` persistently in the environment that runs the
  repository setup and starts the service.
- Indexes and searches then use dense vectors only, so exact-term matching and hybrid
  fusion are absent. Dense embedding and reranking still run on the GPU.
- After switching, rebuild existing indexes so stored vector schemas match.

Otherwise, give the account that runs vaultspec-rag access before the first download:

1. Sign in to Hugging Face, open the model page, and accept its access conditions.

1. Log in:

   ```bash
   uvx --from huggingface_hub hf auth login
   ```

   If the `hf` command is already on your `PATH`, `hf auth login` works too. A
   standalone tool exposes only vaultspec-rag's own commands, so `hf` isn't on the
   `PATH` there.

Instead of logging in, set `HF_TOKEN` persistently in your user environment, so both
the repository setup and `vaultspec-rag server start` see it. `HF_TOKEN` takes
precedence over the stored login. A token alone isn't enough until its account has
accepted the model's conditions.

The repository setup's model download, `server warmup`, and the `server doctor` cache
check all honour `VAULTSPEC_RAG_SPARSE_ENABLED=0`. With it, they never download, warm,
or probe the gated model, so a dense-only configuration needs no Hugging Face login.
The other two models still download from the Hugging Face Hub, and the repository
setup may still print a token warning; ignore it.

Model files use the [Hugging Face cache](configuration.md#hugging-face-cache). To choose
where downloads go, set `HF_HOME` to a persistent location before the repository setup.
See [model selection and toggles](configuration.md#model-selection) for the full
reference.

<p id="install-with-python"></p>
<p id="installing-it-as-a-standalone-tool"></p>

### Install as a standalone tool

Choose this route by default. The following commands install the host and the Model
Context Protocol (MCP) adapter that AI assistants launch. The Windows and Linux commands
pin the CUDA build of PyTorch in the tool's receipt, so later upgrades keep it.

Windows x86-64:

```powershell
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.14.0%2Bcu130-cp313-cp313-win_amd64.whl"
```

Linux x86-64 (glibc 2.28 or newer):

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.14.0%2Bcu130-cp313-cp313-manylinux_2_28_x86_64.whl"
```

Apple silicon macOS:

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]"
```

For other Python versions or Linux architectures, install without the `--with` pin,
then [pin the GPU build](#pin-the-gpu-build). If uv reports its executables directory
isn't on your `PATH`, run `uv tool update-shell` and open a new terminal.

Run every later command as `vaultspec-rag`. Continue with
[set up each repository](#set-up-each-repository).

<p id="adding-it-to-a-project"></p>

### Install as a project dependency

Choose this route when one Python project's environment should run the service, and
collaborators share its pinned version. From the project root, run:

```bash
uv add "vaultspec-rag[gpu]"
```

Run every later command as `uv run vaultspec-rag` from the project root. The repository
setup then asks to add a CUDA package source to `pyproject.toml`; see
[set up each repository](#set-up-each-repository).

<p id="trying-it-without-commitment"></p>
<p id="run-without-installing-a-tool"></p>

### Try a temporary run

On Windows, a temporary run gets PyPI's CPU-only PyTorch, so it can set up a repository
but can't start the service. Use the standalone tool there.

To try vaultspec-rag before installing it, prefix each command with
`uvx --from "vaultspec-rag[gpu]"`. For example, from a repository's root:

```bash
uvx --from "vaultspec-rag[gpu]" vaultspec-rag install --no-torch-config
```

`uvx` uses a temporary environment, but the command still configures the repository.

<p id="install-without-python"></p>
<p id="installing-a-prebuilt-binary"></p>
<p id="which-sections-you-still-need"></p>

### Install a prebuilt binary

Choose this route when the machine has no Python toolchain. A binary is always a host
installation. The release publishes Windows x86-64, Linux x86-64 and ARM64, and Apple
silicon macOS archives. Intel Macs are unsupported on every route, because PyTorch
publishes no Intel macOS build.

`vaultspec-rag` and `vaultspec-search-mcp` ship in one archive per target. The archive
embeds CPython 3.13, and on first launch it installs the vaultspec-rag wheel and its
runtime dependencies.

#### Install with Scoop or Homebrew

The channels live in the account tap, `nevenincs/homebrew-tap`. Add that tap once, then
install the product for your platform.

On Windows:

```powershell
scoop bucket add nevenincs https://github.com/nevenincs/homebrew-tap
scoop install vaultspec-rag
```

On Linux or Apple silicon macOS:

```sh
brew tap nevenincs/tap https://github.com/nevenincs/homebrew-tap
brew install vaultspec-rag
```

Each channel pins one archive URL and SHA-256 digest for the selected target, and puts
the `vaultspec-rag` and `vaultspec-search-mcp` commands on your `PATH`.

#### Download an archive directly

On Linux, first check
[which Linux binary your distribution can run](#which-linux-binary-your-distribution-can-run).
Then use the release asset for your operating system and architecture, replacing
`<release>` with the release number.

| Platform            | Release asset                                               |
| ------------------- | ----------------------------------------------------------- |
| Windows x86-64      | `vaultspec-rag-v<release>-x86_64-pc-windows-msvc.zip`       |
| Linux x86-64        | `vaultspec-rag-v<release>-x86_64-unknown-linux-gnu.tar.gz`  |
| Linux ARM64         | `vaultspec-rag-v<release>-aarch64-unknown-linux-gnu.tar.gz` |
| macOS Apple silicon | `vaultspec-rag-v<release>-aarch64-apple-darwin.tar.gz`      |

1. Open the [release page](https://github.com/nevenincs/vaultspec-rag/releases) and
   download the archive and `SHA256SUMS` from the same `vaultspec-rag-v<release>`
   release. The checksum file has one line per release asset.

1. Compute the archive's digest and find its line in `SHA256SUMS`:

   | Platform           | Compute the archive digest                                | Find the matching release entry                           |
   | ------------------ | --------------------------------------------------------- | --------------------------------------------------------- |
   | Windows PowerShell | `Get-FileHash -Algorithm SHA256 -LiteralPath .\<archive>` | `Select-String -Path .\SHA256SUMS -SimpleMatch <archive>` |
   | Linux              | `sha256sum <archive>`                                     | `grep -F -- "  <archive>" SHA256SUMS`                     |
   | macOS              | `shasum -a 256 <archive>`                                 | `grep -F -- "  <archive>" SHA256SUMS`                     |

   If the digests differ, don't extract or run the archive. Download both files again
   from the same release and repeat the check.

1. Extract the verified archive and check the binary runs.

   Windows PowerShell:

   ```powershell
   Expand-Archive -LiteralPath .\vaultspec-rag-v<release>-x86_64-pc-windows-msvc.zip `
     -DestinationPath .\vaultspec-rag
   .\vaultspec-rag\vaultspec-rag.exe --version
   ```

   Linux or macOS (substitute your asset's name):

   ```sh
   mkdir -p vaultspec-rag
   tar -xzf vaultspec-rag-v<release>-x86_64-unknown-linux-gnu.tar.gz -C vaultspec-rag
   chmod +x vaultspec-rag/vaultspec-rag vaultspec-rag/vaultspec-search-mcp
   ./vaultspec-rag/vaultspec-rag --version
   ```

1. Add the extracted folder to your `PATH`, so later steps can run `vaultspec-rag`.

To check each extracted file against the archive's manifest, see the
[archive layout](#inspect-the-archive-layout).

#### First launch requirements for binaries

On Windows and Linux, the binary installs the CUDA 13 PyTorch wheel pinned from the
project lockfile. On macOS, it installs PyPI's PyTorch, which carries MPS. The other
packages come from PyPI. First launch needs network access and enough disk space for
the PyTorch wheel and its runtime dependencies. The binary has no CPU mode.

A successful `vaultspec-rag --version` confirms the bootstrap completed. The archive
contains no model files or Qdrant binary: the repository setup downloads them.
[The model cache and its first download](#the-model-cache-and-its-first-download) and
every later step apply to a binary too.

<p id="set-up-a-project"></p>
<p id="what-the-install-command-provisions"></p>
<p id="install-less-than-the-default"></p>
<p id="choose-where-vaultspec-rag-lives"></p>
<p id="complete-the-install-with-a-sync"></p>

### Set up each repository

Run the repository setup once in the root of every repository you want to search. The
command is named `install`, but it sets up that repository rather than reinstalling the
package.

If the host installation is a standalone tool, a prebuilt binary, or a temporary run,
add `--no-torch-config`. The installation already carries its PyTorch, and the PyTorch
step only edits the repository's own `pyproject.toml`:

```sh
vaultspec-rag install --no-torch-config
```

If the host installation is a dependency of this project, run the setup through the
project:

1. Run the setup. It asks to add a CUDA package source to `pyproject.toml`; answer `y`,
   or pass `--yes` for an unattended run. On Windows, declining leaves PyPI's CPU-only
   PyTorch, which can't run the service.

   ```sh
   uv run vaultspec-rag install
   ```

1. Install the CUDA build and the `mcp` extra the setup adds:

   ```sh
   uv sync
   ```

The repository setup does three things:

- Adds the AI assistant integration: a rule, a skill, and the MCP server entry your
  assistant launches. See [MCP integration](mcp.md).
- Creates the `.vault/` folder if it's missing.
- On the first repository, downloads the search models and the Qdrant index server
  binary. Later repositories reuse both. The default configuration downloads three
  models, and a dense-only configuration downloads two. The first run downloads several
  gigabytes.

These flags change it:

- For terminal use without an AI assistant, add `--no-mcp`.
- To keep the index in the local-only backend instead of the managed Qdrant server, add
  `--local-only`, which also skips the Qdrant download. The backend is a choice for the
  whole service, not one repository. Start the service with
  `vaultspec-rag server start --local-only` every time. Set
  `VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local` where the service starts,
  because the default profile refuses the local-only backend. See
  [storage backends](backends.md).

The repository setup detects how the repository declares vaultspec-rag and records it in
`.vaultspec/workspace.json`. If the detection is wrong, correct it with `--mode`; see
the [install command reference](cli.md#install) for every flag and exit code.

<p id="verify-the-install"></p>

### Start and verify

Start the service from the host installation:

```bash
vaultspec-rag server start
```

The command loads the models and waits until the service is ready. Stop the service
with `vaultspec-rag server stop`. It doesn't restart by itself after a reboot, and
vaultspec-rag ships no autostart; the [service guide](service-mode.md) covers running it
at login.

Three commands answer different questions throughout this guide:

| Command                       | What it answers                                                                    |
| ----------------------------- | ---------------------------------------------------------------------------------- |
| `vaultspec-rag server status` | Is the service running? Add `--verbose` to see its release.                        |
| `vaultspec-rag server doctor` | Does this installation have what it needs, and does the service's release match?   |
| `vaultspec-rag status`        | What state is this repository's index in, and which installation runs the service? |

Check the version:

```bash
vaultspec-rag --version
```

This reports `vaultspec-rag v0.5.2`. <!-- x-release-please-version -->

Then run the readiness report:

```bash
vaultspec-rag server doctor
```

A healthy host installation reports PyTorch ready on a `cuda` or `mps` backend, every
configured model cached, and the Qdrant binary present. If a line reports a problem, see
[when something goes wrong](#when-something-goes-wrong). To interpret the full report,
see [verify the index](verification.md).

Next, index the repository and run a first search with the
[getting-started tutorial](getting-started.md#step-2-start-the-service-and-index-your-project).

## Add a client to a Python project

### What a client needs

- A host installation on this machine that already runs the service under your user
  account.

- The service's release. From the host installation, run this command and note the
  `Service release:` line:

  ```bash
  vaultspec-rag server status --verbose
  ```

- A project whose `requires-python` allows Python 3.13 or 3.14, which vaultspec-rag
  requires.

Pin the client to exactly the service's release: a client refuses a service from any
other release. A client needs no GPU, CUDA, PyTorch, or model download.

### Add and set up the client

From the project root:

1. Add the client to the development dependencies, pinned to the service's release.
   `uv add` also syncs the environment.

   If the project's AI assistant should get the search tools, add the `mcp` extra:

   ```bash
   uv add --dev "vaultspec-rag[mcp]==<release>"
   ```

   For terminal use without an AI assistant, add the plain package:

   ```bash
   uv add --dev "vaultspec-rag==<release>"
   ```

1. Set up the project. `--mode dev` makes the AI assistant launch the search tools from
   the project environment. Without it, a project the host installation already set up
   keeps launching the standalone tool.

   With the `mcp` extra:

   ```bash
   uv run vaultspec-rag install --mode dev
   ```

   With the plain package:

   ```bash
   uv run vaultspec-rag install --mode dev --no-mcp
   ```

   A client installation skips the PyTorch step and every download automatically. The
   output reports `PyTorch configuration: not needed (this installation is a client)`
   and each provisioning step as skipped.

Run the client as `uv run vaultspec-rag` from the project. If the host installation is
a standalone tool, a plain `vaultspec-rag` runs the host instead.

### Verify and use the client

Run the readiness report through the client:

```bash
uv run vaultspec-rag server doctor
```

It shows `release: <release> (matches this client)` for the running service, and
`torch: ready - not needed (this installation is a client)` for the client itself. If
the release doesn't match, repeat step 1 with the service's release. While the service
runs, `uv run vaultspec-rag status` describes the host installation that serves the
client, not the client.

Index and search with the same commands a host uses, prefixed with `uv run`; see the
[getting-started tutorial](getting-started.md). Start, stop, and upgrade the service
from the host installation.

## Upgrade

A client refuses a service from a different release, even a newer one. Upgrade the host
installation and every client together.

1. Close connected assistant sessions. The service may serve other repositories and
   assistants, so tell their users before stopping it. Then stop the service from the
   host installation:

   ```bash
   vaultspec-rag server stop
   ```

   If the command reports a failure, resolve it before continuing; see
   [the service guide's troubleshooting](service-mode.md#troubleshooting).

1. Upgrade the host installation with the command for its route:

   | Installation route | Upgrade command                                               |
   | ------------------ | ------------------------------------------------------------- |
   | Project dependency | `uv sync --upgrade-package vaultspec-rag`                     |
   | Standalone tool    | `uv tool upgrade vaultspec-rag`                               |
   | Scoop              | `scoop update vaultspec-rag`                                  |
   | Homebrew           | `brew upgrade vaultspec-rag`                                  |
   | Downloaded archive | Verify and extract the new release in place of the old folder |

   uv upgrades respect version constraints, and a standalone tool keeps the Python
   version and [GPU build pin](#pin-the-gpu-build) from its receipt. For a temporary
   run, follow [uv's version selection](https://docs.astral.sh/uv/guides/tools/#requesting-specific-versions)
   and keep your extras.

1. Read the new release from the upgraded host installation with
   `vaultspec-rag --version`. Move every client project to that release, keeping its
   extras:

   ```bash
   uv add --dev "vaultspec-rag[mcp]==<release>"
   ```

   A client on the plain package uses `uv add --dev "vaultspec-rag==<release>"`.
   Collaborators then upgrade their own host installations to the same release.

1. In each repository, refresh the repository setup. Repeat any `--local-only`,
   `--no-mcp`, or `--no-torch-config` you used; only the installation route carries
   over.

   ```bash
   vaultspec-rag install --upgrade
   ```

   A client runs it as `uv run vaultspec-rag install --upgrade`.

1. If you ran the host's repository setup with `--local-only`, `--skip-qdrant`, or
   `--no-provision`, it skipped the Qdrant download. When the
   [release notes](https://github.com/nevenincs/vaultspec-rag/releases) name a new
   Qdrant version, install it:

   ```bash
   vaultspec-rag server qdrant install
   ```

   Otherwise, the repository setup already downloaded it.

1. Start the service again from the host installation, reconnect assistants, and rerun
   the checks in [start and verify](#start-and-verify). If the release requires
   rebuilding indexes, follow [reindexing](verification.md#reindexing).

## When something goes wrong

<p id="telling-two-lookalikes-apart"></p>
<p id="the-driver-isn-t-loaded"></p>
<p id="the-environment-has-a-processor-only-build"></p>
<p id="a-tool-environment-lost-its-gpu-build"></p>

### `vaultspec-rag` isn't found after installing

For a standalone tool, run `uv tool update-shell`, open a new terminal, and try again.
For a project dependency, run commands as `uv run vaultspec-rag` from the project root.
For a downloaded archive, add the extracted folder to your `PATH`.

### GPU backend unavailable

A `torch: not_ready` line from `server doctor` can mean missing PyTorch, an
unavailable GPU, an unsuitable PyTorch build, or rejected MPS fallback. Read the
diagnostic detail before choosing a repair.

First, [confirm your GPU is visible](#confirm-your-gpu-is-visible). If that check fails,
fix the driver before repairing packages. Apple silicon uses MPS, not CUDA.

For a project dependency, rerun the [repository setup](#set-up-each-repository) and
`uv sync`. For a standalone tool on Linux or Windows, follow
[pin the GPU build](#pin-the-gpu-build). Running `uv sync` in a project doesn't update
a tool's environment. After making changes, rerun the checks in
[start and verify](#start-and-verify).

### The model download is refused

A `401`, `403`, `GatedRepoError`, or "repository not found" during the repository setup
or `server start` usually means missing authorization, not a missing repository.
Accept the conditions on the [model page](https://huggingface.co/naver/splade-v3), then
log in again as described in
[the model cache and its first download](#the-model-cache-and-its-first-download). To
avoid the gated model, turn the sparse model off there.

### The GPU runs out of memory

Exhausting GPU memory is a runtime concern rather than an install one. See
[tuning for memory and speed](configuration.md#tuning-for-memory-and-speed). On MPS,
memory is unified with the rest of the system rather than dedicated.

### `server start` says the installation is a client

The message reads `That environment cannot run the GPU-only service: not needed (this installation is a client)`.
The command ran in a client installation, which can't run the service. Start the
service from the host installation instead. If the machine has none,
[set up a host installation](#set-up-a-host-installation).

### Commands report that no service is running

The service is stopped, which is its normal state after a reboot. Start it from the
host installation with `vaultspec-rag server start`, then retry the search, index
request, or assistant's tool call.

### The client and the service run different releases

Commands print `Refusing to <command> against the running service.` and name both
releases. In `--json` output and in an assistant's tool error, the code is
`service_version_mismatch`. The code is `service_version_unreported` when the service
predates release reporting.

Move the older side forward: pin the client project to the service's release, or
upgrade the host installation and restart the service from it. The [upgrade](#upgrade)
steps cover both. A client can't restart the service itself.

<p id="install-refused-to-edit-pyprojecttoml"></p>

### `install` refuses to edit `pyproject.toml`

The repository setup needs consent it doesn't have, so it exits non-zero. Rerun it with
`--yes` to approve, or with `--no-torch-config` to manage PyTorch yourself.

<p id="install-refused-to-repair-the-tool-environment"></p>

### `install` prints a repair command instead of repairing the tool

The repository setup prints a repair command rather than replacing the environment it's
running in, and exits non-zero without setting up the repository. Follow
[pin the GPU build](#pin-the-gpu-build) to stop the service and its assistant sessions,
then run the saved command from outside the tool environment. See the
[install command reference](cli.md#install) for configuration flags.

<p id="a-tool-environment-is-missing-packages-after-a-failed-reinstall"></p>

### A tool environment is missing packages after an interrupted reinstall

An interrupted reinstall can leave `vaultspec-rag` unable to run, reporting
`ModuleNotFoundError`. In this state, the command can't generate a repair command.

[Report the failed command](https://github.com/nevenincs/vaultspec-rag/issues) with the
error, operating system, Python version, and output of
`uv tool list --show-paths --show-python --show-with`. Include any saved pinned install
command. While the service or assistant sessions still use the tool environment, don't
force another reinstall; [pin the GPU build](#pin-the-gpu-build) requires them to stop
first.

<p id="server-start-cannot-find-the-qdrant-binary"></p>

### `server start` can't find the Qdrant binary

Install the Qdrant binary, then retry your original start command. For a project
dependency, add `uv run`:

```bash
vaultspec-rag server qdrant install
```

To use the local-only backend instead, follow [storage backends](backends.md).

<p id="the-qdrant-download-failed-a-checksum"></p>

### The Qdrant download fails a checksum

The archive didn't match the committed digest, and the command deleted the partial
file. Retry. On an air-gapped machine, register your own executable with
`server qdrant install --binary <path>`.

### Pin the GPU build

Use these steps to repair missing or CPU-only PyTorch in a standalone tool on Linux or
Windows. Apple silicon uses the standard wheel's MPS support.

A pin saves the direct `torch` wheel URL in the tool's installation receipt through
`--with`. Unpinned upgrades can select a CPU build. Project `pyproject.toml` settings
and `uv sync` don't configure tool environments.

If `ModuleNotFoundError` prevents `vaultspec-rag` from running, see
[the interrupted reinstall entry](#a-tool-environment-is-missing-packages-after-an-interrupted-reinstall)
before attempting these steps.

1. If `vaultspec-rag` runs, preview the repair:

   ```sh
   vaultspec-rag install --dry-run --no-torch-config
   ```

   For a missing or CPU-only PyTorch build, this prints a pinned, platform-specific
   `uv tool install` command. Save it. The preview neither replaces the tool nor checks
   for processes holding its files. If no command appears, follow the diagnosis and
   rerun the checks in [start and verify](#start-and-verify).

1. Before running the saved command, locate the tool environment and stop its service:

   ```sh
   uv tool list --show-paths --show-python --show-with
   vaultspec-rag server stop
   ```

1. Prepare the tool environment for replacement:

   1. If the stop command reports a failure, resolve it first.
   1. Close assistant sessions that use the tool.
   1. Move shells and editors outside its environment directory. Open file handles can
      leave an incomplete installation on Windows.

1. Run the saved command from a shell outside the tool environment. Preserve its
   `--python` selection and wheel URL; Python must match the wheel's compatibility tags.

1. Run the tool listing again and confirm it shows the direct `torch` URL. Rerun
   `vaultspec-rag install --no-torch-config` in each repository whose setup was
   refused, then rerun the checks in [start and verify](#start-and-verify).

### Ask for help

Open an issue on the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues)
with the output of `vaultspec-rag server doctor --json`,
`vaultspec-rag server status --json`, and `vaultspec-rag server logs`. Redact
credentials and private content first. The tracker takes questions as well as bug
reports, and it's the only support channel.

<p id="remove-it"></p>

## Remove vaultspec-rag

Removing a repository's setup removes its integration, not the package, and it keeps
indexed data by default. Read the [uninstall flags](cli.md#uninstall) before choosing
data removal. If vaultspec-rag is a project dependency, prefix each command with
`uv run`.

1. From the repository root, preview the changes:

   ```sh
   vaultspec-rag uninstall
   ```

1. Review the preview, then apply it. If you use the local-only backend and want to
   delete this repository's index too, its index lives in the repository's `.vault/`
   folder; run `vaultspec-rag uninstall --force --remove-data`. Otherwise, run:

   ```sh
   vaultspec-rag uninstall --force
   ```

1. With the managed Qdrant server, every repository on the machine shares one index
   store. To delete only this repository's indexes,
   [inspect the store](storage-maintenance.md#inspect-what-is-stored) and follow
   [storage maintenance](storage-maintenance.md#reclaim-space-manually).

1. Before removing a host installation, run `vaultspec-rag server stop` from it and
   close connected assistant sessions. Stopping the service interrupts everyone using
   it. Before removing a client, close the assistant sessions that use it.

1. Remove the package with the command for your installation route:

   | Installation route        | Command                           |
   | ------------------------- | --------------------------------- |
   | Project dependency        | `uv remove vaultspec-rag`         |
   | Client added with `--dev` | `uv remove --dev vaultspec-rag`   |
   | Standalone tool           | `uv tool uninstall vaultspec-rag` |
   | Scoop                     | `scoop uninstall vaultspec-rag`   |
   | Homebrew                  | `brew uninstall vaultspec-rag`    |
   | Downloaded archive        | Delete the extracted folder       |

The models stay in the Hugging Face cache, and the Qdrant binary stays under
`~/.vaultspec-rag/bin/`. Delete them only when no repository on the machine uses
vaultspec-rag anymore.

## Where to go next

- The [project overview](../README.md) answers what vaultspec-rag is and what problem it
  solves.
- [Getting started](getting-started.md) walks through a first index and search.
- [Search and index](search-and-index.md) answers how ranking works and what the
  filters do.
- The [service guide](service-mode.md) answers how to run, observe, and control the
  service.
- [Backends](backends.md) answers when to choose the local-only backend over the managed
  Qdrant server.
- [Storage maintenance](storage-maintenance.md) answers how to inspect and reclaim index
  storage.
- [Configuration](configuration.md) answers which environment variables and settings
  exist.
- The [command reference](cli.md) lists every command, flag, and exit code.
- [MCP integration](mcp.md) answers how an AI assistant reaches the service.
- The [architecture overview](architecture.md) answers how the service, models, and
  index fit together.
- The [glossary](glossary.md) defines the terms these guides use.
- The [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues) takes
  questions and bug reports.

## Appendix: reference

### Packages and what they can run

vaultspec-rag has two extras, `gpu` and `mcp`. The `gpu` extra installs the model stack.
The `mcp` extra adds the library the model-free MCP standard input/output (stdio)
adapter needs. Every package installs the `vaultspec-search-mcp` command, but that
command refuses to run without the `mcp` extra.

| Package                  | Installation | Loads models | Needs a GPU | Can start the service | Can run the MCP adapter |
| ------------------------ | ------------ | ------------ | ----------- | --------------------- | ----------------------- |
| `vaultspec-rag`          | Client       | No           | No          | No                    | No                      |
| `vaultspec-rag[mcp]`     | Client       | No           | No          | No                    | Yes                     |
| `vaultspec-rag[gpu]`     | Host         | Yes          | Yes         | Yes                   | No                      |
| `vaultspec-rag[gpu,mcp]` | Host         | Yes          | Yes         | Yes                   | Yes                     |

In `tool` mode, the MCP entry the repository setup writes fetches the adapter with
`uvx`, whatever the installation contains.

The service is loopback-only. A client and its host installation share one machine; this
isn't a documented network deployment across machines. `VAULTSPEC_RAG_QDRANT_URL` can
point at remote vector storage, but Qdrant doesn't run the dense encoder, sparse
encoder, or reranker. The host installation still needs `[gpu]` and a supported GPU.

### Inspect the archive layout

Every verified release archive contains these members at its top level:

| Member                                               | Purpose                                            |
| ---------------------------------------------------- | -------------------------------------------------- |
| `vaultspec-rag` or `vaultspec-rag.exe`               | Command-line client and service control            |
| `vaultspec-search-mcp` or `vaultspec-search-mcp.exe` | MCP stdio adapter                                  |
| `LICENSE`                                            | Project licence                                    |
| `README.txt`                                         | Target and runtime notes                           |
| `manifest.json`                                      | Machine-readable bundle metadata and member hashes |

`manifest.json` records the schema, product and version, release tag, target, archive
format, runtime, requirements, and platform metadata. Its `files` array records the
role, size, and SHA-256 of each executable and release document.

Confirm `archive.name` matches the downloaded filename, `target` matches your machine,
and every `files[].name` exists with its listed size and digest. `manifest.json`
doesn't hash the enclosing archive; `SHA256SUMS` is the source of truth for that digest.
The manifest's `platform.glibc_floor` records the Linux loader floor.

### Which Linux binary your distribution can run

A binary links against the C library that built it, so a download labelled only "Linux"
may not run on your distribution.

| Binary                      | Requires   | Covers                                |
| --------------------------- | ---------- | ------------------------------------- |
| `x86_64-unknown-linux-gnu`  | glibc 2.39 | Ubuntu 24.04+, Debian 13+, Fedora 40+ |
| `aarch64-unknown-linux-gnu` | glibc 2.39 | Ubuntu 24.04+, Debian 13+, Fedora 40+ |

Check your glibc version with `ldd --version`. On an older distribution, the binary
doesn't start, and the error names a missing symbol version rather than saying the
distribution is too old.

Debian 12, Ubuntu 22.04, Red Hat Enterprise Linux (RHEL) 8 and 9, and Amazon Linux 2023
all ship a glibc below this floor, so the archives don't run there. On those systems,
install from PyPI instead. The PyPI route needs glibc 2.28, the floor of the CUDA
PyTorch wheel, which every distribution listed here meets.
