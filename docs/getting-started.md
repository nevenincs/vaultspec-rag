# Your first search

Keyword tools like grep find files that use the same words as your query. They miss files that mean the same thing in different words. vaultspec-rag closes that gap for your own project by searching on meaning, not just spelling.

By the end of this tutorial you will have installed vaultspec-rag, pointed it at a project, run a search written in plain English, and read the ranked results. To follow along you need a working command line and a project directory that contains some source code. Model downloads and the first index build take longer than later runs and depend on your network and project size, so plan for an unhurried first pass.

## Before you start

- An NVIDIA GPU with CUDA support and roughly 3 GB of free GPU memory.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed and on your `PATH`.
- Python 3.13 or newer.

For full environment setup, see [installation](installation.md). For why the GPU is required, see [architecture](architecture.md).

## Step 1: install vaultspec-rag

Add the package to a uv-managed project:

```bash
uv add vaultspec-rag
```

uv downloads vaultspec-rag and its dependencies. Wait for the prompt to return before continuing.

Verify the install:

```bash
uv run vaultspec-rag --version
```

You should see:

```text
vaultspec-rag v0.2.9
```

## Step 2: configure the GPU build

vaultspec-rag ships a one-shot command that patches your `pyproject.toml` to pull the correct CUDA-enabled `torch` wheel:

```bash
uv run vaultspec-rag install
```

The command asks for confirmation before editing `pyproject.toml`. Press `y` to accept. When it finishes, expect a final summary line that includes `torch_config_action=applied` to confirm the patch landed. If you see an error instead, see [installation](installation.md) for recovery steps.

## Step 3: move into your project

Change into the directory you want to search. Any directory you would open in your editor counts as a project; vaultspec-rag treats every `.md` file as a document and walks the source tree for code files.

```bash
cd path/to/your/project
```

## Step 4: build the search index

Build the index for both documents and code:

```bash
uv run vaultspec-rag index
```

On the first run, vaultspec-rag downloads the GPU model files into your HuggingFace cache. This happens once; later runs reuse the cached files. The indexer prints per-file progress as it works and finishes with a per-source summary that lists vault and code counts. The exact format may differ between versions, but the summary will appear once indexing is complete.

## Step 5: run your first search

Ask a question about your code in plain English:

```bash
uv run vaultspec-rag search "how authentication works" --type code
```

You will see a ranked table:

```text
  Score   Location                          Snippet
  0.87    src/auth/middleware.py:42         def authenticate(request): ...
  0.81    src/auth/session.py:118           class SessionManager: ...
  0.74    src/api/login.py:27               @router.post("/login") ...
```

`Score` shows how closely each chunk matches your query in meaning, with higher being closer. `Location` names the file and the starting line of the matching chunk. `Snippet` shows the first line of the matching code. By default the command returns the top 10 results.

## Step 6: narrow the results to one area

Scope the same query to a single subdirectory using `--include-path`:

```bash
uv run vaultspec-rag search "how authentication works" --type code --include-path 'src/auth/**'
```

`--include-path` is a glob filter applied after the search runs: only results whose path matches the pattern survive. Compare the output to Step 5 and you will see the result list shrink to files under `src/auth/`. For the full set of refinement flags, see [search and index](search-and-index.md).

## Wrap up

You now have a working install, a code search, and a narrowed search. From here:

- [Search and index](search-and-index.md) covers vault search and the other refinement flags you skipped here.
- [Service mode](service-mode.md) keeps the GPU model resident so repeat searches return faster.
- [MCP](mcp.md) wires vaultspec-rag into Claude Desktop and Claude Code.
- [Architecture](architecture.md) explains how the search actually works under the hood.

If anything went wrong, see the [Support section of the project README](../README.md#support-and-help).
