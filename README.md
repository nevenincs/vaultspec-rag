<img src="assets/logo.png" width="150" alt="vaultspec-rag logo">

# vaultspec-rag

The semantic search component for vault and code.

Search code and feature records by meaning through the command line or Model Context
Protocol (MCP). Search inference runs on your GPU, with optional hosted Typesafe
query classification and result reranking.

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

For the Python installation below, use Python 3.13 or 3.14 and
[uv](https://docs.astral.sh/uv/getting-started/installation/).
Only the process that hosts the inference service needs model packages and an
accelerator. It requires NVIDIA CUDA on Linux or Windows, or Apple silicon on macOS;
CPU inference and AMD GPUs are unsupported. A command-line or MCP client that connects
to an already-running service on the same machine does not need CUDA.

Check the [memory and disk requirements](docs/installation.md#what-you-need-before-you-start)
before installing. That section also covers the smaller resource profile.

## Install

Choose extras for what you want this environment to run. There is no `rag` extra.

| Role                                     | Package                  | Loads models here? | Needs an accelerator? |
| ---------------------------------------- | ------------------------ | ------------------ | --------------------- |
| Command-line client and service controls | `vaultspec-rag`          | No                 | No                    |
| MCP stdio adapter to an existing service | `vaultspec-rag[mcp]`     | No                 | No                    |
| Inference-service host                   | `vaultspec-rag[gpu]`     | Yes                | Yes                   |
| Inference host with local MCP adapter    | `vaultspec-rag[gpu,mcp]` | Yes                | Yes                   |

The client and MCP adapter use the compatible vaultspec-rag HTTP service listening on
the configured loopback port. A remote Qdrant URL moves vector storage only; it is not
a remote inference service and does not remove the host's `gpu` requirement. See the
[installation lanes](docs/installation.md#choose-what-this-environment-runs) for setup
commands and the limits of each role.

Install a standalone tool for use across repositories. Choose the command for your
platform. The commands below install both the inference service and MCP adapter. These
CUDA commands use Python 3.13 and pin the GPU wheel so later tool upgrades retain it.

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

For other Python versions or Linux architectures, see [GPU wheel selection](docs/installation.md#pin-the-gpu-build).
If uv reports that its executables directory is missing from `PATH`, follow its
instructions before continuing. For an existing tool installation, follow the
[upgrade instructions](docs/installation.md#upgrade) before
replacing its environment.

Once installation succeeds, open the repository you want to search.

The default setup downloads
[`naver/splade-v3`](https://huggingface.co/naver/splade-v3), a gated sparse model.
Before running it, accept the model's access conditions and authenticate the service
account with `HF_TOKEN` or `hf auth login`; a token alone is insufficient until its
account has accepted the conditions. The model's CC-BY-NC-SA-4.0 license restricts
commercial use. If the gate or license is unsuitable, follow the
[dense-only setup](docs/installation.md#the-model-cache-and-its-first-download) instead.

```bash
vaultspec-rag install --no-torch-config
```

This installs the repository's agent integration, downloads the three search models,
and provisions Qdrant, the index server. The GPU packages are already installed, so
`--no-torch-config` leaves the project's PyTorch configuration alone. The first setup
downloads several gigabytes; subsequent projects share the models and server binary.

The default installer sets up the local models and Qdrant even with the lightweight
base or `[mcp]` package. Use `install --no-provision` to connect a client-only workspace
to an already-running service.

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

### Optional Typesafe classification

Set `VAULTSPEC_RAG_TYPESAFE_API_KEY` in the service account's environment before
starting the server to opt into paid Typesafe classification. A valid, funded key
enables query interpretation and reranking using the full result content, including
removal of confidently irrelevant hits. The server sends queries and candidate
content to Typesafe; without a usable key, search keeps its existing local ranking.

`server start` and `server status` show the running server's enrollment and whether
a recent evaluation succeeded. No separate enable flag is needed. See
[activation, fallback and status meanings](docs/configuration.md#typesafe-enrollment)
before enabling it. The local search models and GPU are still required.

### Start and search

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

To share a version with collaborators,
[add RAG as a project dependency](docs/installation.md#adding-it-to-a-project).

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
