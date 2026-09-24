<img src="assets/logo.png" width="150" alt="vaultspec-rag logo">

# vaultspec-rag

Find code and the decisions behind it by meaning, on your own GPU, from a terminal or an
AI coding assistant.

vaultspec-rag indexes a repository's source code and decision records, then answers
plain-language queries with ranked file locations and passages. Indexing and search run
on your machine. Optionally,
[TypeSafe ranking](#sharpen-results-with-typesafe-ranking), a paid hosted relevance
service, can re-rank and prune results. vaultspec-rag is in Beta.

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

[Why vaultspec-rag](#why-vaultspec-rag) · [Before you install](#before-you-install) ·
[Install](#install) · [Use it](#use-it) ·
[TypeSafe ranking](#sharpen-results-with-typesafe-ranking) ·
[Documentation](#documentation) · [Status and help](#status-and-help)

<p align="center">
<img src="assets/term-search-code.svg" alt="Example code search: a numbered result naming a source file and line number, followed by the matching passage" width="880" />
</p>

## Why vaultspec-rag

Keyword search fails when you don't know the name a piece of code or a decision uses.
vaultspec-rag searches by meaning instead. It returns ranked file locations and passages
for you or an AI assistant to read, making it the retrieval half of retrieval-augmented
generation (RAG).

Source code shows where something happens. Decision records show why: architecture decision records (ADRs), plans, research notes, and
audits kept as Markdown in a `.vault/` folder. Its companion project,
[vaultspec-core](https://github.com/nevenincs/vaultspec-core), writes those records.
Repositories without any still get full code search.

By default, indexing and search run on your machine, so your code stays private and
queries cost nothing. The [glossary](docs/glossary.md) defines unfamiliar terms.

### What you get

- **Hybrid retrieval.** Each search combines meaning and exact keywords, then a
  reranking model reorders the top results.
- **Code, decisions, and documents.** Search source code, decision records, or documents
  such as PDFs converted by extraction commands you configure, one at a time or all
  together.
- **One service for every repository.** A single background search service serves all
  your repositories and re-indexes files as they change in the ones you're using.
- **Built for AI assistants.** Model Context Protocol (MCP) tools let coding assistants
  run searches themselves.
- **Production code first.** Code results favor production code. Tests, docs, locale
  files, and vendored code rank lower, and generated files and worktree copies are
  hidden. Inline filters change that per query.
- **Optional TypeSafe ranking.** A hosted service judges each result's relevance and
  removes the ones it's confident are irrelevant.

### How it works

Indexing splits each file into chunks and encodes every chunk twice: once with a meaning
model and once with a keyword model. Both vectors go into a [Qdrant](https://qdrant.tech/)
vector database, which runs as its own process on your machine. A search encodes the
query the same two ways and fuses the two rankings. A third model, the reranker, then
reorders the top results.

The search service keeps its models loaded on the GPU, so searches return
quickly. That's also why there's no CPU mode: on a CPU, the models are too slow to be
useful. The command line and the MCP adapter are thin clients of the service. See the
[architecture overview](docs/architecture.md) for the full picture.

## Before you install

<p id="what-you-need"></p>

You need:

- **A supported GPU.** An NVIDIA GPU with CUDA on Linux or Windows, or Apple silicon on
  macOS. CPU inference and AMD GPUs aren't supported. On NVIDIA,
  [confirm the driver sees your card](docs/installation.md#confirm-your-gpu-is-visible).
- **Enough memory and disk.** The default resource profile needs 16 GiB of system RAM,
  8 GiB of free disk for the index, and, on NVIDIA, 12 GiB of free GPU memory. Allow
  several more gigabytes for the models. A
  [smaller resource profile](docs/installation.md#what-you-need-before-you-start) fits
  machines with 8 GiB of RAM or unified memory.
- **On Linux, glibc 2.38 or newer**, such as Ubuntu 24.04 or Debian 13, for the default
  Qdrant server. Check with `ldd --version`. On older distributions, use
  [local-only mode](#run-without-a-separate-qdrant-process) instead.
- **uv.** The [uv package manager](https://docs.astral.sh/uv/getting-started/installation/)
  fetches Python for you. The commands in this guide use Python 3.13; 3.14 also works.
  To skip Python entirely, use a [prebuilt binary](#other-ways-to-install).
- **A Hugging Face account.** The default keyword model,
  [`naver/splade-v3`](https://huggingface.co/naver/splade-v3), is gated: you must accept
  its access conditions before downloading it. Its CC-BY-NC-SA-4.0 license restricts
  commercial use.

If the gate or the license doesn't suit you, use the
[meaning-only setup](docs/installation.md#the-model-cache-and-its-first-download): set
`VAULTSPEC_RAG_SPARSE_ENABLED=0` before Step 3, and in every environment that starts
the search service. It skips the keyword model and gives up exact-keyword matching.

## Install

### Step 1: Install the tool

Run the command for your platform. Each one installs the search service and the MCP
adapter as a standalone tool for every repository. The CUDA commands pin the GPU build
of PyTorch, so later upgrades keep it.

Windows x64:

```powershell
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.14.0%2Bcu130-cp313-cp313-win_amd64.whl"
```

Linux x86_64:

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.14.0%2Bcu130-cp313-cp313-manylinux_2_28_x86_64.whl"
```

Apple silicon macOS:

```bash
uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]"
```

For Python 3.14, replace both `cp313` tags in the wheel URL with `cp314`. For Linux
ARM64, replace `x86_64` with `aarch64`. [Pin the GPU build](docs/installation.md#pin-the-gpu-build)
shows how to have vaultspec-rag print the exact command. If uv reports that its
executables directory is missing from `PATH`, follow its instructions before
continuing. To upgrade an existing installation, follow the
[upgrade guide](docs/installation.md#upgrade) instead.

### Step 2: Grant access to the gated model

If you set `VAULTSPEC_RAG_SPARSE_ENABLED=0` for the meaning-only setup, skip this step.

Otherwise, sign in to Hugging Face and accept the access conditions on the
[`naver/splade-v3` model page](https://huggingface.co/naver/splade-v3). Then
authenticate the account that runs vaultspec-rag: set `HF_TOKEN` in its environment,
or log in once with the Hugging Face CLI (`uvx --from huggingface_hub hf auth login`). A token alone isn't enough
until its account accepts the conditions.

### Step 3: Set up each repository

Every repository follows the same routine: set it up once,
[start the service](#start-the-service-and-check-it) if it isn't running, then index
it. Run each command from the repository root.

```bash
vaultspec-rag install --no-torch-config
```

This adds agent rules, a search skill, and MCP adapter entries to the repository. The
entries target Claude Code and Codex, or the assistants vaultspec-core already set up
there. `--no-torch-config` leaves the project's PyTorch settings alone,
because Step 1 already installed the GPU build. Add `--dry-run` to preview the changes.

The first time you run it, it also downloads the models (three by default, two in the
meaning-only setup) and the Qdrant binary. That's several gigabytes, so expect a long
first run; later repositories reuse both. vaultspec-rag checks the Qdrant download
against a SHA-256 digest pinned in its code before unpacking it, and re-checks the
binary before every launch.

<p id="where-it-puts-things-and-how-to-remove-it"></p>
<p id="remove-rag"></p>

To undo these changes later, follow the [removal guide](docs/installation.md#remove-it).

### Other ways to install

- [Prebuilt Windows, Linux, and Apple silicon binaries](docs/installation.md#install-without-python),
  with no Python toolchain.
- [Scoop or Homebrew](docs/installation.md#install-with-scoop-or-homebrew).
- [A project dependency](docs/installation.md#adding-it-to-a-project), to share one
  version with collaborators.
- [Client-only packages](#choose-a-package-by-role), for an extra environment on a machine
  that already runs the service.

### Choose a package by role

The install steps set up everything one machine needs. The client packages suit an
extra environment on a machine that already runs the search service, such as a
lightweight project environment that only needs the command line. Clients reach the
service over the machine's loopback interface and load no models.

| Role                                 | Package                  | Needs a GPU? |
| ------------------------------------ | ------------------------ | ------------ |
| Command-line client                  | `vaultspec-rag`          | No           |
| MCP adapter for an existing service  | `vaultspec-rag[mcp]`     | No           |
| Search service host                  | `vaultspec-rag[gpu]`     | Yes          |
| Search service host with MCP adapter | `vaultspec-rag[gpu,mcp]` | Yes          |

There is no `rag` extra. In a client-only environment, run Step 3 as
`vaultspec-rag install --no-provision --no-torch-config` to skip the model and Qdrant
downloads. Add `--no-mcp` for a command-line-only environment. See the
[installation lanes](docs/installation.md#choose-what-this-environment-runs) for each
role's commands and limits.

## Use it

For a guided walkthrough with checks at each step, follow the
[first-search tutorial](docs/getting-started.md). The following sections are the short
version.

<p id="start-and-search"></p>

### Start the service and check it

Start the search service. The command waits until the models are loaded:

```bash
vaultspec-rag server start
```

Check its health:

```bash
vaultspec-rag server doctor
```

<p align="center">
<img src="assets/term-doctor.svg" alt="vaultspec-rag server doctor output reporting the service running, CUDA available on the GPU, all three models present, and the Qdrant binary resolved" width="880" />
</p>

A healthy report shows the service running, detects your GPU, and reports the models
ready: three, or two in the meaning-only setup. In the default server mode, it also
reports the Qdrant binary ready. If it reports a problem, follow the
[installation troubleshooting guide](docs/installation.md#when-something-goes-wrong).

<p id="check-on-the-index"></p>

### Index a repository

Indexing runs any converter commands the repository declares, with your permissions.
Only index a repository you'd trust to build, and see
[converter security](#index-pdfs-and-other-formats) first.

From the repository root, submit the indexing jobs:

```bash
vaultspec-rag index
```

Indexing runs in the background. Follow the jobs until they finish:

```bash
vaultspec-rag server jobs --watch
```

After that, the service re-indexes changed files while the repository stays loaded:
from its first search or `index` after the service starts, until it sits idle for 30
minutes. If results look stale, run `index` again; it processes only changed files.

One service handles all your repositories, so run `index` once in each. To start over
or remove indexed content, see [rebuilding](docs/search-and-index.md#rebuild-from-scratch)
and [cleaning index data](docs/search-and-index.md#clean-index-data).

<p id="refine-searches"></p>
<p id="write-a-query-that-finds-it"></p>
<p id="narrow-the-results"></p>

### Search code and decision records

A search covers the repository you run it from. Search source code with `--type code`:

```bash
vaultspec-rag search "parse query text into filters" --type code
```

Each result names a file and line, followed by the matching passage.

Search decision records with `--type vault`. Add `--doc-type adr` to return only
architecture decisions:

```bash
vaultspec-rag search "why the GPU lock covers only the forward pass" --type vault --doc-type adr
```

Steer code results with filter tokens inside the query. This one hides tests:

```bash
vaultspec-rag search "retry backoff for failed uploads exclude:tests" --type code
```

If results are missing or weak, [diagnose missing results](docs/verification.md) and
[write a better query](docs/query-craft.md). The
[filter reference](docs/query-craft.md#the-filter-surface) covers the common filters,
and [commands and flags](docs/cli.md#search) lists every one.

<p id="use-it-from-an-ai-assistant"></p>

### Connect an AI assistant

Step 3 already registered the MCP adapter for Claude Code and Codex. Restart the
assistant to load it, and keep the search service running while you work. For other
assistants, follow [MCP setup](docs/mcp.md). The assistant gets `search_codebase` and
`search_vault`, among other tools.

The default toolset also includes tools that change or delete indexes. To give an
assistant search only, see
[withholding the mutating tools](docs/mcp.md#withholding-the-mutating-tools).

### Stop the service

```bash
vaultspec-rag server stop
```

The service holds GPU memory while it runs, and it doesn't start automatically at boot.
Your indexes persist, so next session start the service again without a full re-index.
To pick up files changed while it was stopped, run `index` again.

<p id="scripting-it"></p>

### Script it

For JSON output and result handling, see [scripting and automation](docs/automation.md).

## Optional capabilities

<p id="optional-typesafe-classification"></p>

### Sharpen results with TypeSafe ranking

[TypeSafe AI](https://typesafe.ai) runs a paid hosted service that judges search
results. With a TypeSafe API key, vaultspec-rag uses it to rank and filter results by
relevance:

- **Reads intent.** It classifies what the query asks for, such as an implementation, a
  design decision, or a failure's cause, and uses that to guide ranking. Filters you set
  explicitly always take precedence.
- **Reviews a wider pool.** It considers more candidate results than the page shows, and
  reads each one's full content rather than a snippet.
- **Re-orders and prunes.** It sorts candidates by judged usefulness and removes the ones
  it's confident are irrelevant, so a page can come back shorter, or empty.

If TypeSafe can't judge a search or can't be reached, search uses the normal local
ranking.

**Data and cost.** TypeSafe ranking sends your queries, any filters you set, and
candidate content with its file paths, including source code, to TypeSafe. It also uses
paid API credits. It adds to local search rather
than replacing it, so you still need the GPU and models.

To turn it on:

1. Create an API key in the [TypeSafe console](https://console.typesafe.ai/).

1. Set `VAULTSPEC_RAG_TYPESAFE_API_KEY` in the environment that starts the search
   service, then start the service from there. If it's already running, stop it first.
   Set the key in your shell or service environment, and keep it out of committed files,
   including a project `.env` file.

   ```bash
   export VAULTSPEC_RAG_TYPESAFE_API_KEY='<your-key>'
   vaultspec-rag server start
   ```

   In PowerShell:

   ```powershell
   $env:VAULTSPEC_RAG_TYPESAFE_API_KEY = '<your-key>'
   vaultspec-rag server start
   ```

1. Run a search, then run `vaultspec-rag server status` within a minute. Its
   `Typesafe:` line reads `on (recent searches were classified)` when TypeSafe answered
   a recent search. After a quiet minute, it reads
   `on (API key set; waiting for its first successful search)`.

See [TypeSafe enrollment](docs/configuration.md#typesafe-enrollment) for fallback rules
and every status, and
[TypeSafe diagnostics](docs/configuration.md#typesafe-connection-reuse-caching-and-diagnostics)
for per-search timings.

<p id="use-an-on-disk-index"></p>
<p id="run-without-the-search-server"></p>

### Run without a separate Qdrant process

By default, Qdrant runs as its own process next to the search service: this is server
mode. For a small or offline project, local-only mode runs an embedded store inside the
search service instead, and keeps each repository's index on disk in that repository.
Both run entirely on your machine, and both need a GPU and the models. Local-only mode
also needs the smaller resource profile: set
`VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local` in the service's environment.

Switching modes doesn't move existing indexes, so re-index each repository afterwards
or migrate it. Follow [backend setup](docs/backends.md).

<p id="read-pdfs-and-other-formats"></p>

### Index PDFs and other formats

Converters extract text from formats the indexer can't read, such as PDFs. A repository
declares them in a `.vaultragpreprocess.toml` file at its root. Without that file, no
converter runs. See [converter setup](docs/preprocessing-hooks.md).

<p id="what-a-converter-is-allowed-to-do"></p>

**Security.** When that file exists, its commands run by default, with no sandbox and
with the permissions of the account running vaultspec-rag. They can read and write
files and reach the network. They run during explicit indexing, watched file changes,
and assistant-triggered re-indexing.

Before indexing a repository you didn't write, read its `.vaultragpreprocess.toml`.
`vaultspec-rag preprocess status` reports whether converters would run, and
`vaultspec-rag preprocess list` shows each declared command. Neither runs a converter. See [security and disable options](docs/preprocessing-hooks.md#security-posture).

## Documentation

- **Learn by doing:** [First-search tutorial](docs/getting-started.md) ·
  [Worked searches](docs/examples.md)
- **Get something done:** [Installation, upgrade, and troubleshooting](docs/installation.md) ·
  [Index maintenance](docs/search-and-index.md) ·
  [Write a better query](docs/query-craft.md) ·
  [Diagnose missing results](docs/verification.md) · [MCP setup](docs/mcp.md) ·
  [Scripting and automation](docs/automation.md) · [Backend setup](docs/backends.md) ·
  [Converter setup](docs/preprocessing-hooks.md)
- **Look something up:** [Commands and flags](docs/cli.md) ·
  [Configuration reference](docs/configuration.md) ·
  [TypeSafe enrollment](docs/configuration.md#typesafe-enrollment) ·
  [Glossary](docs/glossary.md)
- **Understand it:** [Architecture overview](docs/architecture.md) ·
  [Indexing internals](docs/indexing.md)
- **See what changed:** [Release notes](CHANGELOG.md)

## Status and help

vaultspec-rag is in Beta: commands and configuration can change between releases, so
read the [release notes](CHANGELOG.md) before upgrading.

Ask questions and report bugs in
[GitHub issues](https://github.com/nevenincs/vaultspec-rag/issues), the only support
channel. Include your version, operating system, GPU, the command you ran, and its error
output. Redact credentials and private content before posting.

## Related projects

- [vaultspec-core](https://github.com/nevenincs/vaultspec-core): records decisions for
  coding agents and humans, in the `.vault/` format vaultspec-rag searches.
- [vaultspec-dashboard](https://github.com/nevenincs/vaultspec-dashboard): the
  human-facing visual workspace for a vaultspec project.

## License

vaultspec-rag is released under the [MIT License](./LICENSE). The default keyword
model, `naver/splade-v3`, carries its own non-commercial license.
