# First search in five minutes

In this tutorial, you install vaultspec-rag, point it at a real project,
build a search index over its files, run a search, and read the results.
By the end you'll have a working install and a clear sense of what the
tool returns.

## Before you start

You need:

- A computer with an NVIDIA GPU. vaultspec-rag uses the GPU to compute
  search results; there's no CPU fallback. See
  [Why a GPU is required](../explanation/why-gpu.md) for the reasoning.
- About 3 GB of free GPU memory.
- [`uv`](https://docs.astral.sh/uv/) installed. If you don't have it,
  follow uv's install instructions for your platform.
- A project to search. Any folder with documents (`.md`) or source code
  files will do. If you don't have one in mind, clone a small open-source
  project to follow along.

You'll see commands in code blocks. Run them in a terminal in the order
they appear.

## Step 1: Install vaultspec-rag

Add the package to your environment:

```sh
uv add vaultspec-rag
```

uv downloads vaultspec-rag and its dependencies. This takes a minute or
two on a fresh machine because the embedding models are large.

Confirm the install worked:

```sh
uv run vaultspec-rag --version
```

You should see `vaultspec-rag 0.2.9` (or a newer version).

## Step 2: Configure the GPU build

vaultspec-rag uses a CUDA build of PyTorch. The install command patches
your `pyproject.toml` to use the right PyTorch wheel:

```sh
uv run vaultspec-rag install
```

The command asks for confirmation before editing `pyproject.toml`. Press
**y** to allow it.

When the install finishes, you'll see a "ready" message. If you see a
"no GPU" error instead, or if you'd rather configure PyTorch yourself,
see [Install and configure](../how-to/install-and-configure.md).

## Step 3: Move into a project

`cd` into the project you want to search:

```sh
cd path/to/your/project
```

vaultspec-rag works on the current directory. It treats any `.md` files
as documentation and walks the source tree for code files.

## Step 4: Build the search index

Run:

```sh
uv run vaultspec-rag index
```

The first run downloads three models from HuggingFace (about 1.9 GB
total). Subsequent runs reuse the cached models. The command prints
progress as it walks your files and builds the search index. On a 500-file
project, expect 30 to 90 seconds.

When indexing finishes, you'll see a summary like:

```
vault: 47 documents
code: 312 chunks
```

The counts depend on your project. If you don't have any `.md` files
the vault count will be 0; that's fine.

## Step 5: Run your first search

Ask a plain-English question about your project:

```sh
uv run vaultspec-rag search "how authentication works"
```

You'll see a table:

```
Score   Location                          Snippet
─────   ─────────────────────────────     ──────────────────────────────────
0.92    docs/auth.md                      Authentication uses signed tokens...
0.84    src/auth/middleware.py:42         def verify_token(token: str):...
0.78    docs/security.md                  All API requests require a valid...
```

The `Score` column ranks how relevant each result is (higher is more
relevant). `Location` points to the file (and line number for code).
`Snippet` shows the matching excerpt.

By default you get the top 10 results from your documentation. To
search source code instead, add `--type code`:

```sh
uv run vaultspec-rag search "how authentication works" --type code
```

## Step 6: Refine the results

The search you just ran looks across all of your documentation or all
of your code. If you want to narrow it, pass filters:

```sh
uv run vaultspec-rag search "retry" --type code --language python
```

That restricts results to Python files. Other useful filters:

- `--include-path 'src/api/**'` keeps only matches under `src/api/`.
- `--exclude-path 'tests/**'` drops test files.
- `--prefer prod` ranks production code above tests and docs.

See [Narrow results with path filters and category preferences](../how-to/narrow-results.md)
for the full list.

## You're done

You now have a working vaultspec-rag install and a search index over
your project. You ran a search and read the results. Everything from
here is variations on the same loop: index when files change, search
when you want to find something.

## What to read next

- [Run as a background service](../how-to/run-as-a-service.md) -
  Searches feel sluggish because the models reload every time. Run the
  service once and subsequent searches return instantly.
- [Use with Claude Desktop, Claude Code, and other MCP clients](../how-to/use-with-mcp-clients.md) -
  Wire vaultspec-rag into an AI assistant so it can search your project
  on your behalf.
- [How it works](../explanation/how-it-works.md) - If you want to
  understand what the tool is doing under the hood.
