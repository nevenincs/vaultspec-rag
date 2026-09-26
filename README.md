<img src="assets/logo.png" width="150" alt="vaultspec-rag logo">

# vaultspec-rag

The semantic search component for vault and code.

Grep finds a concept only when you already know its name. Why code looks the way it
does is often written in a decision record that's hard to find. vaultspec-rag searches a
repository's source code and its decision records by meaning. Run it from the command
line, or connect an AI assistant through the Model Context Protocol (MCP), so the
assistant finds both the code and the decisions behind it. Search combines a model that
matches meaning with one that matches exact terms, then reranks the results. An optional
paid service, Typesafe, can refine the ranking.

One background service per machine runs the models on the local graphics processing
unit (GPU), because they're too slow to be useful on a central processing unit (CPU). A
host installation starts that service; a client installation only sends it requests.
The [architecture overview](docs/architecture.md) explains how the pieces fit.

<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/stars/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="GitHub Stars" src="https://www.shieldcn.dev/github/stars/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/forks/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="GitHub Forks" src="https://www.shieldcn.dev/github/forks/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/watchers/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Watchers" src="https://www.shieldcn.dev/github/watchers/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/branches/nevenincs/vaultspec-rag.svg?variant=ghost&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Branches" src="https://www.shieldcn.dev/github/branches/nevenincs/vaultspec-rag.svg?variant=ghost&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/contributors/nevenincs/vaultspec-rag.svg?theme=emerald&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Contributors" src="https://www.shieldcn.dev/github/contributors/nevenincs/vaultspec-rag.svg?theme=emerald&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/last-commit/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Last commit" src="https://www.shieldcn.dev/github/last-commit/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/commits/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Commits" src="https://www.shieldcn.dev/github/commits/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/open-issues/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Open issues" src="https://www.shieldcn.dev/github/open-issues/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/closed-issues/nevenincs/vaultspec-rag.svg?variant=ghost&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Closed issues" src="https://www.shieldcn.dev/github/closed-issues/nevenincs/vaultspec-rag.svg?variant=ghost&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/open-prs/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Open PRs" src="https://www.shieldcn.dev/github/open-prs/nevenincs/vaultspec-rag.svg?variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/closed-prs/nevenincs/vaultspec-rag.svg?variant=ghost&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Closed PRs" src="https://www.shieldcn.dev/github/closed-prs/nevenincs/vaultspec-rag.svg?variant=ghost&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/merged-prs/nevenincs/vaultspec-rag.svg?variant=ghost&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Merged PRs" src="https://www.shieldcn.dev/github/merged-prs/nevenincs/vaultspec-rag.svg?variant=ghost&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/badge/dynamic/json.svg?url=https%3A%2F%2Fpypi.org%2Fpypi%2Fvaultspec-rag%2Fjson&amp;query=%24.info.version&amp;label=release&amp;variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Release" src="https://www.shieldcn.dev/badge/dynamic/json.svg?url=https%3A%2F%2Fpypi.org%2Fpypi%2Fvaultspec-rag%2Fjson&amp;query=%24.info.version&amp;label=release&amp;variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/badge/dynamic/json.svg?url=https%3A%2F%2Fapi.github.com%2Frepos%2Fnevenincs%2Fvaultspec-rag%2Factions%2Fworkflows%2Fmerge-gate.yml%2Fruns%3Fbranch%3Dmain%26per_page%3D1&amp;query=%24.workflow_runs%5B0%5D.conclusion&amp;label=build&amp;variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Build" src="https://www.shieldcn.dev/badge/dynamic/json.svg?url=https%3A%2F%2Fapi.github.com%2Frepos%2Fnevenincs%2Fvaultspec-rag%2Factions%2Fworkflows%2Fmerge-gate.yml%2Fruns%3Fbranch%3Dmain%26per_page%3D1&amp;query=%24.workflow_runs%5B0%5D.conclusion&amp;label=build&amp;variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/badge/runtime-Python%203.13%20%7C%203.14%20%7C%20CUDA%20%7C%20MPS-57606a.svg?variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Runtime" src="https://www.shieldcn.dev/badge/runtime-Python%203.13%20%7C%203.14%20%7C%20CUDA%20%7C%20MPS-57606a.svg?variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/github/license/nevenincs/vaultspec-rag.svg?variant=ghost&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="License" src="https://www.shieldcn.dev/github/license/nevenincs/vaultspec-rag.svg?variant=ghost&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="https://www.shieldcn.dev/badge/Agent--friendly-AGENTS.md-D97757.svg?variant=secondary&amp;size=xs&amp;mode=dark&amp;font=roboto"><img alt="Agent-friendly AGENTS.md" src="https://www.shieldcn.dev/badge/Agent--friendly-AGENTS.md-D97757.svg?variant=secondary&amp;size=xs&amp;mode=light&amp;font=roboto"></picture>

[Install](#install) · [Use it](#use-it) ·
[Docs](#documentation) · [Help](#status-and-help)

Use it with [vaultspec-core](https://github.com/nevenincs/vaultspec-core) or
independently in another repository. To index PDFs and other formats,
[connect a converter](#read-pdfs-and-other-formats).

## What you need

- Python 3.13 or 3.14 with [uv](https://docs.astral.sh/uv/getting-started/installation/),
  or a [prebuilt binary](docs/installation.md#install-a-prebuilt-binary).
- A supported GPU: an NVIDIA GPU with CUDA, NVIDIA's GPU computing platform, on Linux or
  Windows, or Apple silicon on macOS. vaultspec-rag doesn't run on a CPU or on AMD GPUs.
- Enough memory for a resource profile. The default profile needs 16 GiB of system
  memory and, on CUDA, 12 GiB of free GPU memory. The smaller `embedded-local` profile
  needs 8 GiB of system memory and 6 GiB of free GPU memory.
- Several gigabytes of disk for a one-time model download.
- By default, search also uses the sparse model
  [`naver/splade-v3`](https://huggingface.co/naver/splade-v3), which matches exact terms.
  It needs a Hugging Face account that has accepted the model's non-commercial licence.
  The [dense-only setup](docs/installation.md#the-model-cache-and-its-first-download)
  uses only the meaning model. It needs no Hugging Face login and gives up exact-term
  matching.

The [installation requirements](docs/installation.md#what-you-need-before-you-start)
list the full figures, and the [glossary](docs/glossary.md) defines the terms used here.

## Install

- If vaultspec-rag isn't installed on this machine yet, install the
  [host](#host-installation). It serves every repository on the machine and gives AI
  assistants the search tools.
- If a host installation already runs the service, add a
  [client](#client-in-a-python-project) to any uv-managed Python project that must list
  vaultspec-rag as a dependency. A client installs no GPU packages or models and sends
  every request to the host's service on the same machine.

The [installation guide](docs/installation.md#choose-what-this-environment-runs) covers
every route, and its [troubleshooting](docs/installation.md#when-something-goes-wrong),
[upgrade](docs/installation.md#upgrade), and [removal](docs/installation.md#remove-vaultspec-rag)
sections cover what comes after.

### Host installation

Install the host once, as a standalone tool; it serves every repository on the machine.
The `[gpu]` extra adds PyTorch and the model libraries, and `[mcp]` adds the MCP adapter
that AI assistants launch. The Windows and Linux commands pin the CUDA build of PyTorch,
so later tool upgrades keep it.

Windows x64:

```powershell
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.14.0%2Bcu130-cp313-cp313-win_amd64.whl"
```

Linux x86_64 (glibc 2.28 or newer):

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.14.0%2Bcu130-cp313-cp313-manylinux_2_28_x86_64.whl"
```

Apple silicon macOS:

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]"
```

For other Python versions or Linux architectures, see
[GPU wheel selection](docs/installation.md#pin-the-gpu-build). If uv reports that its
executables directory isn't on your `PATH`, run `uv tool update-shell` and open a new
terminal.

By default, search needs access to the sparse model. If you can't accept its licence,
set `VAULTSPEC_RAG_SPARSE_ENABLED=0` in your user environment and skip to the
repository setup. Otherwise, accept the licence on the
[model page](https://huggingface.co/naver/splade-v3), then log in:

```bash
uvx --from huggingface_hub hf auth login
```

Alternatively, set `HF_TOKEN` in your user environment.

From the root of each repository you want to search, run the repository setup. It
doesn't reinstall the tool:

```bash
vaultspec-rag install --no-torch-config
```

The setup adds the AI-assistant integration and creates the `.vault/` folder for
decision records. On the first repository, it also downloads the search models and
Qdrant, the index server; later repositories reuse both. The first run downloads
several gigabytes. `--no-torch-config` leaves the repository's own PyTorch
configuration alone, because the tool already carries its PyTorch.

Start the service. It loads the models and waits until it's ready:

```bash
vaultspec-rag server start
```

The service doesn't start by itself after a reboot, so run `vaultspec-rag server start`
again then. To stop it, run `vaultspec-rag server stop`.

Check the installation:

```bash
vaultspec-rag server doctor
```

<p align="center">
<img src="assets/term-doctor.svg" alt="vaultspec-rag server doctor - service, GPU, model, and Qdrant readiness at a glance" width="880" />
</p>

Check that the report detects your GPU and finds every configured model and the Qdrant
binary. If it reports a problem, use the
[installation troubleshooting guide](docs/installation.md#when-something-goes-wrong).

### Client in a Python project

A client lets a project's own AI-assistant configuration launch the search tools from
the project environment, so collaborators get them with `uv sync`. Each collaborator
still needs their own host installation at the release the project pins.

1. In the host installation, run this command and note the release on the
   `Service release:` line:

   ```bash
   vaultspec-rag server status --verbose
   ```

1. From the project root, add the client pinned to that release:

   ```bash
   uv add --dev "vaultspec-rag[mcp]==<release>"
   ```

1. Set up the project. `--mode dev` makes the AI assistant launch the search tools from
   the project environment, even if the host installation set up the project first. A
   client skips PyTorch configuration and all downloads.

   ```bash
   uv run vaultspec-rag install --mode dev
   ```

1. Confirm the client reaches the service. `uv run vaultspec-rag server doctor` must
   show `release: <release> (matches this client)` and report PyTorch as not needed for
   this client installation. If the release doesn't match, repeat step 2 with the
   release from step 1.

Run the client as `uv run vaultspec-rag`, and start or stop the service from the host
installation. When you upgrade the host, move each client to the same release with the
[upgrade steps](docs/installation.md#upgrade).

## Use it

### Index and search

From the root of each repository you want to search, index it. The command queues
indexing jobs and prints their IDs:

```bash
vaultspec-rag index
```

Follow progress with `vaultspec-rag server jobs --watch`, and wait until the jobs finish
before searching. Afterwards, the service watches for file changes and updates the
index automatically.

Search source code with `--type code`, or decision records with `--type vault`. Results
list file paths with their matching passages:

```bash
vaultspec-rag search "parse query text into filters" --type code
```

A client runs the same commands with the `uv run` prefix. If results are missing or
incomplete, [check the index](docs/verification.md) and
[adjust the query](docs/query-craft.md). The
[getting-started tutorial](docs/getting-started.md) walks through a first search, and
[AI assistant setup](#use-it-from-an-ai-assistant) connects your AI assistant. See
[index maintenance](docs/search-and-index.md) for rebuilding or removing indexed
content.

### Optional Typesafe classification

Set `VAULTSPEC_RAG_TYPESAFE_API_KEY` in the service account's environment before
starting the server to opt into paid Typesafe classification. A valid, funded key
enables query interpretation and reranking using the full result content, including
removal of confidently irrelevant hits. The server sends queries and candidate
content to Typesafe; without a usable key, search keeps its existing local ranking.

`server start` and `server status` show the running server's enrollment and whether
a recent evaluation succeeded. No separate enable flag is needed. See
[activation, fallback, and status meanings](docs/configuration.md#typesafe-enrollment)
before enabling it. The local search models and GPU are still required.

### Other ways to install

To have one Python project's environment run the service, install the host
[as a project dependency](docs/installation.md#install-as-a-project-dependency). Unlike a
client, this adds the GPU packages to the project.

Without a Python toolchain, use the
[prebuilt Windows, Linux, or Apple silicon macOS binaries](docs/installation.md#install-a-prebuilt-binary).

<p id="where-it-puts-things-and-how-to-remove-it"></p>

### Remove vaultspec-rag

Follow the [removal guide](docs/installation.md#remove-vaultspec-rag) to preview project changes,
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

By default, the service keeps its index in managed Qdrant, a separate process. The
optional local-only backend keeps the index in each repository's `.vault/` folder
instead. It still needs a GPU and the models. To use it, set
`VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local` in the environment that starts the
service, because the default resource profile refuses the local-only backend.

Switching backends doesn't migrate your existing index. Follow
[backend setup](docs/backends.md) to switch.

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
