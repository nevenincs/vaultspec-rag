# Get started with vaultspec-rag

Index your project, search its source code, and narrow the results to a file.

## Check your machine can run vaultspec-rag

Check the [hardware and Python requirements](installation.md#what-you-need-before-you-start)
and install [uv](https://docs.astral.sh/uv/). The steps below add RAG as a project
dependency; use a project whose source code you want to search.

## Step 1: Install vaultspec-rag and download the models

Open a terminal in the root of the project you want to search, then add and provision RAG:

```
uv add "vaultspec-rag[gpu]"
uv run vaultspec-rag install --sync
```

`install` asks once before it changes your PyTorch configuration. The prompt defaults to no, so type `y` to continue. On Linux and Windows this selects the CUDA build; on macOS the entry's platform marker leaves it inactive, because the standard wheel already supports Apple silicon.

This is the slowest part of the tutorial. Budget roughly 5 GB for the CUDA PyTorch stack and another 4 GB for the three search models.

Confirm it worked:

```
uv run vaultspec-rag --version
```

<!-- x-release-please-start-version -->

```
vaultspec-rag v0.4.24
```

<!-- x-release-please-end -->

If the version check fails, the [installation guide](installation.md) covers recovery for each step.

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

vaultspec-rag keeps your code and your `.vault/` records in separate *domains* and searches one at a time. `--type code` selects your source. Without the flag it searches `vault`, which is empty unless your project keeps decision records, so pass the flag here. The [search and index guide](search-and-index.md) covers every domain.

Write a query that pairs the concept with the concrete words the code itself contains, such as symbol and type names:

```
uv run vaultspec-rag search "parse the query text into filters" --type code
```

Each search returns up to 10 results, each with a rank, a file location, and the
matching lines. The capture below is that command run against this project's own
source, so yours will name your files instead. Each result's matching lines are
cut here to the first one; on your terminal they run to a dozen lines or more:

```text
1. src/vaultspec_rag/search/_parsing.py:51
   def parse_query(raw_query: str) -> ParsedQuery:
2. src/vaultspec_rag/search/_searcher.py:1129
           """Search documents from one already encoded query."""
3. src/vaultspec_rag/search/_parsing.py:1
   """Query parsing: extract metadata filter tokens from raw queries.
```

Ten came back; three are shown. The ranking is the point: the function that
does the thing you asked for is first, and one file can hold several of the
results because a result is a passage rather than a file.

## Step 4: Narrow the search to part of your project

Run the same query again with a path filter:

```
uv run vaultspec-rag search "parse the query text into filters" --type code --include-path 'src/vaultspec_rag/search/_parsing.py'
```

Only the filter changed, so any difference in what comes back is the filter's
doing. Cut to the first matching line again:

```text
1. src/vaultspec_rag/search/_parsing.py:51
   def parse_query(raw_query: str) -> ParsedQuery:
2. src/vaultspec_rag/search/_parsing.py:1
   """Query parsing: extract metadata filter tokens from raw queries.
3. src/vaultspec_rag/search/_parsing.py:31
   _FILTER_KEY_MAP = {
```

Ten results became three, every one of them inside the file you named, and the
same passage that was first before is first again. Point the filter at a path your own tree has; if
it does not exist, expect none, which is the filter working rather than the
search failing.

## When you are finished

Stop the service:

```
uv run vaultspec-rag server stop
```

Your index survives, and while the service runs it watches your files and re-indexes changes on its own. So your next session is shorter: start the service again, then go straight to searching. You won't reinstall, and you won't run `index` a second time.

## If a step didn't work

**`install` fails on the PyTorch step.** Usually a GPU the toolchain can't see. Run `uv run vaultspec-rag server doctor`, which reports what it detected, and check your machine against [the requirements](#check-your-machine-can-run-vaultspec-rag).

**Searching returns nothing.** Either the service is still loading or the first index hasn't finished. `uv run vaultspec-rag server status` reports the service state and exits 5 while the models are still loading. `uv run vaultspec-rag server jobs` shows whether indexing has finished.

**Results look thin or irrelevant.** Check that indexing finished, then re-read Step 3 on query wording. A query of only common words returns weak matches.

For anything else, the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues) takes questions as well as bug reports, so a setup problem on your own machine belongs there too.

## Where to go next

- [Search and index](search-and-index.md) answers how ranking works and what the full filter set can do.
- [Writing a query](query-craft.md) answers what to change when results look wrong.
- [Architecture](architecture.md) answers why the tool needs a GPU and how the service, the models, and the index fit together.
- [CLI reference](cli.md) catalogues every command, flag, and exit code.
