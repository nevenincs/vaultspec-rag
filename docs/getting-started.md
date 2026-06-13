# Get started with vaultspec-rag

By the end of this tutorial, you'll have vaultspec-rag installed, its dependencies provisioned, and a search service running. You'll index your project, get a first search result on screen, read it, and then narrow it down.

You'll need an NVIDIA GPU with CUDA and around 3 GB of free video memory, [uv](https://docs.astral.sh/uv/), and Python 3.13 or newer. The first run downloads the search model files once, so it takes longer than later runs. Follow the steps in order.

For the full setup reference, see the [installation guide](installation.md). For how the pieces fit together, see the [architecture overview](architecture.md).

## Step 1: Install the package

Add vaultspec-rag to your environment:

```
uv add vaultspec-rag
```

Confirm the install by printing the version:

```
uv run vaultspec-rag --version
```

You'll see:

```
vaultspec-rag v0.2.20
```

## Step 2: Provision dependencies

Provision the GPU build, the search models, and the managed vector-store binary:

```
uv run vaultspec-rag install
```

The command pauses at the PyTorch configuration prompt. Type `y` and press Enter. To skip the prompt, run `uv run vaultspec-rag install --yes` instead.

The command then prints a per-dependency report:

```
PyTorch: configured, sync pending
Models: downloaded
Qdrant binary: downloaded
```

PyTorch reads `configured, sync pending` because the GPU build is fetched in the next step.

## Step 3: Fetch the GPU build

Download the GPU PyTorch build that the previous step configured:

```
uv sync
```

uv resolves the dependency graph and installs the GPU build. You'll see uv list the packages it adds and updates.

## Step 4: Move into your project

Change into a project directory that contains source code:

```
cd path/to/your/project
```

## Step 5: Start the search service

Start the background search service:

```
uv run vaultspec-rag server start
```

The command starts the managed Qdrant server on the loopback address `127.0.0.1:8765` and warms the search models. It then binds the service on port 8766 and waits until the service reports ready. When it finishes, it prints the service address.

## Step 6: Build the index

Index your project through the running service:

```
uv run vaultspec-rag index
```

The service queues the work as a background job and prints:

```
Check progress with: vaultspec-rag server jobs
```

Watch the job until it completes:

```
uv run vaultspec-rag server jobs
```

Wait until both index runs show as `finished`, marked by the `-` legend prefix:

```
Jobs
Address: http://127.0.0.1:8766
Displayed: 2 of 2
Legend: * active, ~ waiting, ! failed, - finished

- 14:03:21 finished vault index update for my-project (job 9f2a1c7d) - added 24, updated 0, removed 0, finished in 3.1s
- 14:03:27 finished code index update for my-project (job a1b2c3d4) - added 120, updated 0, removed 0, finished in 6.4s
```

A small project usually finishes within a minute. Wait until both sources show `finished` before you search.

## Step 7: Run your first search

Search your code for a concept:

```
uv run vaultspec-rag search "how authentication works" --type code
```

The service returns up to ten ranked records. Each record shows a numbered rank, the file location, and the matching text:

```
1. src/auth/middleware.py:42
   def authenticate(request): ...
2. src/auth/session.py:118
   class SessionManager: ...
```

Relevance scores stay hidden by default. To see them, add `--scores`.

## Step 8: Narrow the results

Restrict the same search to one part of your tree with a path glob:

```
uv run vaultspec-rag search "how authentication works" --type code --include-path 'src/auth/**'
```

The result list shrinks to the files under that path:

```
1. src/auth/middleware.py:42
   def authenticate(request): ...
2. src/auth/session.py:118
   class SessionManager: ...
```

## Wrap up

You installed vaultspec-rag, provisioned its dependencies, started a search service, indexed a project, and ran your first searches - including a path-scoped one.

From here:

- Refine searches and search vault documents with the [search and index guide](search-and-index.md).
- Manage and observe the running service with the [service mode guide](service-mode.md).
- Compare the server-backed default with the local-only minimal setup in the [backends guide](backends.md).
- Wire vaultspec-rag into an AI assistant with the [MCP guide](mcp.md).
- Learn how the system works in the [architecture overview](architecture.md).

When you're done, stop the service:

```
uv run vaultspec-rag server stop
```

Need help? See [support and help](../README.md#support-and-help).
