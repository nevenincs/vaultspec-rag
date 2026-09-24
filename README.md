<img src="assets/logo.png" width="150" alt="vaultspec-rag logo">

# vaultspec-rag

Find code and the decisions behind it by meaning, on your own GPU, from a terminal or an
AI coding assistant.

vaultspec-rag indexes a repository's source code and decision records, then answers
plain-language queries with ranked file locations and passages. Indexing and search run
on your machine. Optionally,
[TypeSafe ranking](#sharpen-results-with-typesafe-ranking), a paid hosted relevance
service, can rerank and prune results. vaultspec-rag is in beta.

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
<img src="assets/term-search-code.svg" alt="Terminal output of vaultspec-rag search &quot;gpu section wrapping the reranker predict forward pass&quot; --type code --scores. Result 1 is src/vaultspec_rag/search/_searcher.py line 299, score 0.5119, followed by the matching docstring about reranking results with a CrossEncoder." width="880" />
</p>

## Why vaultspec-rag

Keyword search fails when you don't know the name a piece of code or a decision uses.
vaultspec-rag searches by meaning instead. It returns ranked file locations and passages
for you or an AI assistant to read. That makes it the retrieval half of
retrieval-augmented generation (RAG).

Source code shows where something happens. Decision records show why: architecture
decision records (ADRs), plans, research notes, and audits kept as Markdown in a
`.vault/` folder. vaultspec-rag's companion project,
[vaultspec-core](https://github.com/nevenincs/vaultspec-core), writes those records.
Repositories without any still get full code search.

By default, indexing and search run on your machine, so your code stays private and
queries cost nothing. The [glossary](docs/glossary.md) defines unfamiliar terms.

### What you get

- **Hybrid retrieval.** Each search combines meaning and exact keywords, then a
  reranking model reorders the top results.
- **Code, decisions, and documents.** Search source code, decision records, or documents
  such as PDFs, converted to text by converters a repository declares. Search one kind
  at a time or all together.
- **One service for every repository.** A single background search service serves all
  your repositories. It re-indexes changed files in the repositories you've searched
  recently.
- **Built for AI assistants.** Model Context Protocol (MCP) tools let coding assistants
  run searches themselves.
- **Production code first.** Code results favor production code. Tests, docs, locale
  files, and vendored code rank lower, and generated files and worktree copies are
  hidden. Filters in the query change these defaults.
- **Optional TypeSafe ranking.** A paid hosted service judges each result's relevance
  and removes the ones it's confident are irrelevant. It sends your queries and matching
  code to TypeSafe.

### How it works

Indexing splits each file into chunks and encodes every chunk twice: once with a meaning
model and once with a keyword model. Both vectors go into a [Qdrant](https://qdrant.tech/)
vector database. By default, Qdrant runs as its own process on your machine; this is
server mode. A search encodes the query the same two ways and fuses the two rankings.
A third model, the reranker, then reorders the top results.

The search service keeps its models loaded on the GPU, so searches return quickly.
vaultspec-rag has no CPU mode, because on a CPU the models are too slow to be useful.
The command line and the MCP adapter send requests to the service and load no models
themselves. See the [architecture overview](docs/architecture.md) for the full picture.

## Before you install

<p id="what-you-need"></p>

You need:

- **A supported GPU.** An NVIDIA GPU with CUDA on Linux or Windows, or Apple silicon on
  macOS. CPU inference and AMD GPUs aren't supported. On NVIDIA,
  [confirm the driver sees your card](docs/installation.md#confirm-your-gpu-is-visible).
- **Enough memory and disk.** The default resource profile needs 16 GiB of system RAM,
  8 GiB of free disk for the index, and, on NVIDIA, 12 GiB of free GPU memory. Allow
  about 4 GiB more disk for the models.
- **Linux: glibc 2.38 or newer.** The default Qdrant process needs it. Ubuntu 24.04 and
  Debian 13 qualify; check yours with `ldd --version`. On older distributions, use
  [local-only mode](#run-without-a-separate-qdrant-process) instead.
- **uv.** The [uv package manager](https://docs.astral.sh/uv/getting-started/installation/)
  fetches Python for you. The commands in this guide use Python 3.13; 3.14 also works.
  To skip Python entirely, use a [prebuilt binary](#other-ways-to-install).
- **A Hugging Face account.** The default keyword model,
  [`naver/splade-v3`](https://huggingface.co/naver/splade-v3), is gated: you must accept
  its access conditions before downloading it. Its CC-BY-NC-SA-4.0 license restricts
  commercial use.

A resource profile is the set of minimums the service checks before indexing. For a
machine with 8 GiB of RAM or unified memory, set the environment variable
`VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local` wherever you start the search
service. See the
[smaller profile's limits](docs/installation.md#what-you-need-before-you-start).

If the gate or the license doesn't suit you, skip the keyword (sparse) model. Set the
environment variable `VAULTSPEC_RAG_SPARSE_ENABLED=0` before Step 3, and keep it set
wherever you start the search service. This meaning-only setup gives up exact-keyword
matching; the [model download guide](docs/installation.md#the-model-cache-and-its-first-download)
covers it.

## Install

### Step 1: Install the tool

If vaultspec-rag is already installed, follow the
[upgrade guide](docs/installation.md#upgrade) instead.

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

To adapt a command:

- **Python 3.14:** change `--python 3.13` to `--python 3.14`, and replace both `cp313`
  tags in the wheel URL with `cp314`.
- **Linux ARM64:** replace `x86_64` in the wheel URL with `aarch64`.
- **Anything else:** [Pin the GPU build](docs/installation.md#pin-the-gpu-build) shows
  how to have vaultspec-rag print the exact command.

If uv reports that its executables directory is missing from `PATH`, follow its
instructions before continuing.

### Step 2: Grant access to the gated model

If you set `VAULTSPEC_RAG_SPARSE_ENABLED=0` for the meaning-only setup, skip this step.

Otherwise, sign in to Hugging Face and accept the access conditions on the
[`naver/splade-v3` model page](https://huggingface.co/naver/splade-v3). Then give the
system user that runs vaultspec-rag your Hugging Face token. Either set the `HF_TOKEN`
environment variable, or log in once with the Hugging Face command-line tool:

```bash
uvx --from huggingface_hub hf auth login
```

The token works only after its Hugging Face account accepts the conditions.

### Step 3: Set up each repository

Every repository follows the same routine: set it up once, start the service if it
isn't running, then index it. Run each command from the repository root. To preview the
setup changes first, add `--dry-run`.

```bash
vaultspec-rag install --no-torch-config
```

This adds agent rules and a search skill, which teach coding assistants when and how to
search. It also adds MCP adapter entries. If vaultspec-core already configured
assistants in the repository, the entries target those. Otherwise, they target Claude
Code and Codex. `--no-torch-config` leaves the PyTorch settings in the repository's
`pyproject.toml` alone, because Step 1 already installed the GPU build.

The first run also downloads the models and the Qdrant binary: about 4 GiB, which later
repositories reuse. The meaning-only setup downloads two models instead of three.
vaultspec-rag checks the Qdrant download against a SHA-256 checksum pinned in its code
before unpacking it. It re-checks the binary before every launch.

<p id="where-it-puts-things-and-how-to-remove-it"></p>
<p id="remove-rag"></p>

To undo these changes later, follow the [removal guide](docs/installation.md#remove-it).

Next, [start the service and index the repository](#use-it).

### Other ways to install

- [Prebuilt Windows, Linux, and Apple silicon binaries](docs/installation.md#install-without-python),
  with no Python toolchain.
- [Scoop or Homebrew](docs/installation.md#install-with-scoop-or-homebrew).
- [A dependency of your Python project](docs/installation.md#adding-it-to-a-project), to
  share one version with collaborators.
- [Client-only packages](#choose-a-package-by-role), for an extra Python environment on
  a machine that already runs the service.

### Choose a package by role

The install steps set up everything one machine needs. The client packages suit an
extra Python environment on a machine that already runs the search service. For
example, a lightweight project environment might need only the command line. Clients
reach the service over a local connection and load no models.

| Role                                 | Package                  | Needs a GPU? |
| ------------------------------------ | ------------------------ | ------------ |
| Command-line client                  | `vaultspec-rag`          | No           |
| MCP adapter for an existing service  | `vaultspec-rag[mcp]`     | No           |
| Search service host                  | `vaultspec-rag[gpu]`     | Yes          |
| Search service host with MCP adapter | `vaultspec-rag[gpu,mcp]` | Yes          |

In a client-only environment, run Step 3 as
`vaultspec-rag install --no-provision --no-torch-config`. That skips the model and
Qdrant downloads. Add `--no-mcp` for a command-line-only environment. See the
[installation lanes](docs/installation.md#choose-what-this-environment-runs) for each
role's commands and limits.

## Use it

For a guided walkthrough with checks at each step, follow the
[first-search tutorial](docs/getting-started.md). The following sections are the short
version.

<p id="start-and-search"></p>

### Start the service and check it

The `vaultspec-rag server` commands control the search service. Start it; the command
waits until the models are loaded:

```bash
vaultspec-rag server start
```

Check its health:

```bash
vaultspec-rag server doctor
```

<p align="center">
<img src="assets/term-doctor.svg" alt="vaultspec-rag server doctor output. Backend: server. Readiness: ready for requests. The live service is running and listening on port 8766. Installed dependencies are ready: CUDA available on an NVIDIA GPU, all 3 model repos present in the cache, and the Qdrant binary resolved." width="880" />
</p>

A healthy report shows the service running, your GPU detected, and the models ready:
three, or two in the meaning-only setup. In server mode, the default, it also shows
the Qdrant binary ready. If it reports a problem, follow the
[installation troubleshooting guide](docs/installation.md#when-something-goes-wrong).

<p id="check-on-the-index"></p>

### Index a repository

Indexing runs any converters the repository declares, with your permissions. Only index
a repository you'd trust to build, and read [converter security](#converter-security)
first.

From the repository root, submit the indexing jobs:

```bash
vaultspec-rag index
```

Indexing runs in the background. Follow the jobs until they finish:

```bash
vaultspec-rag server jobs --watch
```

The service then re-indexes changed files automatically while the repository is loaded.
A repository loads the first time you search or run `index` in it after the service
starts. It unloads after 30 minutes without use. If results look stale, run `index`
again; it processes only changed files.

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

Search decision records with `--type vault`. Add `--doc-type adr` to return only ADRs:

```bash
vaultspec-rag search "why the GPU lock covers only the forward pass" --type vault --doc-type adr
```

Add filter tokens to the query text to steer code results. This one hides tests:

```bash
vaultspec-rag search "retry backoff for failed uploads exclude:tests" --type code
```

If results are missing or weak, [diagnose missing results](docs/verification.md) and
[write a better query](docs/query-craft.md). The
[filter reference](docs/query-craft.md#the-filter-surface) covers the common filters,
and [commands and flags](docs/cli.md#search) lists every flag.

<p id="use-it-from-an-ai-assistant"></p>

### Connect an AI assistant

Step 3 registered the MCP adapter for your assistants. Restart each assistant to load
it, and keep the search service running while you work. For other assistants, follow
[MCP setup](docs/mcp.md). The assistant gets `search_codebase` and `search_vault`, among
other tools.

The default toolset also includes tools that change or delete indexes. To give an
assistant search only, see
[withholding the mutating tools](docs/mcp.md#withholding-the-mutating-tools).

### Stop the service

```bash
vaultspec-rag server stop
```

The service holds GPU memory while it runs. It doesn't start automatically at boot.
Your indexes persist, so next time, start the service again; you don't need a full
re-index. To pick up files changed while it was stopped, run `index` again.

<p id="scripting-it"></p>

### Script it

For JSON output and result handling, see [scripting and automation](docs/automation.md).

## Optional capabilities

<p id="optional-typesafe-classification"></p>

### Sharpen results with TypeSafe ranking

[TypeSafe AI](https://typesafe.ai) runs a paid hosted service that judges search
results. With a TypeSafe API key, vaultspec-rag uses it to rank and prune results by
relevance.

#### Data and cost

TypeSafe ranking sends your queries, the filters you set, and candidate results to
TypeSafe. Each candidate includes its file path and full content, including source code.
Each search also uses paid API credits. TypeSafe ranking adds to local search rather
than replacing it, so you still need the GPU and models.

#### What it adds

- **Reads intent.** It classifies what the query asks for, such as an implementation, a
  design decision, or a failure's cause, and uses that to guide ranking. Filters you set
  explicitly always take precedence.
- **Reviews a wider pool.** It considers more candidate results than the page shows, and
  reads each one's full content rather than a snippet.
- **Reorders and prunes.** It sorts candidates by judged usefulness and removes the ones
  it's confident are irrelevant, so a page can come back shorter, or empty.

If TypeSafe can't judge a search or can't be reached, search uses the normal local
ranking.

#### Turn it on

1. Create an API key in the [TypeSafe console](https://console.typesafe.ai/).

1. If the search service is running, stop it. Set the environment variable
   `VAULTSPEC_RAG_TYPESAFE_API_KEY` in the shell that starts the service, then start it.
   Keep the key out of committed files, including a project `.env` file.

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
   a recent search. After a minute without one, it reads
   `on (API key set; waiting for its first successful search)`. If it shows that right
   after a search, or reports the key rejected, see
   [TypeSafe enrollment](docs/configuration.md#typesafe-enrollment).

The enrollment guide explains fallback rules and every status.
[TypeSafe diagnostics](docs/configuration.md#typesafe-connection-reuse-caching-and-diagnostics)
explains per-search timings.

<p id="use-an-on-disk-index"></p>
<p id="run-without-the-search-server"></p>

### Run without a separate Qdrant process

Server mode, the default, runs Qdrant as its own process next to the search service.
Local-only mode suits small or offline repositories. It runs an embedded store inside
the search service instead, and keeps each repository's index on disk in that
repository. Both modes run entirely on your machine and need a GPU and the models.

Local-only mode also needs the smaller resource profile. Set the environment variable
`VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local` wherever you start the service.
Switching modes doesn't move existing indexes, so re-index each repository afterwards
or migrate it. Follow [backend setup](docs/backends.md).

<p id="read-pdfs-and-other-formats"></p>

### Index PDFs and other formats

Converters extract text from formats the indexer can't read, such as PDFs. A repository
declares them in a `.vaultragpreprocess.toml` file at its root. Without that file, no
converter runs. See [converter setup](docs/preprocessing-hooks.md).

<p id="what-a-converter-is-allowed-to-do"></p>

#### Converter security

When that file exists, its converters run by default, with no sandbox and with the
permissions of the system user running vaultspec-rag. They can read and write files and
reach the network. They run during explicit indexing, watched file changes, and
assistant-triggered re-indexing.

Before indexing a repository you didn't write, read its `.vaultragpreprocess.toml`.
`vaultspec-rag preprocess status` reports whether converters would run.
`vaultspec-rag preprocess list` shows each declared command. Neither runs a converter.
See [security and disable options](docs/preprocessing-hooks.md#security-posture).

## Documentation

- **Learn by doing:** [first-search tutorial](docs/getting-started.md) and
  [worked searches](docs/examples.md).
- **Get something done:** [installation, upgrade, and troubleshooting](docs/installation.md),
  [index maintenance](docs/search-and-index.md), [writing a better query](docs/query-craft.md),
  [diagnosing missing results](docs/verification.md), [MCP setup](docs/mcp.md),
  [scripting and automation](docs/automation.md), [backend setup](docs/backends.md), and
  [converter setup](docs/preprocessing-hooks.md).
- **Look something up:** [commands and flags](docs/cli.md),
  [configuration reference](docs/configuration.md),
  [TypeSafe enrollment](docs/configuration.md#typesafe-enrollment), and the
  [glossary](docs/glossary.md).
- **Understand it:** [architecture overview](docs/architecture.md) and
  [indexing internals](docs/indexing.md).
- **See what changed:** [release notes](CHANGELOG.md).

## Status and help

vaultspec-rag is in beta. Commands and configuration can change between releases, so
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
