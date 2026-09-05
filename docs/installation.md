# Installing vaultspec-rag

## What you need before you start

For local inference, use an NVIDIA GPU with CUDA on Linux or Windows, or Apple
silicon with MPS on macOS. CPU inference and AMD GPUs are unsupported.

Choose a service resource profile:

| Profile                     | Total system RAM | Free index-store space | Free CUDA memory at startup |
| --------------------------- | ---------------- | ---------------------- | --------------------------- |
| `managed-service` (default) | 16 GiB           | 8 GiB                  | 12 GiB                      |
| `embedded-local`            | 8 GiB            | 5 GiB                  | 6 GiB                       |

The CUDA figures are the default model-loading admission limits; they do not apply
to Apple silicon. See [GPU memory settings](configuration.md#index-resource-bounds-and-memory-ceilings).
Allow additional disk space for the model cache.

Use `embedded-local` for smaller corpora or a machine with 8 GiB of unified memory.
This profile also supports the server. Set
`VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local` in the service startup environment;
setting it only in the query client's shell does not configure the service.
Run `vaultspec-rag status` to check the active profile and corpus limits.

Ensure network access to the package index, model host, and search-server release downloads.

For a Python installation, install [uv](https://docs.astral.sh/uv/) and use CPython
3.13 or 3.14. Alternatively, [install without Python](#install-without-python).

## Confirm your GPU is visible

On Linux or Windows:

```bash
nvidia-smi
```

If that lists your card and a driver version, the driver is loaded. On Apple silicon,
macOS supplies the driver; no CUDA installation is needed. PyTorch must report MPS available.

vaultspec-rag refuses to start when neither CUDA nor MPS is available, and it refuses MPS when `PYTORCH_ENABLE_MPS_FALLBACK` enables processor execution. Neither platform falls back.

## Choose an install route

Four routes. Pick one.

### Trying it without commitment

Runs in a throwaway environment and leaves nothing in your project:

```bash
uvx --from "vaultspec-rag[gpu]" vaultspec-rag install
```

### Adding it to a project

Choose this when the project itself should carry the dependency, so teammates and continuous integration (CI) resolve the same version:

```bash
uv add "vaultspec-rag[gpu]"
```

### Installing it as a standalone tool

Choose this when you want one copy on your machine to use across several projects, and no project should list it as a dependency. This route needs a pinned GPU build:

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]"
```

### Installing a prebuilt binary

Choose this when the machine has no Python toolchain at all. See [Install without Python](#install-without-python).

### Which sections you still need

The first three routes can install the bare package instead of `[gpu]`. That control-plane-only install runs service and diagnostic commands but cannot index or search locally, because it omits PyTorch and the model stack. It avoids roughly 5 GB of dependencies. The binary route always carries the GPU build.

A control-plane-only install is a supported state rather than a broken one: `install` completes, and `server doctor` reports torch as absent without calling the environment defective. The service still refuses to start, because it cannot serve a search without a model. The way out is choosing the `[gpu]` extra, not repairing anything.

| Your route                         | Sections you still need                                                                                                                 |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Trying it without commitment       | [What the install command provisions](#what-the-install-command-provisions), [Verify the install](#verify-the-install)                  |
| Adding it to a project             | [Install with Python](#install-with-python) in full, [Verify the install](#verify-the-install)                                          |
| Installing it as a standalone tool | [Install with Python](#install-with-python) in full, including [the pin](#pin-the-gpu-build), [Verify the install](#verify-the-install) |
| Installing a prebuilt binary       | [Install without Python](#install-without-python), [Verify the install](#verify-the-install)                                            |

## Install without Python

**Windows and Linux only.** The lane publishes `x86_64` Windows, and `x86_64` and `aarch64` Linux. It publishes no macOS artifact and no macOS formula, so on Apple silicon use one of the Python routes. The GPU requirement is unchanged.

On Linux, first check [which binary your distribution can run](#which-linux-binary-your-distribution-can-run). The binaries carry a C library floor that installing from the package index does not.

`vaultspec-rag` and `vaultspec-search-mcp` ship as standalone binaries that need no Python toolchain. They're published through the account channel root, `nevenincs/homebrew-tap`, which carries every vaultspec product, so you add it once.

On Windows:

```powershell
scoop bucket add nevenincs https://github.com/nevenincs/homebrew-tap
scoop install vaultspec-rag
```

On Linux:

```sh
brew tap nevenincs/tap https://github.com/nevenincs/homebrew-tap
brew install vaultspec-rag
```

The binaries bootstrap the same GPU PyTorch build this project resolves, pinned from the lockfile, so a binary cannot drift onto a different build than a Python install would get.

First launch downloads that build. On Windows that's about 1.9 GB and self-contained. On Linux the wheel itself is about 500 MB, but it pulls the CUDA runtime packages as dependencies, so budget several gigabytes there too.

Nothing in [Install with Python](#install-with-python) applies to this route. Go to [Verify the install](#verify-the-install).

## Install with Python

The following steps run in order. Each says which routes it applies to.

### What the install command provisions

*All Python routes.*

```bash
uv run vaultspec-rag install
```

It provisions three things and enrols a fourth:

- The CUDA (`cu130`) PyTorch build, which it records as a Linux and Windows package source in `pyproject.toml`. This reports `configured, sync pending`. The source marker is inactive on macOS, where normal resolution installs the MPS-capable standard wheel.
- The dense, sparse, and reranker model files, in the Hugging Face cache.
- The pinned Qdrant search-server binary, downloaded and checksum-verified.

It also enrols the agent-facing MCP search surface, which is on by default and
writes an entry your coding agent can call. `--no-mcp` opts out and leaves a
workspace with the command line only. See [use with MCP clients](mcp.md).

The PyTorch step asks before editing `pyproject.toml`, and **the prompt defaults to no**. Type `y` to accept. For an unattended run, pass `--yes` to accept it, or `--no-torch-config` to skip that step and manage PyTorch yourself.

Each dependency reports its outcome as `created`, `updated`, `unchanged`, `skipped`, or `failed`. The run is idempotent: re-running a satisfied dependency reports `unchanged` and makes no network call.

Here is the whole of it, on a project that already had a `pyproject.toml`, with
the prompt left unanswered:

```text
Patch <project>/pyproject.toml with the cu130 torch index? This lets uv resolve
the CUDA torch wheel. [y/n] (n): vaultspec-rag installed
Target: <project>
created 4 directories
seeded 3 bundled files:
  [ADD] rules/vaultspec-rag.builtin.md
  [ADD] skills/vaultspec-rag-discovery/SKILL.md
  [ADD] mcps/vaultspec-rag.builtin.json
tool integrations: added 8
Claude MCP: added 1
Codex MCP: added 1
MCP optional dependency: tool
PyTorch configuration: needs confirmation
Provisioning: mixed
  PyTorch: skipped (torch configuration handled by the dedicated PyTorch step
  (it patches pyproject.toml; see 'PyTorch configuration' above) - not re-run
  here)
  Models: already present (all 3 model repos already cached)
  Qdrant binary: already present (Verified install already present; nothing to
  do.)
Warning: torch-config patch skipped: confirmation prompt hit EOF
(non-interactive stdin). Re-run with --yes or --force to apply, or
--no-torch-config to opt out.
```

If the other installation steps succeed, answering `n` returns `0`;
missing confirmation input returns `2`. See the [install exit codes](cli.md#install).

### Install less than the default

*All Python routes. These are decisions you make when you run `install`, not afterwards.*

- `--local-only` selects the embedded on-disk store, skips the Qdrant download, and persists the choice so a later `server start` honors it. Throughput drops under concurrent load. It doesn't change Python dependencies, CUDA, or model downloads. See [backends](backends.md).
- `--skip-torch`, `--skip-models`, `--skip-qdrant` each drop one dependency. `--skip-qdrant` is redundant under `--local-only`.
- `--no-torch-config` leaves `pyproject.toml` untouched.
- `--no-mcp` skips the MCP enrolment and its optional dependency, leaving a
  CLI-only workspace. On Windows it also skips `pywin32`.
- `--dry-run` reports `preview only` for every step, writes nothing, and never prompts.

The [command-line reference](cli.md) has the complete flag set.

### Choose where vaultspec-rag lives

*Project and standalone tool routes.*

`install` records where vaultspec-rag sits in your workspace. That placement decides how vaultspec-rag launches its Model Context Protocol (MCP) server, which exposes search to AI assistants. See [MCP integration](mcp.md) for the server itself.

```bash
uv run vaultspec-rag install --mode tool
```

- `tool` launches the server through an ephemeral `uvx` invocation, independent of any project environment. This is the default when your project doesn't depend on vaultspec-rag.
- `dependency` launches it through `uv run` inside the project environment. A runtime dependency ships with your project's published distribution.
- `dev` launches identically to `dependency` but records the placement as development-only, so it doesn't ship.

With no `--mode`, `install` detects the placement from `pyproject.toml`: a runtime dependency resolves to `dependency`, a default dev-group entry to `dev`, anything else to `tool`. It refuses an explicit `--mode dependency` or `--mode dev` when no `pyproject.toml` exists to declare against, rather than guessing.

`install` commits the choice to `.vaultspec/workspace.json`, per package, so a workspace holding both vaultspec-rag and vaultspec-core keeps each placement without one overwriting the other. Placement is independent of `--local-only`: placement decides where the tool lives, the backend flag decides where the index is stored.

### Complete the install with a sync

*Project and standalone tool routes.*

The install isn't finished until the environment resolves the platform build. Until it does, searches cannot run:

```bash
uv sync
```

To fold this into the install step, pass `install --sync`, which runs `uv sync --reinstall-package torch` after the config step.

### Pin the GPU build

*Standalone tool route only.*

A tool environment must pin the CUDA wheel in its receipt. Without the pin, every `uv tool upgrade` re-resolves PyTorch from the package index and silently replaces the GPU build with a processor-only one. The service then refuses to start.

Nothing may be running out of the tool environment while the pin is applied. `--force` removes the installed distributions before it writes the replacements, and a held file stops it part-way: on Windows the run dies on the locked `Scripts` directory. What is left is an environment missing most of its packages, and the next `vaultspec-rag` invocation ends in a `ModuleNotFoundError` naming some dependency of a dependency. The service is one holder. Every editor or agent session with the vaultspec-rag MCP server connected is another, each running a `vaultspec_rag.server` of its own, and closing the editor window is what releases it. Stop the service, close those sessions, and confirm nothing is left:

```bash
vaultspec-rag server stop
pgrep -af vaultspec_rag
```

```powershell
vaultspec-rag server stop
Get-Process python | Where-Object Path -like '*tools*vaultspec-rag*'
```

The exact command depends on your interpreter, platform, and PyTorch release, so don't copy one from documentation. Both `vaultspec-rag server start` and `vaultspec-rag install` print the correct command for your machine whenever they detect a processor-only tool environment. Run either to get it. Its shape, for Python 3.13 and torch 2.13.0 on Windows, is:

```bash
uv tool install --force --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.13.0%2Bcu130-cp313-cp313-win_amd64.whl"
```

The `--python` request must match the wheel's `cp3XX` tag, or the install fails on a tag mismatch. Two alternatives look equivalent and are not:

- `--index` is not recorded in the tool receipt, so an upgrade drops it.
- The project-scoped pin that `install` writes into `pyproject.toml` never reaches tool environments.

On Apple silicon no pin is needed, because the standard macOS wheel already supplies MPS.

If a tool environment has already lost its GPU build, see [When something goes wrong](#when-something-goes-wrong).

## Verify the install

Check the version:

```bash
uv run vaultspec-rag --version
```

This reports `vaultspec-rag v0.4.23`. <!-- x-release-please-version -->

Run the readiness report, which checks PyTorch and the resolved GPU backend, the model cache, and the Qdrant binary and server:

```bash
uv run vaultspec-rag server doctor
```

Check `Readiness` and the status of each dependency. To interpret the report and
check index coverage, follow [verify the index](verification.md).

## When something goes wrong

### Telling two lookalikes apart

A missing driver and a processor-only environment both end in a refusal to start. `nvidia-smi` distinguishes them. If it doesn't list your card, the driver isn't loaded, and reinstalling PyTorch doesn't help. If it does list your card but `server doctor` reports the `torch` line as not ready, the driver is fine and your environment holds the wrong build.

### The driver isn't loaded

Fix that before installing anything further. On Apple silicon, an unavailable MPS backend or `PYTORCH_ENABLE_MPS_FALLBACK=1` is an explicit startup failure, not a fallback.

### The environment has a processor-only build

On Linux or Windows run `uv sync`, or `uv run vaultspec-rag install --sync`. On Apple silicon, sync the standard wheel and check that `torch.backends.mps.is_available()` is true.

### A tool environment lost its GPU build

Repair it in place:

```bash
uv pip install --python "<tool-env python>" --reinstall --torch-backend=cu130 torch
```

The next upgrade undoes this. [The receipt pin](#pin-the-gpu-build) is the durable fix.

Two things break tool environments in the first place:

- A forced reinstall while something still runs out of the environment. uv removes the installed packages before it writes the replacements, and a file it cannot remove stops it there, so the environment is left unrunnable rather than unchanged. The service is the obvious holder; an editor or agent session with the MCP server connected is the easily missed one.
- After such a failure, `uvx vaultspec-rag` silently falls back to a cached ephemeral environment instead of the installed tool. `server start` warns when it detects that fallback.

A process holds an environment in either of two ways, and only the first is obvious. Its **executable** may live inside the tree - the service, an MCP server, any `vaultspec-rag` command. Or its **working directory** may sit inside the tree, which blocks removal even when the program itself has nothing to do with vaultspec-rag: a shell left in the tool directory, an editor opened on it. End the first kind; leave the directory for the second.

Only a blocked removal is destructive. A wheel that cannot be fetched, an interpreter tag that matches nothing, an empty cache with no network - each fails before uv replaces anything, and leaves the environment and its receipt exactly as they were. There is no need to fear a bad pin: fear a busy one.

Stop the service and close every MCP client session before any forced reinstall or upgrade.

### `install` refused to repair the tool environment

It printed the pinned command instead of running it, and named the processes holding the environment. That is the whole behaviour: the installer never replaces a tool environment, because it runs inside the only environment it would ever target, and a replacement issued from there has to remove the interpreter issuing it.

Each holder is listed with its pid and what to do about it - end the process, or move it out of the directory. Clear them, then run the printed command from a shell that holds nothing in that tree. `--no-tool-repair` skips the check entirely if you would rather manage the environment yourself; `--no-torch-config` does not, it governs only the `pyproject.toml` step.

### A tool environment is missing packages after a failed reinstall

The symptom is a `ModuleNotFoundError` on any invocation, naming a package you never installed by hand - a dependency of a dependency, such as `typer`'s `annotated_doc`. The environment holds whatever the interrupted reinstall had already removed and not yet replaced.

The in-place torch repair above does not fix this. It reinstalls torch and torch's dependencies, and the missing packages are not among them. Re-run the [pinned install](#pin-the-gpu-build) instead, with nothing running out of the environment, which rebuilds it and records the pin in the receipt. Check that it landed:

```bash
grep -c 'download.pytorch.org' "$(uv tool dir)/vaultspec-rag/uv-receipt.toml"
```

A receipt naming only `vaultspec-rag`, with no wheel URL, is an environment that ran a reinstall without the pin, or one whose pinned run did not finish.

### `install` refused to edit `pyproject.toml`

It needs consent it doesn't have, and exits non-zero. Re-run with `--yes` to approve, or `--no-torch-config` to manage PyTorch yourself.

### `server start` cannot find the Qdrant binary

Provision it, or run without the server:

```bash
uv run vaultspec-rag server qdrant install
uv run vaultspec-rag server start --local-only
```

### The Qdrant download failed a checksum

The archive didn't match the committed digest, and the command deleted the partial file. Retry. On an air-gapped host, register your own executable with `server qdrant install --binary PATH`.

Every recovery on this page is safe to run more than once. `install` reports `unchanged` for satisfied dependencies, and the repair commands re-resolve from scratch, so if you've already tried one, you haven't made anything worse.

For anything not covered here, the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues) takes questions as well as bug reports. It's the only support channel.

## The model cache and its first download

The first index or search downloads the dense, sparse, and reranker model files once, so it runs slower than later work. The files land in the Hugging Face cache. If they appear to re-download every run, point `HF_HOME` at a persistent location; see the [configuration guide](configuration.md).

If a run exhausts GPU memory, that's a runtime concern rather than an install one: see [tuning for memory and speed](configuration.md#tuning-for-memory-and-speed). On MPS, memory is unified with the rest of the system rather than dedicated.

## Upgrade

Bump the dependency and sync:

```bash
uv add --upgrade vaultspec-rag
uv sync
```

`uv sync` refetches the platform PyTorch build if it changed. Two follow-ups apply only when a release changes bundled content. Run `uv run vaultspec-rag install --upgrade` to refresh the bundled rules and integration files. If a release pins a newer Qdrant, run `uv run vaultspec-rag server qdrant install --upgrade`.

Nothing migrates and nothing reindexes automatically. If a release notes a changed embedding or reranker model, reindex by hand with `index --rebuild`.

One refresh matters for AI-assistant integrations. Workspaces set up before the tokenized launch format still carry a static MCP seed that bypasses vaultspec-core's launch renderer. `install --upgrade` rewrites it to the tokenized form, which renders a launch matching the workspace's declared placement. If an assistant's MCP config predates that refresh, re-run the client's MCP setup afterwards.

The `server updates` commands are unrelated to upgrades; they control the automatic-reindex watcher, covered in [service mode](service-mode.md).

## Remove it

Uninstalling removes the project's integration, not the package. It preserves
data by default. Read the [uninstall flags](cli.md#uninstall) before choosing
data removal.

If RAG is a project dependency, prefix `vaultspec-rag` commands with `uv run`.

1. From your project root, preview the integration changes:

   ```sh
   vaultspec-rag uninstall
   ```

1. Review the preview, then apply it:

   ```sh
   vaultspec-rag uninstall --force
   ```

1. For optional shared-index cleanup, [inspect the store](storage-maintenance.md#inspect-what-is-stored)
   and follow [storage maintenance](storage-maintenance.md#reclaim-space-manually).
   Models and Qdrant binaries are shared across projects; removing one project's
   setup does not require deleting them.

1. Before removing the package, run `vaultspec-rag server stop` and close connected
   MCP clients. Stopping the service affects its other clients too.

1. Remove the package using your installation method:

   | Installation          | Command                           |
   | --------------------- | --------------------------------- |
   | uv project dependency | `uv remove vaultspec-rag`         |
   | uv tool               | `uv tool uninstall vaultspec-rag` |
   | Scoop                 | `scoop uninstall vaultspec-rag`   |
   | Homebrew              | `brew uninstall vaultspec-rag`    |

## Which Linux binary your distribution can run

A binary links against whatever C library built it, so a download labelled only "Linux" may not run on your distribution.

| Binary                      | Requires   | Covers                                                |
| --------------------------- | ---------- | ----------------------------------------------------- |
| `x86_64-unknown-linux-gnu`  | glibc 2.28 | Debian 10+, Ubuntu 20.04+, RHEL 8+, Amazon Linux 2023 |
| `aarch64-unknown-linux-gnu` | glibc 2.28 | Debian 10+, Ubuntu 20.04+, RHEL 8+, Amazon Linux 2023 |

Check yours with `ldd --version`. On an older distribution the binary doesn't start, and the error names a missing symbol version rather than saying the distribution is too old.

Every currently offered download meets the 2.28 floor. Older `aarch64` binaries, built before that floor dropped, require glibc 2.39; if one refuses to start, take the current binary instead.

Installing from the package index has no such floor and works wherever the Python and GPU requirements are met.

## Where to go next

- [Getting started](getting-started.md) walks through your first index and search.
- [Search and index](search-and-index.md) answers how ranking works and what the filters do.
- [Backends](backends.md) answers when to choose the on-disk store over the managed server.
- [Configuration](configuration.md) answers which environment variables and settings exist.
- [Project overview](../README.md) answers what vaultspec-rag is, if you're still deciding.
