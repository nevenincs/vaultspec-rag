# Get started with vaultspec-rag

By the end of this tutorial you have vaultspec-rag installed, a search service running, your project indexed, and a first result on screen. Run the steps in order.

This needs an NVIDIA GPU with CUDA support and roughly 3 GB of free GPU memory. Without one, vaultspec-rag does not run, and you cannot complete the rest of this tutorial. You also need [uv](https://docs.astral.sh/uv/) and Python 3.13 or newer. The [requirements](../README.md#requirements) section lists the full set. For deeper detail, see the [installation guide](installation.md) and the [architecture overview](architecture.md).

## Step 1: Install and provision

Add the package, provision its dependencies, and fetch the GPU build:

```
uv add vaultspec-rag
uv run vaultspec-rag install
uv sync
```

`install` pauses once to confirm a config edit; type `y` to proceed. The first run downloads a few gigabytes of model files, so it is slow. The [installation guide](installation.md) covers the prompt, the `uv sync` step, and what to do if any of this fails.

Confirm the result:

```
uv run vaultspec-rag --version
```

```
vaultspec-rag v0.2.23
```

## Step 2: Start the service and index your project

Move into a project that contains source code, start the service, and index it:

```
cd path/to/your/project
uv run vaultspec-rag server start
uv run vaultspec-rag index
```

`server start` launches the search service and warms the models before it reports ready. `index` queues the work as a background job and returns immediately. Watch the job until it finishes:

```
uv run vaultspec-rag server jobs
```

```
Legend: * active, ~ waiting, ! failed, - finished

- 14:03:21 finished vault index update for my-project - added 24, updated 0, removed 0
- 14:03:27 finished code index update for my-project - added 120, updated 0, removed 0
```

A `-` prefix marks a finished run. Wait until both the vault run and the code run show `finished` before you search, or an early search returns incomplete results. A small project usually finishes within a minute.

## Step 3: Run your first search

Write a query as a short phrase. Combine the concept with the concrete terms the target code contains, such as symbol names, type names, and the domain vocabulary. Those exact terms feed the keyword half of the hybrid index and produce the strongest matches. A natural-language question starves that half and returns weaker results.

Search your code with a high-yield query:

```
uv run vaultspec-rag search "authentication middleware session token" --type code
```

The service returns up to ten ranked records, each with a rank, a file location, and the matching text:

```
1. src/auth/middleware.py:42
   def authenticate(request): ...
2. src/auth/session.py:118
   class SessionManager: ...
```

Now narrow the same query to one part of your tree with a path glob:

```
uv run vaultspec-rag search "authentication middleware session token" --type code --include-path 'src/auth/**'
```

The result list shrinks to the files under that path. After this first index, the service watches your files and reindexes changes on its own. The index stays current without running `index` again.

## Where to go next

You installed vaultspec-rag, started a search service, indexed a project, and ran your first searches. When you are done, stop the service:

```
uv run vaultspec-rag server stop
```

The [search and index guide](search-and-index.md) covers vault search, relevance scores, and the full filter set. The [documentation map](../README.md#documentation) lists every guide. If a step failed, report it on the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues).
