<img src="assets/logo.png" width="150" alt="vaultspec-rag logo">

# vaultspec-rag

The semantic search component for vault and code.

[![build](https://img.shields.io/github/actions/workflow/status/nevenincs/vaultspec-rag/ci.yml?branch=main&style=flat&label=build&logo=githubactions&logoColor=white&labelColor=24292f&color=57606a)](https://github.com/nevenincs/vaultspec-rag/actions/workflows/ci.yml)
[![release](https://img.shields.io/pypi/v/vaultspec-rag?style=flat&label=release&logo=pypi&logoColor=white&labelColor=24292f&color=57606a)](https://pypi.org/project/vaultspec-rag/)
[![runtime](https://img.shields.io/badge/runtime-Python%203.13%20%7C%203.14%20%7C%20CUDA%20%7C%20MPS-57606a?style=flat&logo=python&logoColor=white&labelColor=24292f)](#what-you-need)
[![license](https://img.shields.io/github/license/nevenincs/vaultspec-rag?style=flat&label=license&logo=opensourceinitiative&logoColor=white&labelColor=24292f&color=57606a)](./LICENSE)

[What it is](#what-it-is) · [Install](#install) · [Use it](#use-it) ·
[Docs](#documentation) · [Help](#status-and-help)

## What it is

You remember that your project handles file locking somehow. You don't remember what
anyone called it. `grep "lock"` gives you two hundred hits.

vaultspec-rag lets you describe it instead:

```bash
vaultspec-rag search "file lock concurrent write per-root" --type vault
```

```
1. .vault/audit/large-index-resilience-ledger-concurrency-audit.md
   audit | feature: large-index-resilience | 2026-08-13
   # `large-index-resilience` audit: `ledger concurrency`

   ## Scope

   Mandatory review of the durable-state concurrency work: write-ahead logging on
   the shared per-root ledger, integrity verification move
```

Every result gives you the file, what kind of record it is, and the passage that
matched.

It searches two things you already have: your source code, and your project's decision
records if you keep them with
[vaultspec-core](https://github.com/nevenincs/vaultspec-core). It reads other formats
too, like PDFs, once you [connect a converter](#read-pdfs-and-other-formats).

You don't need vaultspec-core. Point vaultspec-rag at any codebase and it works.

Keep using `grep` when you know the string - it's exact and instant. Use this when you
can't name the thing you're looking for.

## What you need

This runs machine-learning models on your own hardware, so the requirements are real:

- **Python:** 3.13 or 3.14.
- **A GPU:** on Linux and Windows, an NVIDIA card with CUDA and about 3 GB of free video
  memory. On macOS, Apple silicon, where 8 GiB of unified memory is the tested minimum.
- **16 GiB of system RAM.** Indexing refuses to start below this, it does not simply run
  slower.
- **Free disk:** 8 GiB for the default setup, 5 GiB if you
  [run without the search server](#run-without-the-search-server).

**CPU-only machines and AMD GPUs won't work.** There's no fallback. If that rules you
out, stop here.

## Install

```bash
uvx --from "vaultspec-rag[gpu]" vaultspec-rag install
```

This sets up the current folder, installs PyTorch for your platform, downloads the three
search models, and fetches the search-server binary. It asks once before changing any
config. Expect a few minutes and about 3.7 GB of downloads.

Check it worked:

```bash
vaultspec-rag server doctor
```

<p align="center">
<img src="assets/term-doctor.svg" alt="vaultspec-rag server doctor - service, GPU, model, and Qdrant readiness at a glance" width="880" />
</p>

You want to see your GPU detected, all three models present, and the server binary
provisioned. If something's missing, run `vaultspec-rag install --sync` to fix it, and
open an [issue](https://github.com/nevenincs/vaultspec-rag/issues) if that doesn't.

## Use it

Three commands.

**1. Start the service.** It loads the models and keeps them in memory, so later
searches are fast.

```bash
uv run vaultspec-rag server start
```

**2. Index your project.** Do this once.

```bash
uv run vaultspec-rag index
```

This takes minutes on a large project, and the progress bar can sit still while a batch
runs on the GPU - that's normal, it hasn't stopped responding. After this, the service
watches your files and re-indexes changes on its own.

**3. Search.** `search` looks in your decision records by default, so pass `--type code`
to search source:

```bash
uv run vaultspec-rag search "concept plus the domain terms" --type code
```

<p align="center">
<img src="assets/term-search-vault.svg" alt="vaultspec-rag search - a plain-English query surfacing the governing decision record from this repository's own vault" width="880" />
</p>

**Nothing came back?** Two likely reasons. The service may still be warming up - run
`vaultspec-rag server doctor`, and note that exit code 5 means "still loading, try
again". Or the first index may not have finished - `vaultspec-rag status` shows you. If
it's neither, please [open an issue](https://github.com/nevenincs/vaultspec-rag/issues).

You only start the service once per machine, and index once per project.

To wipe the index and start over: `vaultspec-rag clean all`.

### Other ways to install

As a project dependency, as a tool, or as a standalone binary.

**Add it to a project**, so your team gets the same version:

```bash
uv add "vaultspec-rag[gpu]"
uv run vaultspec-rag install --sync
```

On Linux and Windows, `--sync` installs the pinned CUDA build. On macOS you get the
standard wheel, which already supports Apple silicon.

**Install it as a standalone tool.** On Linux and Windows you have to pin the GPU build,
or `uv tool upgrade` will silently swap in a CPU one. Both `server start` and `install`
print the exact command for your machine when they spot this, and refuse to run it for
you - the installer lives inside the environment a replacement would have to remove.
Clear the environment first: stop the service, close every editor or agent session
holding the MCP server, and leave any shell whose working directory sits inside the tool
tree. A forced reinstall removes the old packages before writing the new ones, so
anything still holding the environment leaves it half-emptied
([the way back](docs/installation.md#a-tool-environment-is-missing-packages-after-a-failed-reinstall)).
It looks like this (Python 3.13, torch 2.13.0, Windows):

```bash
uv tool install --force --python 3.13 "vaultspec-rag[gpu,mcp]" --with "torch @ https://download.pytorch.org/whl/cu130/torch-2.13.0%2Bcu130-cp313-cp313-win_amd64.whl"
vaultspec-rag install
```

The `--python` version has to match the wheel's `cp3XX` tag. On Apple silicon, no pin is
needed:

```bash
uv tool install --python 3.13 "vaultspec-rag[mcp]"
vaultspec-rag install
```

**Install a standalone binary**, if the machine has no Python toolchain:

```powershell
scoop bucket add nevenincs https://github.com/nevenincs/homebrew-tap
scoop install vaultspec-rag
```

```bash
brew tap nevenincs/tap https://github.com/nevenincs/homebrew-tap
brew install vaultspec-rag
```

These already include the GPU build. The tap covers every vaultspec product, so you add
it once. Windows and Linux only - on Apple silicon, use one of the routes above. Linux
binaries need a recent glibc; see the [installation guide](docs/installation.md).

### Where it puts things, and how to remove it

By default the index lives in the shared service storage under `~/.vaultspec-rag/`, with
your project's data kept in its own namespace. Your project directory only holds run
metadata, in `.vault/data/search-data/`. The models and the server binary are also shared
across every project on the machine, in `~/.cache/huggingface/` and `~/.vaultspec-rag/`.
Expect the index itself to be substantial: this repository's namespace is about 1.3 GiB.

To remove it:

```bash
vaultspec-rag uninstall --force
```

Without `--force` it only shows you what it would delete. Adding `--remove-data` clears
`.vault/data/`, but your indexed content stays in the shared storage. To reclaim that
space, run `vaultspec-rag server storage survey` to find the namespace and
`vaultspec-rag server storage delete` to remove it. `server storage prune` clears every
namespace whose project directory is gone. See
[storage maintenance](docs/storage-maintenance.md).

## Write a query that finds it

This matters more than any flag. Describe the **behaviour**, and include the **words the
code or document would use**. Both halves do work: the description finds things
that mean the same, the specific words find exact matches.

One noun on its own gives the search almost nothing to go on:

```bash
vaultspec-rag search "locking" --type vault
```

```
1. .vault/adr/threading-lock-for-singleton-adr.md
2. .vault/audit/code-document-index-boundary-s18-document-store-audit.md
3. .vault/exec/service-hardware-singleton/...-service-lock-step.md
```

Describe what happens, and name the specifics:

```bash
vaultspec-rag search "file lock concurrent write per-root" --type vault
```

```
1. .vault/audit/large-index-resilience-ledger-concurrency-audit.md
2. .vault/research/service-concurrency-research.md
3. .vault/adr/store-eviction-log-rotation-adr.md
```

Same topic. The first scatters across unrelated features that merely mention locks. The
second returns three records about concurrent writes. More in [writing a query](docs/query-craft.md).

## Narrow the results

Try these in order.

1. **Search one thing at a time.** `--type code`, `--type vault`, or `--type document`.
   For decisions specifically, add `--doc-type adr`.

1. **Limit where it looks.** `--language python`, `--include-path "src/**"`,
   `--exclude-path "**/legacy/**"`. Use `--include-path` for a subtree or glob;
   `--path` matches one exact path.

1. **Hide the noise.** Code searches compete against tests, generated files, vendored
   dependencies, and worktree copies. Steer with inline words in the query itself:

   ```bash
   vaultspec-rag search "fixture setup helpers exclude:tests" --type code
   ```

   `exclude:` hides a group, `only:` keeps only what you name, `include:` brings back one
   that's hidden by default. The groups are `prod`, `tests`, `docs`, `locale`,
   `generated`, `vendored`, and `worktree`.

Asking for more results won't help. That gives you more of the same ranking, not a better
one - narrow the search instead.

<p align="center">
<img src="assets/term-search-code.svg" alt="vaultspec-rag code search - the reranker implementation surfaced from a plain-English description" width="880" />
</p>

## Check on the index

`vaultspec-rag status` tells you what's indexed, where it's stored, and which GPU it's
using. `vaultspec-rag server doctor` tells you whether the service, models, and search
server are ready.

To watch indexing as it happens, `vaultspec-rag server jobs --watch` opens a live view of
the running service. You get progress per job, what's waiting on the GPU, and the log for
whichever job you select.

<p align="center">
<img src="assets/term-jobs-watch.svg" alt="vaultspec-rag server jobs --watch - the live jobs interface showing an active vault index, two jobs waiting on the GPU slot, and the selected job's service log" width="880" />
</p>

If the index has fallen behind, run `vaultspec-rag index` again - it only picks up what
changed. See [verify the index](docs/verification.md).

## Use it from an AI assistant

Claude Code and other MCP clients can search your project directly. MCP is the Model
Context Protocol, a standard way to give AI tools access to things like this.

Start the service first, then add this to `.mcp.json` in your project:

```json
{
  "mcpServers": {
    "vaultspec-rag": {
      "command": "vaultspec-search-mcp",
      "env": { "VAULTSPEC_RAG_ROOT": "${workspaceFolder}" }
    }
  }
}
```

You need the `mcp` extra installed for this. It gives the assistant twelve tools: four
kinds of search, one to fetch a file, one to report index status, four to re-index, and
two to clear the index. Add `--read-only` to offer only the ones that read. See
[MCP integration](docs/mcp.md).

## Run without the search server

By default, vaultspec-rag runs a managed Qdrant server to hold the index. Pass
`--local-only` and it uses a plain on-disk store instead - nothing to download, nothing
to supervise.

```bash
vaultspec-rag install --local-only
```

You give up speed when several searches run at once, because the on-disk store handles
them one at a time. For one person searching now and then, you won't notice. It's a good
fit for continuous integration, air-gapped machines, and anywhere you can't run an extra
binary.

This changes **where the index is stored, and nothing else**. You still need the GPU and
the models. See [backends](docs/backends.md).

## Read PDFs and other formats

vaultspec-rag reads code and Markdown on its own. For anything else - PDFs,
spreadsheets - you connect a converter, and vaultspec-rag indexes what it produces. You
define them in a `.vaultragpreprocess.toml` file. The docs and the CLI call these
preprocessing hooks, which is why the command below is `preprocess`. See
[preprocessing hooks](docs/preprocessing-hooks.md).

Read the next part before you use someone else's.

### What a converter is allowed to do

**A converter runs whatever command it names, with your user account's permissions.
Nothing sandboxes it and nothing checks it against a list of approved commands.**

Indexing a repository therefore means trusting that repository, exactly as running its
`make` or `npm install` does.

It also runs more often than you might expect:

- when you run `vaultspec-rag index`
- whenever the service notices a matching file change - with no command from you
- on any re-index request, including from an AI assistant

The limits that exist stop a runaway converter, not a hostile one. It runs in a separate
process, under a time limit, with its output capped, and with your environment variables
stripped down so passwords and tokens in them don't reach it. That last one isn't a
security boundary. The converter runs as your account: it can read and write any file you
can, and reach the network exactly as you can.

Before you use a converter you didn't write:

- Read the `.vaultragpreprocess.toml` and every command it runs, the way you'd read a
  build script.
- Run `vaultspec-rag preprocess status` first. It tells you whether a project defines
  converters and whether they'd run - without running anything.
- **Don't index a repository you wouldn't build.**

To turn converters off completely, set `VAULTSPEC_RAG_PREPROCESS=off`. That overrides
everything else. `server start --no-preprocess` disables them for that service. Note that
`index --no-preprocess` only applies when indexing runs in-process: if a service is
already running, `index` hands the work to it and the flag has no effect.

## How it works

A background service holds the models and the index. One service per machine; the index
itself is per project.

Indexing reads your files once, then keeps up by watching for changes.

A search matches two ways at once - by meaning, and by exact words. A third, slower model
then re-scores the best few results to put the strongest first. That last step is where
most of a search's time goes, and the two-way matching is why
[how you word a query](#write-a-query-that-finds-it) changes so much.

Read the [architecture overview](docs/architecture.md) for the detail.

## Scripting it

Every command except `server warmup` takes `--json`. You get one JSON object on stdout,
and nothing else - logs go to stderr.

```json
{ "ok": true, "command": "search", "data": { "results": [] } }
```

When something fails you get `"ok": false` with `error` and `message`. Branch on the
`error` value, such as `port_unreachable`, `local_store_locked`, or `stopped`, rather
than on the message text.

| Exit code | Meaning                                    |
| --------- | ------------------------------------------ |
| 0         | Worked                                     |
| 1         | Failed - GPU error, busy index, no service |
| 2         | You passed a bad argument or flag          |
| 3         | Service isn't running                      |
| 4         | Service crashed, or its state disagrees    |
| 5         | Service is still loading - try again       |

See [automation](docs/automation.md).

## Documentation

**Start here**

- [Getting started](docs/getting-started.md) - install, index, and search, end to end.
- [Installation](docs/installation.md) - GPU-specific PyTorch details and how to recover
  a broken setup.

**Using it**

- [Search and index](docs/search-and-index.md) - running searches and refreshing the
  index.
- [Writing a query](docs/query-craft.md) - phrasing, every filter, and what to do when
  results look wrong.
- [Retrieval recipes](docs/examples.md) - worked examples, including questions it answers
  badly.
- [Verify the index](docs/verification.md) - check the service is healthy and the index
  covers what you meant.
- [Service mode](docs/service-mode.md) - keeping the models loaded in the background.
- [Backends](docs/backends.md) - managed server versus on-disk store.
- [MCP integration](docs/mcp.md) - connecting AI clients.
- [Automation](docs/automation.md) - JSON output and scripting.
- [Preprocessing hooks](docs/preprocessing-hooks.md) - connecting converters, and the
  trust model.

**Looking things up**

- [CLI reference](docs/cli.md) - every command, flag, and exit code.
- [Configuration](docs/configuration.md) - settings, environment variables, defaults.
- [Service discovery](docs/service-discovery.md) - the `service.json` contract.
- [Glossary](docs/glossary.md) - every term used across these docs.

**How it works**

- [Architecture](docs/architecture.md) - the design, and why a GPU is required.
- [Indexing](docs/indexing.md) - indexing and retrieval internals.

## Status and help

vaultspec-rag is Beta. Report bugs and ask questions on the
[issue tracker](https://github.com/nevenincs/vaultspec-rag/issues).

Please include five things: your vaultspec-rag version, your operating system, your GPU,
the command you ran, and the full error output. With those, someone can reproduce the
problem. Without them, it's guesswork.

## Related projects

| Project                                                       | Maturity | Role                                                   |
| ------------------------------------------------------------- | -------- | ------------------------------------------------------ |
| [vaultspec-core](https://github.com/nevenincs/vaultspec-core) | Beta     | Decision-driven harness for coding agents, and humans. |
| **vaultspec-rag**                                             | Beta     | The semantic search component for vault and code.      |

[vaultspec-dashboard](https://github.com/nevenincs/vaultspec-dashboard) is a separate
project building a dedicated frontend on the same files. It is in early development, in
the open.

## For contributors

The [changelog](CHANGELOG.md) has release notes and version history. vaultspec-rag is
released under the [MIT License](./LICENSE).
