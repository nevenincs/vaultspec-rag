# Get started with vaultspec-rag

Index your project, search its source code, and narrow the results to a file.

## Step 1: Install vaultspec-rag and download the models

Open the [installation guide](installation.md) and choose "Adding it to a project."
Work from your project root. Complete the project setup to download the models,
then follow "Verify the install."

Once verification succeeds, return here for Step 2.

## Step 2: Start the service and index your project

From your project directory, start the service and submit indexing jobs:

```bash
uv run vaultspec-rag server start
uv run vaultspec-rag index
```

`server start` waits until the service is ready. `index` prints IDs
for the jobs it submits. Indexing continues after the command returns.

Open the live job view:

```bash
uv run vaultspec-rag server jobs --watch
```

Match the first eight characters of the returned job IDs and check the project
path. Wait until each submitted job shows `finished` before continuing. For jobs
no longer in view, [inspect a job by ID](service-mode.md#control-one-job).

If a submission fails or a job shows `failed` or `cancelled`, follow the
[verification guide](verification.md).

## Step 3: Run your first search

Choose a function you know exists in your indexed project. Replace the example
query with its name and a brief description of its behavior:

```bash
uv run vaultspec-rag search "parse_query convert query text into filters" --type code
```

The `--type code` option searches source files. Inspect the returned file paths
and matching passages to find your function. A file may have several matching
passages.

If no results appear, use the [verification guide](verification.md) and
[query guidance](query-craft.md) before continuing.

## Step 4: Narrow the search to part of your project

Reuse your query from Step 3, adding a filter for one file. Replace `src/search.py`
with a project-relative path from the results, keeping forward slashes and
omitting any `:LINE` suffix:

```bash
uv run vaultspec-rag search "parse_query convert query text into filters" --type code --path "src/search.py"
```

Check that every result belongs to the selected file. The `--path` option matches
an exact project-relative path.

See the [filter reference](query-craft.md#the-filter-surface) for other ways to
narrow a search.

## When you are finished

Stop the service when you no longer need it:

```bash
uv run vaultspec-rag server stop
```

Stopping the service leaves stored indexes in place. Next session,
[start the service again](#step-2-start-the-service-and-index-your-project).
For stale indexes or configuration changes, see [reindexing](verification.md#reindexing).

## If a step didn't work

- [Resolve installation failures](installation.md#when-something-goes-wrong).
- [Investigate missing or incomplete results](verification.md).
- [Improve poor matches](query-craft.md).

If you still need help, [report the problem](https://github.com/nevenincs/vaultspec-rag/issues).

## Where to go next

- [Search and index your project](search-and-index.md)
- [Understand the architecture](architecture.md)
- [Command-line reference](cli.md)
