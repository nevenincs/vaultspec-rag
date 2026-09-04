# Get started with vaultspec-rag

vaultspec-rag searches your source code by meaning rather than by keyword, so you can find something by describing it when you can't remember what it was called. It also searches the decision records your project keeps in `.vault/`, if it has them. The [project overview](../README.md) covers what it is and why it exists.

By the end of this tutorial you'll have vaultspec-rag installed, a search service running, your own project indexed, and search results on screen. Budget about 20 minutes, most of it waiting for downloads and the first index.

## Check your machine can run vaultspec-rag

The search models run on a GPU. Without a supported one you can't complete this tutorial, and the tool has no CPU fallback.

- **A GPU:** on Linux and Windows, an NVIDIA card with CUDA and roughly 3 GB of free video memory. On macOS, Apple silicon with at least 8 GiB of unified memory (the tested minimum), which on Apple silicon is the same pool as the system RAM below, so a machine at that minimum needs the `embedded-local` profile rather than the default. AMD cards aren't supported.
- **16 GiB of system RAM:** indexing refuses to start below this rather than running slowly. That's the floor for the default `managed-service` profile; the `embedded-local` profile lowers it to 8 GiB.
- **8 GiB of free disk:** on the volume holding the search index, and separately room in your Hugging Face cache for the models. The `embedded-local` profile lowers the index figure to 5 GiB.
- **CPython 3.13 or 3.14**, and [uv](https://docs.astral.sh/uv/).

The [installation guide](installation.md) carries the full compatibility detail and what to do when a step fails.

## Step 1: Install vaultspec-rag and download the models

Move into the project you want to search, then add and provision the package:

```
cd path/to/your/project
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
vaultspec-rag v0.4.22
```

<!-- x-release-please-end -->

If the version check fails, the [installation guide](installation.md) covers recovery for each step.

## Step 2: Start the service and index your project

Three pieces are now in play. The *service* is a background process that holds the models in memory so searches are fast. The *models* are the files you just downloaded. The *index* is the searchable copy of your project that the service builds and then maintains.

Start the service and index the project:

```
uv run vaultspec-rag server start
uv run vaultspec-rag index
```

`server start` loads the models before it reports ready, so the first start is slower than later ones. `index` hands the work to the service as a background job and returns immediately. The command finishing doesn't mean the indexing has.

Watch for it to finish:

```
uv run vaultspec-rag server jobs
```

```
Jobs
Address: http://127.0.0.1:8766
Displayed: 3 jobs
Total: 262 jobs
Displayed jobs: 0 active, 0 waiting, 3 finished, 0 failed
Showing: active, waiting, failed, then latest finished
Order: latest job appears last
Legend: * active, ~ waiting, ! failed, - finished
Scripting: use --json (this summary always contains the word 'active')
- 15:34:20 finished vault index update for main (job ad5e3dca) - added 26, updated 7, removed 0, finished in 7 seconds
- 15:34:41 finished code index update for main (job 5a318228) - added 120, updated 0, removed 0, finished in 34 seconds
- 15:34:52 finished document index update for main (job f7daa7b9) - added 0, updated 0, removed 0, finished in less than 1 second
```

`index` builds three indexes by default: `vault`, `code`, and `document`. Wait until all three show a line that reads `finished`. Read the word, not the `-` prefix alone: a job that was interrupted or cancelled also starts with `-`. Searching before all three finish returns whatever has been indexed so far, which looks like poor results rather than an error. A small project takes under a minute.

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
