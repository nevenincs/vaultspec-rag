# Installing vaultspec-rag

vaultspec-rag searches a repository's source code and its design decision records by
meaning, from the terminal or from an AI coding assistant. Decision records are
markdown files kept in a `.vault/` folder. The repository setup creates the folder, and
code search works while it's empty. This guide installs vaultspec-rag on one machine and
connects repositories to it.

The RAG search service needs a supported graphics processing unit (GPU): an NVIDIA GPU with CUDA,
NVIDIA's GPU computing platform, on Linux or Windows, or Apple silicon on macOS. It
doesn't run on a central processing unit (CPU) or on AMD GPUs. The
[architecture overview](architecture.md#why-vaultspec-rag-needs-a-gpu) explains why a
GPU is required, and the [glossary](glossary.md) defines the terms this guide uses.

<p id="choose-an-install-route"></p>
<p id="choose-what-this-environment-runs"></p>

## Choose an installation

Every machine that uses vaultspec-rag runs one background [service](glossary.md#service).
The service runs the search models on the GPU, and the `vaultspec-rag server` commands
control it. None of the routes below carry GPU packages at install time; the first
`vaultspec-rag server start` puts them wherever they belong.

- [Install as a standalone tool](#install-as-a-standalone-tool) by default. One
  installation serves every repository on the machine, in any language.
- [Add a client to a Python project](#add-a-client-to-a-python-project) when one Python
  project should list vaultspec-rag as a dependency instead.
- [Install a prebuilt binary](#install-a-prebuilt-binary) when the machine has no Python
  toolchain. A binary always carries its own GPU packages.

Run every installation under the same user account as the service: a client that talks
to a service another account started can't reach it.

Find out where this machine stands:

- If the `vaultspec-rag` command isn't found, and no project on this machine depends on
  it, nothing is installed yet. [Install vaultspec-rag](#install-vaultspec-rag).
- If `vaultspec-rag server status` reports the service stopped, don't reinstall. Start
  it with `vaultspec-rag server start`.
- If `vaultspec-rag server status` reports the service running,
  [set up each repository](#set-up-each-repository).

To carry the GPU packages in the installation itself instead of letting `server start`
build them separately - a [host installation](glossary.md#host-installation) - see
[carry the GPU packages in the tool itself](#carry-the-gpu-packages-in-the-tool-itself).
The [package table](#packages-and-what-they-can-run) lists what each package can run.

## Install vaultspec-rag

### What you need before you start

- A supported GPU. On Linux and Windows, install an NVIDIA driver that supports CUDA 13.
  On macOS, the system provides the driver. Without one, `vaultspec-rag install` and
  `server start` still run, but `server start` has no GPU to put the service on and
  refuses; see [when something goes wrong](#when-something-goes-wrong).
- The system memory (RAM), disk, and GPU memory of a resource profile, from the
  following table.
- Several gigabytes of free disk: the model download, which every repository shares, and,
  unless this installation carries the GPU packages itself, the GPU environment the first
  `server start` builds.
- [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs vaultspec-rag,
  manages the Python interpreter the standalone tool and the GPU environment use, and
  needs no separate CPython install.
- Network access to the Python Package Index (PyPI), the PyTorch download server
  (`download.pytorch.org`) on Windows and Linux, the Hugging Face model server, and
  GitHub release downloads. A site that mirrors the models or the Qdrant release names
  its mirror instead; see [download sources](configuration.md#download-sources).

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

A project adding vaultspec-rag as a client dependency also needs a `requires-python`
that allows 3.13 or 3.14. A prebuilt binary needs neither uv nor a project file.

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

Search uses public dense, sparse and reranker models. The sparse encoder is
[`Linkup-Platform/linkup-sparseup-embed-v1`](https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1),
a ModernBERT SPARSEUP model pinned to revision
`08314498d4f6a3a205b930ab9f27001404ea94b8`. Downloads require no account setup.
Repository setup, `server warmup`, and `server doctor` share that revision.

Each default model is pinned to one commit, and every file is compared with a digest
compiled into vaultspec-rag after it is downloaded and before it is loaded. The
[provisioning guide](provisioning.md#the-model-files) describes the check, what an
unpinned model is, and how to run without a network.

Set `VAULTSPEC_RAG_SPARSE_ENABLED=0` to use dense vectors only and reduce GPU
memory usage. Provisioning, warmup and readiness then omit the sparse model.
Rebuild existing indexes after changing the model or this toggle.

Model files use the [Hugging Face cache](configuration.md#hugging-face-cache). To choose
where downloads go, set `HF_HOME` to a persistent location before the repository setup.
See [model selection and toggles](configuration.md#model-selection) for the full
reference.

<p id="install-with-python"></p>
<p id="installing-it-as-a-standalone-tool"></p>

### Install as a standalone tool

Choose this route by default. One installation serves every repository on the machine,
in any language:

```bash
uv tool install "vaultspec-rag[mcp]"
```

This installs the command line and the Model Context Protocol (MCP) adapter your AI
assistant launches: in `tool` mode the assistant launches
`uvx --from "vaultspec-rag[mcp]" python -m vaultspec_rag.server`, and `uvx` reuses the
installed tool instead of fetching another copy. It carries no GPU packages. The first
`vaultspec-rag server start` in each repository builds a separate environment for the
service, with the CUDA build of PyTorch, under the service's own managed directory, and
runs the daemon from there. That build runs once per release and takes a few minutes;
later starts and later repositories reuse it, and an upgrade's first start replaces it.

If uv reports its executables directory isn't on your `PATH`, run `uv tool update-shell`
and open a new terminal.

Run every later command as `vaultspec-rag`. Continue with
[set up each repository](#set-up-each-repository).

To try vaultspec-rag without installing anything, run `uvx vaultspec-rag server start`
instead. It builds the same service environment, but fetches the `vaultspec-rag` command
itself afresh on every invocation, which is slower for repeated use than the standalone
tool.

<p id="carry-the-gpu-packages-in-the-tool-itself"></p>

#### Carry the GPU packages in the tool itself

Choose this instead of the default when one environment should hold both the command
line and the GPU packages, with no separate environment for `server start` to build - for
example, on a machine with no network access once the install is done.

Windows x86-64, Linux x86-64 and Linux aarch64 (glibc 2.28 or newer):

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --index https://download.pytorch.org/whl/cu130 --index-strategy unsafe-first-match
```

Apple silicon macOS, which uses Metal rather than CUDA:

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]"
```

Both options are needed on Windows and Linux. The index alone leaves the request
unsatisfiable, because the CUDA index mirrors packages this one depends on at versions it
cannot use and uv's default strategy forbids falling through to PyPI. Choose a Python
version your platform has a CUDA build for; PyTorch publishes them for Windows x86-64 and
Linux x86-64 and aarch64 only. The command records the CUDA package index and its
resolution strategy in the tool's installation receipt, which uv re-applies on every
later upgrade, so the GPU build survives them. An installation made without the two
options is repaired in place by [pin the GPU build](#pin-the-gpu-build).

Run every later command as `vaultspec-rag`. Continue with
[set up each repository](#set-up-each-repository).

<p id="install-without-python"></p>
<p id="installing-a-prebuilt-binary"></p>
<p id="which-sections-you-still-need"></p>

### Install a prebuilt binary

Choose this route when the machine has no Python toolchain. A binary is always a host
installation. The release publishes Windows x86-64, Linux x86-64 and ARM64, and Apple
silicon macOS archives. Intel Macs are unsupported on every route, because PyTorch
publishes no Intel macOS build.

`vaultspec-rag`, `vaultspec-search-mcp`, and `vaultspec-rag-monitor` ship in one archive
per target. The two RAG commands embed CPython 3.13 and install their runtime dependencies
on first launch. The monitor embeds its server, React assets, CSS and fonts; serving its
frontend needs no Python, Node, npm, Bun, GPU or network download.

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
all three commands on your `PATH`.

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
   .\vaultspec-rag\vaultspec-rag-monitor.exe --version
   ```

   Linux or macOS (substitute your asset's name):

   ```sh
   mkdir -p vaultspec-rag
   tar -xzf vaultspec-rag-v<release>-x86_64-unknown-linux-gnu.tar.gz -C vaultspec-rag
   chmod +x vaultspec-rag/vaultspec-rag vaultspec-rag/vaultspec-search-mcp \
     vaultspec-rag/vaultspec-rag-monitor
   ./vaultspec-rag/vaultspec-rag --version
   ./vaultspec-rag/vaultspec-rag-monitor --version
   ```

1. Add the extracted folder to your `PATH`, so later steps can run `vaultspec-rag`.

To check each extracted file against the archive's manifest, see the
[archive layout](#inspect-the-archive-layout).

#### Open the monitor

After adding the extracted directory to your `PATH`, run:

```sh
vaultspec-rag-monitor --port 5420
```

It prints `vaultspec.monitor.ready` followed by an access link such as
`http://127.0.0.1:5420/#capability=<secret>`. Open that whole link: the capability in it
is what lets the page operate the service, and it changes on every launch. The frontend
starts independently of the search service; when no backend is available it shows that
state. An occupied port fails explicitly.
Press Ctrl+C to stop a monitor you launched directly. `--version --json` reports the
release version, full producer commit and embedded frontend identity without starting
the backend.

Backend controls use the sibling `vaultspec-rag` command. If that command lives
elsewhere, set `VAULTSPEC_RAG_MONITOR_OWNER` to its absolute executable path. Those
controls still need the RAG runtime described below. The service supervisor uses its
initialized Python environment automatically when it launches the monitor.

#### First launch requirements for RAG commands

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
package:

```sh
vaultspec-rag install
```

A standalone tool, `uvx`, or prebuilt binary installation has no project of its own to
patch and runs this with no prompt. vaultspec-rag can also run from a project's own
environment instead: [a client dependency](#add-a-client-to-a-python-project), or a
self-contained GPU tool pointed at a repository that happens to have a `pyproject.toml`.
When that file has no CUDA torch index yet, the setup asks to add one; answer `y`, or
pass `--yes` for an unattended run. `--force` overwrites existing files but never
answers this prompt; only `--yes` does. A run with nobody to answer it, such as CI, a
non-TTY session, or `--json`, never prompts: it skips the patch, reports the skip, and
exits non-zero, so the gap is visible rather than silent. If the detection is wrong,
correct it with `--mode`; see the [install command reference](cli.md#install).

The repository setup does three things:

- Adds the AI assistant integration: a rule, a skill, and the MCP server entry your
  assistant launches. See [MCP integration](mcp.md).
- Creates the `.vault/` folder if it's missing.
- When this installation's own environment can already run the service and managed
  Qdrant is selected, setup downloads the search models and the Qdrant server binary, on
  the first such repository. Local-only mode skips the Qdrant download. Any other
  installation - including the standalone tool's default route, which runs the service
  from a separate environment it has not built yet - skips both downloads here; the
  first `server start` fetches what its selected backend needs once that environment is
  ready. Later repositories reuse the cached models and managed server. The default
  configuration downloads three models, and a dense-only configuration downloads two.
  The first download is several gigabytes.

These flags change it:

- For terminal use without an AI assistant, add `--no-mcp`.
- To keep the index in the local-only backend instead of the managed Qdrant server, add
  `--local-only`, which also skips the Qdrant download. The backend is a choice for the
  whole service, not one repository. `install --local-only` records the choice, so a
  later `vaultspec-rag server start` needs no flag. Pass `server start --local-only`
  only for a machine or run where you never ran `install --local-only`. Either way, set
  `VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local` where the service starts,
  because the default profile refuses the local-only backend. See
  [storage backends](backends.md).

The repository setup detects how the repository declares vaultspec-rag and records it in
`.vaultspec/workspace.json`.

#### Machine-readable output

`install --json` and `uninstall --json` print one line: the shared vaultspec envelope
`{"schema", "status", "data"}`, plus `"hints"` when the run has a next step to advise.
The run's own report is the `data` member, and `status` is one word from the shared
vocabulary:

| Status      | Meaning                                                                     |
| ----------- | --------------------------------------------------------------------------- |
| `created`   | Install only. The install completed and was not an upgrade                  |
| `updated`   | Install only. An existing installation was upgraded (`--upgrade`)           |
| `unchanged` | A preview (`--dry-run`), or a run that changed nothing                      |
| `removed`   | Uninstall only. Uninstall removed the installation                          |
| `skipped`   | Install only. The run completed but a required step was skipped for consent |
| `failed`    | The run failed                                                              |

Uninstall reports only `failed`, `unchanged`, or `removed`.

When install provisions, `data.provisioning.steps` holds one entry for each of `torch`,
`models`, and `qdrant`. An entry carries its `step`, its `action` in the same
vocabulary, a `detail` sentence, `sync_pending`, and `code`. `code` is a stable
machine-readable reason when the `models` or `qdrant` step failed, such as
`models_offline`, `models_fetch_failed`, `qdrant_provision_failed`,
`qdrant_binary_invalid`, or `qdrant_binary_unverified`, and is empty otherwise.
`server start --json` reports the same codes as its `error` when one of these steps
stops a start.

A run that can't start at all prints the `vaultspec.error.v1` envelope with its reason
instead, so every `--json` run is parsed the same way.

The exit codes are the shared ones: `0` for success, `1` for a failure, and, for install
only, `2` for the `skipped` status above, a run that completed with a required step skipped, such as the
PyTorch configuration patch nobody was there to approve. A tool environment that needs
the CUDA repair, and wasn't authorised to have it applied, is a failure rather than a
skip: nothing was installed, so the requested state wasn't reached.

<p id="verify-the-install"></p>

### Start and verify

Start the service:

```bash
vaultspec-rag server start
```

When this installation's own environment cannot run the service - the standalone tool's
default route, a plain client dependency, or `uvx` - the first start also builds the
separate GPU environment described in
[install as a standalone tool](#install-as-a-standalone-tool), before anything else.
Either way, the command then downloads whatever the selected backend needs and doesn't
have yet: missing model files, and the Qdrant server when managed-server mode is
selected and no binary resolves. Local-only mode fetches model files but skips Qdrant. It
shows each transfer, then loads the models and waits until the service is ready. A
repository setup that already downloaded the required files leaves nothing to fetch. To
stop `server start` from downloading the Qdrant server, pass `--no-qdrant-auto-provision`
or set `VAULTSPEC_RAG_QDRANT_AUTO_PROVISION=0`; see
[managed server provisioning](configuration.md#managed-server-provisioning). Stop the
service with `vaultspec-rag server stop`. It doesn't restart by itself after a reboot, and
vaultspec-rag ships no autostart. The [service guide](service-mode.md) explains how the
service is started and what a service manager must account for.

Three commands answer different questions throughout this guide:

| Command                       | What it answers                                                                                                             |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `vaultspec-rag server status` | Is the service running? Add `--verbose` to see its release.                                                                 |
| `vaultspec-rag server doctor` | Does this installation, or the environment the service runs from, have what it needs, and does the service's release match? |
| `vaultspec-rag status`        | What state is this repository's index in, and which installation runs the service?                                          |

Check the version:

```bash
vaultspec-rag --version
```

This reports `vaultspec-rag v0.6.0`. <!-- x-release-please-version -->

Then run the readiness report:

```bash
vaultspec-rag server doctor
```

A healthy installation reports PyTorch ready on a `cuda` or `mps` backend, every
configured model cached, and the Qdrant binary present. When the service runs from a
separate GPU environment rather than this installation, doctor reports that environment
instead, under its own "Service runtime" line. If a line reports a problem, see
[when something goes wrong](#when-something-goes-wrong). To interpret the full report,
see [verify the index](verification.md).

Next, index the repository and run a first search with the
[getting-started tutorial](getting-started.md#step-2-start-the-service-and-index-your-project).

## Add a client to a Python project

Add vaultspec-rag to a Python project without carrying GPU packages in it. The project
needs a `requires-python` that allows 3.13 or 3.14. From the project root:

```bash
uv add --dev "vaultspec-rag[mcp]"
uv run vaultspec-rag install
uv run vaultspec-rag server start
```

For terminal use without an AI assistant, add the plain package and skip the assistant
integration instead:

```bash
uv add --dev "vaultspec-rag"
uv run vaultspec-rag install --no-mcp
uv run vaultspec-rag server start
```

Run every later command as `uv run vaultspec-rag` from the project root. The repository
setup detects a project dependency and launches the AI assistant's tools from the
project's own environment; correct a wrong detection with `--mode`. `server start` builds
this client its own GPU environment the first time it runs, the same as
[the standalone tool](#install-as-a-standalone-tool) does; nothing in the project's own
environment needs a GPU, CUDA, or PyTorch.

### Join a service another installation already started

Skip building a second runtime when a host installation, or another client, already runs
the service on this machine under your user account. Pin this client to exactly that
service's release instead - a client refuses a service from any other release:

```bash
vaultspec-rag server status --verbose    # note the "Service release:" line
uv add --dev "vaultspec-rag[mcp]==<release>"
```

Then run `install` and `server start` as above; this time `server start` attaches to the
running service instead of building a runtime.

### Verify the client

```bash
uv run vaultspec-rag server doctor
```

It shows `release: <release> (matches this client)` for the running service. If the
release doesn't match, pin the client to the service's release and try again. While the
service runs, `uv run vaultspec-rag status` describes the installation that serves the
client, not the client's own environment.

Index and search with the same commands a standalone tool uses, prefixed with
`uv run`; see the [getting-started tutorial](getting-started.md).

## Upgrade

A client refuses a service from a different release, even a newer one. Upgrade whichever
installation runs the service, and every client, together.

1. Close connected assistant sessions. The service may serve other repositories and
   assistants, so tell their users before stopping it. Then stop it:

   ```bash
   vaultspec-rag server stop
   ```

   A client runs it as `uv run vaultspec-rag server stop`. If the command reports a
   failure, resolve it before continuing; see
   [the service guide's troubleshooting](service-mode.md#troubleshooting).

1. Upgrade the installation that runs the service, with the command for its route:

   | Installation route | Upgrade command                                               |
   | ------------------ | ------------------------------------------------------------- |
   | Project dependency | `uv sync --upgrade-package vaultspec-rag`                     |
   | Standalone tool    | `uv tool upgrade vaultspec-rag`                               |
   | Scoop              | `scoop update vaultspec-rag`                                  |
   | Homebrew           | `brew upgrade vaultspec-rag`                                  |
   | Downloaded archive | Verify and extract the new release in place of the old folder |

   uv upgrades respect version constraints and re-applies the Python version and the
   extras an installation was given. The default standalone tool and a client carry no
   GPU packages, so there is nothing for the upgrade to lose; the next
   `vaultspec-rag server start` builds a fresh GPU environment for the upgraded release
   and removes the one the previous release used.

   Only [the self-contained tool](#carry-the-gpu-packages-in-the-tool-itself) - the one
   installed with the `gpu` extra - also re-applies the
   [CUDA index](#carry-the-gpu-packages-in-the-tool-itself) its receipt records, so its
   GPU build survives the upgrade. A self-contained tool installed before this mechanism,
   or installed without the two index options, records no CUDA source: a plain upgrade
   then resolves a CPU-only PyTorch. `vaultspec-rag server doctor` says so and prints the
   one command that repairs it, which is the same command
   [pin the GPU build](#pin-the-gpu-build) describes. Nothing needs to be stopped for it.

1. Read the new release from the upgraded installation with `vaultspec-rag --version`.
   Move every client project to that release, keeping its extras:

   ```bash
   uv add --dev "vaultspec-rag[mcp]==<release>"
   ```

   A client on the plain package uses `uv add --dev "vaultspec-rag==<release>"`.
   Collaborators then upgrade their own installations to the same release.

1. In each repository, refresh the repository setup. Repeat any per-run flags whose
   effects you want for this refresh, such as `--local-only` or `--no-mcp`; only the
   installation route carries over. Either way, `--local-only` records the saved
   backend choice.

   ```bash
   vaultspec-rag install --upgrade
   ```

   A client runs it as `uv run vaultspec-rag install --upgrade`.

   A repository set up before its placement was recorded, with no vaultspec-rag entry
   in `.vaultspec/workspace.json`, has its placement inferred rather than reset. A
   `pyproject.toml` runtime dependency or dev-group entry counts only when the
   repository's existing MCP launch already matches it, so `--upgrade` can't move a
   working `tool`-mode setup onto `dependency` mode just because the package is also
   listed.

1. If a release advances the pinned Qdrant version, a start with managed Qdrant selected
   ensures that version is installed, downloading it if it is missing. This also applies
   when repository refresh used `--no-provision`. A saved local-only choice is
   different: a plain start continues in local-only mode and skips Qdrant. Use
   `server start --qdrant` to select the managed server for one start, or install the
   binary without changing the backend choice:

   ```bash
   vaultspec-rag server qdrant install
   ```

   If you want managed-server mode saved for later plain starts, rerun
   `install --upgrade` without `--local-only` or a local-only environment override,
   while the environment that runs the service is ready; a successful setup records
   that choice. If automatic Qdrant downloads are disabled, `server start --qdrant`
   reports the install command instead.

1. Start the service, reconnect assistants, and rerun the checks in
   [start and verify](#start-and-verify). If `uv` reports that it could not replace an
   entry point because the file is in use, the release is installed and the environment
   is intact; restarting the service and any assistant session holding the old launcher
   clears the report.

1. Apply any release-specific index migration after the new service is running. In
   particular, upgrading to 0.6.0 from the previous sparse encoder requires rebuilding
   every indexed repository: its existing sparse vectors are incompatible with the new
   model, and automatic file convergence does not migrate them. Run:

   ```bash
   vaultspec-rag --target <repository> index --rebuild --type all
   ```

   Repeat for each indexed repository and wait for each rebuild to complete. See the
   [sparse encoder details](indexing.md) and [reindexing guide](verification.md#reindexing).

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

This applies to an installation that runs the service directly:
[the self-contained tool](#carry-the-gpu-packages-in-the-tool-itself), or a project that
added the `gpu` extra itself. Follow [pin the GPU build](#pin-the-gpu-build). The default
standalone tool, a plain client, and `uvx` run the service from a separate GPU
environment instead; see
[the service runtime could not be created](#the-service-runtime-could-not-be-created) if
that one fails. After making changes, rerun the checks in
[start and verify](#start-and-verify).

### The model download fails

`install`, `server warmup`, and `server start` download missing model files the same
way, in the foreground, and name the repository that failed. Each repository is
attempted before the command reports, so one failure doesn't hide the next. Check
network access to the Hugging Face Hub or your configured `HF_ENDPOINT`, and confirm
that `HF_HOME` is writable, then rerun `vaultspec-rag server warmup`.

`server warmup` exits `1` when any model could not be fetched. Earlier releases printed
the failure and exited `0`, so a script that ignored its output should now check the
exit code. `server start` stops with `models_fetch_failed` before it starts a daemon.

With offline mode enabled (`HF_HUB_OFFLINE` or `TRANSFORMERS_OFFLINE`), nothing is
downloaded: the cache must already contain the pinned model revision. A model that is
missing then stops the command, and `server start --json` reports it as
`models_offline`. Unset the offline switch and run `vaultspec-rag server warmup`, or copy
a complete model cache onto the machine.

A model that is in the cache and fails its check is reported as `models_unverified`,
with the file at fault. The service never loads such a model. The
[provisioning guide](provisioning.md#when-provisioning-fails) lists every failure code,
what it means, and what to do.

### The GPU runs out of memory

Exhausting GPU memory is a runtime concern rather than an install one. See
[tuning for memory and speed](configuration.md#tuning-for-memory-and-speed). On MPS,
memory is unified with the rest of the system rather than dedicated.

### The service runtime could not be created

When this installation's own environment cannot run the service, `server start` builds
one that can: a separate GPU environment under the service's own managed directory. Each
cause below is one line in that refusal, and each has one command.

- **uv was not found.** The runtime is built with uv. Install it, then run
  `vaultspec-rag server start` again. Windows:
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
  Linux and macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **This installation is a source checkout.** The runtime can only reproduce a released
  build. Install [the standalone tool](#install-as-a-standalone-tool), or
  [the self-contained tool](#carry-the-gpu-packages-in-the-tool-itself), instead.
- **No supported GPU is visible to the new environment.** Check the driver:
  `nvidia-smi`, then run `vaultspec-rag server start` again.
- **The build itself failed, or another start is already building it.** The failure
  names what uv could not do. Run `vaultspec-rag server start` again; a build that
  failed partway is discarded, and a build already in progress is reused once it
  finishes.

### Commands report that no service is running

The service is stopped, which is its normal state after a reboot. Start it with
`vaultspec-rag server start` (or `uv run vaultspec-rag server start` for a client), then
retry the search, index request, or assistant's tool call.

### The client and the service run different releases

Commands print `Refusing to <command> against the running service.` and name both
releases. In `--json` output and in an assistant's tool error, the code is
`service_version_mismatch`. The code is `service_version_unreported` when the service
predates release reporting.

Move the older side forward: pin the client project to the service's release, or
upgrade whichever installation runs the service and restart it. The
[upgrade](#upgrade) steps cover both.

<p id="install-refused-to-edit-pyprojecttoml"></p>

### `install` refuses to edit `pyproject.toml`

This happens only when vaultspec-rag runs from a project's own environment - a client
dependency, or a self-contained GPU tool pointed at a repository that has its own
`pyproject.toml` - and that file has no CUDA torch index yet. The repository setup needs
consent it doesn't have, so it exits non-zero. Rerun it with `--yes` to approve.

<p id="install-refused-to-repair-the-tool-environment"></p>

### `install` prints a repair command instead of repairing the tool

The repository setup found a persistent, self-contained GPU tool environment that cannot
run the GPU stack, or whose installation receipt records no CUDA source, and it was not
authorised to change anything. It prints the command that repairs it and exits non-zero
without setting up the repository. This never happens for the default standalone tool,
which carries no GPU packages of its own.

Run the repository setup again with `--yes` to let it apply the repair itself, or run
the printed command. Either way the change is made in place and nothing has to be
stopped; see [pin the GPU build](#pin-the-gpu-build) for the whole sequence and the
[install command reference](cli.md#install) for configuration flags.

<p id="a-tool-environment-is-missing-packages-after-a-failed-reinstall"></p>

### A tool environment is missing packages after an interrupted reinstall

An interrupted reinstall can leave `vaultspec-rag` unable to run, reporting
`ModuleNotFoundError`. In this state, the command can't generate a repair command.

[Report the failed command](https://github.com/nevenincs/vaultspec-rag/issues) with the
error, operating system, Python version, and output of
`uv tool list --show-paths --show-python --show-with`. Include the command that was
interrupted. Don't force another reinstall while the service or an assistant session
still uses the tool environment: `uv tool install --force` removes the environment's
contents before writing the new ones, and a file it cannot remove leaves the
installation in exactly this state. The repair in
[pin the GPU build](#pin-the-gpu-build) is not a forced reinstall and does not have
this failure mode.

<p id="server-start-cannot-find-the-qdrant-binary"></p>

### `server start` can't find the Qdrant binary

`server start` downloads the Qdrant server when none is installed, so this message
appears only when that download is switched off, with `--no-qdrant-auto-provision` or
`VAULTSPEC_RAG_QDRANT_AUTO_PROVISION=0`. Install the Qdrant binary, then retry your
original start command, or rerun the start with `--qdrant-auto-provision`. For a
client, add `uv run`:

```bash
vaultspec-rag server qdrant install
```

To use the local-only backend instead, follow [storage backends](backends.md).

<p id="a-qdrant-on-path-is-no-longer-used"></p>

### A `qdrant` on `PATH` is no longer used

Earlier releases ran a `qdrant` executable found on `PATH` when no other one was
configured. That lookup is removed: on Windows it searched the working directory first,
and it ran a server of unknown version without checking it. A system `qdrant` is now
ignored, and a start that relied on it downloads the managed server instead.

To keep using your own executable, name it and vouch for it, with two settings that are
only accepted together:

- `VAULTSPEC_RAG_QDRANT_BINARY` is its absolute path. It must name a regular file.
- `VAULTSPEC_RAG_QDRANT_BINARY_SHA256` is the SHA256 of that file. Print it with
  `Get-FileHash -Algorithm SHA256 <path>` on Windows, or `sha256sum <path>` or
  `shasum -a 256 <path>` elsewhere.

The file is hashed and compared with the digest before every launch, restarts included,
and a file that does not match is never run. Setting only one of the two, or a path
that is not an absolute path to a regular file, stops `server start` with
`qdrant_binary_invalid` rather than falling back to another server. Both settings are
read from the process environment only; a workspace file cannot name a binary for the
service to run.

`server start` announces such a server as operator-supplied, and
`vaultspec-rag server qdrant status` labels its source `operator-supplied (env)`.

Earlier releases could also register an executable by copying it into the managed
directory. That route is removed: the managed directory now holds the pinned release
only, and an executable registered that way no longer runs.
`vaultspec-rag server qdrant status` reports it and names what to do.

<p id="the-qdrant-download-failed-a-checksum"></p>

### The Qdrant download fails a checksum

The archive, or the executable inside it, didn't match the digest committed with this
release. Nothing was installed, and an install that was already there is untouched.
Retry once: a truncated transfer fails this way. A mismatch that repeats means the
source is serving different bytes than the release was built against. If you set a
mirror with `VAULTSPEC_RAG_QDRANT_RELEASE_BASE_URL`, check the mirror; see
[managed server provisioning](configuration.md#managed-server-provisioning). The
digests themselves cannot be configured.

On a machine with no route to the release source, copy the official release archive for
your platform onto it and install from that file:

```bash
vaultspec-rag server qdrant install --archive <file>
```

The file passes the same two checks as a download, and no request is made.

<p id="the-qdrant-download-is-interrupted-or-waits"></p>

### The Qdrant download is interrupted or waits

An interrupted transfer is retried, up to three attempts in all, and the whole download
has a 15 minute limit. A checksum mismatch, a refusal from the source such as a missing
file, a certificate failure, and a redirect to a host outside the allowed set are not
retried: they fail at once with the reason.

Only one command provisions the server at a time. A second `server start` or
`server qdrant install` run meanwhile reports that it is waiting for the first, then
finds the install present and downloads nothing.

On Windows a running server holds its executable open, so `server qdrant install`
with `--upgrade` or `--archive` fails while the service runs. Run
`vaultspec-rag server stop` first.

<p id="the-installed-qdrant-server-fails-its-check"></p>

### The installed Qdrant server fails its check

`server start` reports `qdrant_binary_unverified` and refuses to run the server. The
installed executable is checked against its committed digest before every launch, and
it no longer matches: the file was modified, or the install is incomplete. Replace it
with the pinned release:

```bash
vaultspec-rag server qdrant install --upgrade
```

`vaultspec-rag server qdrant status` shows the same refusal as its detail line.

<p id="the-linux-x64-server-build"></p>

### The Linux x64 server build

On Linux x64 the managed server is now the static musl build, as it already was on
Linux arm64. It doesn't depend on the host's C library, so it starts on distributions
whose glibc is older than the one the upstream gnu build needs. An install made by an
earlier release keeps running and keeps verifying, and `--upgrade` leaves a healthy
install alone. To move it to the musl build, stop the service, remove the install with
`vaultspec-rag server qdrant clean --yes`, and start the service again; index data is
not touched.

A platform with no upstream Qdrant build is reported as unsupported rather than given
another platform's server. Supply your own executable there, as described under
[a `qdrant` on `PATH` is no longer used](#a-qdrant-on-path-is-no-longer-used).

### Pin the GPU build

This applies to [the self-contained tool](#carry-the-gpu-packages-in-the-tool-itself) -
the one installed with the `gpu` extra - never to the default standalone tool, which
carries no PyTorch of its own. Use these steps when that self-contained tool on Linux or
Windows has a missing or CPU-only PyTorch, or when `server doctor` reports that its
receipt records no CUDA source. Apple silicon uses the standard wheel's Metal support
and needs none of this.

The repair is two commands, in order. The first installs the CUDA build of PyTorch into
the environment through uv's pip interface, naming the release the environment already
has; the second re-runs the tool installation with the CUDA index and its resolution
strategy, which changes no package and only records those options in the installation
receipt, so every later upgrade keeps resolving the GPU build. The order matters: an
install that changes a package re-installs the tool's launchers, and one that is running
cannot be replaced.

Neither step removes anything, so the service and any assistant session may keep running
throughout. The installed release, the extras and the Python version all stay as they
are. Project `pyproject.toml` settings and `uv sync` do not configure tool environments.

If `ModuleNotFoundError` prevents `vaultspec-rag` from running, see
[the interrupted reinstall entry](#a-tool-environment-is-missing-packages-after-an-interrupted-reinstall)
before attempting these steps.

1. Ask what this installation needs:

   ```sh
   vaultspec-rag server doctor
   ```

   It names the compute build, what the next upgrade would resolve, and the two commands
   for this installation. `vaultspec-rag install --dry-run` prints the same commands
   without changing anything.

1. Let the installer apply them, or run them yourself in the order given:

   ```sh
   vaultspec-rag install --yes
   ```

   With a terminal it asks first; `--yes` answers in advance. `--force` does not: it
   authorises overwriting this product's own files, not installing packages. The
   installer then verifies both the installed build and the receipt, and reports a
   failure rather than a repair if either is wrong.

1. Restart the service so it uses the new build:

   ```sh
   vaultspec-rag server stop
   vaultspec-rag server start
   ```

   A process that was already running keeps the PyTorch it imported at startup. Restart
   any assistant session that runs the MCP adapter for the same reason.

1. Confirm with `vaultspec-rag server doctor` that compute is ready and the receipt
   keeps it, then rerun the checks in [start and verify](#start-and-verify).

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
`uv run`. Uninstall is destructive by default: without `--force`, or `--dry-run` to
preview instead, the command refuses to run rather than silently previewing.

1. From the repository root, preview the changes:

   ```sh
   vaultspec-rag uninstall --dry-run
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
- [Provisioning](provisioning.md) answers what is downloaded, how it is checked, and
  how to run without a network.
- [Backends](backends.md) answers when to choose the local-only backend over the managed
  Qdrant server.
- [Storage maintenance](storage-maintenance.md) answers how to inspect and reclaim index
  storage.
- [Configuration](configuration.md) answers which environment variables and settings
  exist.
- The [command reference](cli.md) lists every command and flag. The
  [automation guide](automation.md#exit-codes-and-error-strings) lists exit codes.
- [MCP integration](mcp.md) answers how an AI assistant reaches the service.
- The [architecture overview](architecture.md) answers how the service, models, and
  index fit together.
- The [glossary](glossary.md) defines the terms these guides use.
- [Ask for help](#ask-for-help) names the support channel.

## Appendix: reference

### Packages and what they can run

vaultspec-rag has two extras, `gpu` and `mcp`. The `gpu` extra installs the model stack.
The `mcp` extra adds the library the model-free MCP standard input/output (stdio)
adapter needs. Every package installs the `vaultspec-search-mcp` command, but that
command refuses to run without the `mcp` extra.

| Package                  | Installation | Loads models | Needs a GPU | Running `server start`                              | Can run the MCP adapter |
| ------------------------ | ------------ | ------------ | ----------- | --------------------------------------------------- | ----------------------- |
| `vaultspec-rag`          | Client       | No           | No          | Builds a private GPU environment and serves from it | No                      |
| `vaultspec-rag[mcp]`     | Client       | No           | No          | Builds a private GPU environment and serves from it | Yes                     |
| `vaultspec-rag[gpu]`     | Host         | Yes          | Yes         | Runs the service directly                           | No                      |
| `vaultspec-rag[gpu,mcp]` | Host         | Yes          | Yes         | Runs the service directly                           | Yes                     |

In `tool` mode, the MCP entry the repository setup writes fetches the adapter with
`uvx`, whatever the installation contains.

Building a private GPU environment needs uv and a supported GPU on the machine; see
[the service runtime could not be created](#the-service-runtime-could-not-be-created)
when it can't. The service is loopback-only: a client and whatever runs the service
share one machine, and this isn't a documented network deployment across machines.
`VAULTSPEC_RAG_QDRANT_URL` can point at remote vector storage, but Qdrant doesn't run
the dense encoder, sparse encoder, or reranker; a supported GPU is still needed
somewhere on the machine.

### Inspect the archive layout

Every verified release archive contains these members at its top level:

| Member                                                 | Purpose                                            |
| ------------------------------------------------------ | -------------------------------------------------- |
| `vaultspec-rag` or `vaultspec-rag.exe`                 | Command-line client and service control            |
| `vaultspec-search-mcp` or `vaultspec-search-mcp.exe`   | MCP stdio adapter                                  |
| `vaultspec-rag-monitor` or `vaultspec-rag-monitor.exe` | Self-contained React monitor and local bridge      |
| `LICENSE`                                              | Project licence                                    |
| `README.txt`                                           | Target and runtime notes                           |
| `manifest.json`                                        | Machine-readable bundle metadata and member hashes |

`manifest.json` records the schema, product and version, release tag, target, archive
format and platform metadata. Schema `vaultspec.release-bundle.v2` records runtime and
requirements separately for each executable under `components`, including native
browser verification of the monitor. Its `files` array records the
role, size, and SHA-256 of each executable and release document.

Confirm `archive.name` matches the downloaded filename, `target` matches your machine,
and every `files[].name` exists with its listed size and digest. `manifest.json`
doesn't hash the enclosing archive; `SHA256SUMS` is the source of truth for that digest.
The manifest's `platform.glibc_floor` records the enclosing Linux bundle floor.
The monitor's component records its independently measured `glibc_required`; it does
not lower the RAG bundle's glibc 2.39 requirement. Release CI and public acquisition
also authenticate the archive's GitHub/Sigstore attestation against the release
repository, signing workflow, tag and source commit before inspecting or extracting
it. The executable hashes inside that authenticated archive are checked before launch.

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
