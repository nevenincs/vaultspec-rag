# Search and index your project

vaultspec-rag searches vault records, source code, and explicitly routed extracted
documents by meaning. This guide covers running searches and keeping each independent
index current.

This guide assumes the workspace is installed and provisioned. If it isn't, see the [installation guide](installation.md) first. For how search and indexing fit together, see the [architecture overview](architecture.md). To run searches against a background daemon instead of in-process, see [service mode](service-mode.md).

## Run a search

Search defaults to your vault documents:

```
uv run vaultspec-rag search "how does the watcher debounce changes"
```

To search source code instead, add `--type code`:

```
uv run vaultspec-rag search "gpu lock around the forward pass" --type code
```

Search extracted documents independently with `--type document`, or allocate candidates
across all three domains with `--type combined`:

```
uv run vaultspec-rag search "quarterly retention assumptions" --type document
uv run vaultspec-rag search "where is this policy implemented" --type combined
```

`docs` remains an alias for `vault`, `codebase` remains an alias for `code`, and `all`
remains an alias for `combined`. Unknown source types are rejected rather than falling
back to another corpus. A combined response preserves an outcome for every domain. If
only some domains fail, successful results return with `partial=true`; if all three fail,
the command reports a failure instead of an empty success.

Each result is a record with a rank, a file location, and the matching text.

Search returns 10 results by default. Change the count with `--max-results` (or its alias `--limit`):

```
uv run vaultspec-rag search "rerank inputs" --max-results 25
```

To see numeric relevance scores beside each record, add `--scores`:

```
uv run vaultspec-rag search "rerank inputs" --scores
```

If nothing comes back, the index may be empty or still building. Build it first; see [Build and refresh the index](#build-and-refresh-the-index). With a running service, an index job may still be in flight, so wait for it to finish, then search again.

## Narrow code results by path

Use `--include-path` to keep only files matching a glob, and `--exclude-path` to drop matching files. Both flags are repeatable and accept standard globs:

```
uv run vaultspec-rag search "lock ordering" --type code \
  --include-path "src/**" --exclude-path "**/tests/**"
```

These two flags apply to code only. Passing them with a vault search is a usage error.

## Narrow by language, structure, or symbol

For code searches, filter by language, parse-tree node type, or symbol name.

Filter by language:

```
uv run vaultspec-rag search "store lifecycle" --type code --language python
```

Filter by parse-tree node type with `--structure`:

```
uv run vaultspec-rag search "encode" --type code --structure function_definition
```

Filter by function or class name:

```
uv run vaultspec-rag search "encode" --type code --function-name encode_query
uv run vaultspec-rag search "store" --type code --class-name VaultStore
```

Target one exact project-relative path with `--path`:

```
uv run vaultspec-rag search "lock" --type code --path src/vaultspec_rag/store.py
```

## Narrow vault results

For vault searches, filter by document type, feature, date, or tag.

```
uv run vaultspec-rag search "concurrency" --doc-type adr
uv run vaultspec-rag search "concurrency" --feature server-supervision
uv run vaultspec-rag search "concurrency" --date 2026-06-12
uv run vaultspec-rag search "concurrency" --tag adr
```

Pass `--date` as `yyyy-mm-dd`, and pass `--tag` without the leading `#`.

## Filter code noise by category

Every code chunk is assigned a noise *category* from its path. This is the axis
you use to cut noise within the code domain:

| Category    | What it covers                                                        |
| ----------- | --------------------------------------------------------------------- |
| `prod`      | Production source - what a search usually wants                       |
| `tests`     | Test files and directories (`tests/`, `*_test.*`, `conftest.py`, ...) |
| `docs`      | Documentation (`docs/`, `README*`, `*.md`/`*.rst`)                    |
| `locale`    | Localisation tables (`locales/`, `i18n/`, `<lang>.yml`, ...)          |
| `generated` | Machine-emitted files (`*_pb2.py`, `*.min.js`, `__generated__/`, ...) |
| `vendored`  | Third-party trees (`vendor/`, `dist/`, `node_modules/`, ...)          |
| `worktree`  | Agent worktree clones that duplicate the real source                  |

By default the search keeps production first: it hides the duplicate and
derivative trees (`generated` output and `worktree` clones - clones are also
skipped at index time), demotes `tests`, `docs`, `locale`, and `vendored` so
they sit below production rather than crowding it, and collapses locale
duplicates. When a query still returns noise, narrow by category rather than
raising `--max-results` and reading past the noise.

Steer a single search with inline query tokens. They ride in the query string,
so they need no flags and pass through the running service unchanged; values are
comma-separated and repeatable.

```
# Hide one noise category for this search
uv run vaultspec-rag search "retry backoff policy exclude:tests" --type code

# Hide several at once (comma-separated, or repeat the token)
uv run vaultspec-rag search "payment capture flow exclude:tests,docs,vendored" --type code

# Restrict to one or more categories - e.g. find only the tests for a behaviour
uv run vaultspec-rag search "fixture setup helpers only:tests" --type code

# Re-admit a category the profile hides or demotes by default
uv run vaultspec-rag search "translation table lookup include:locale" --type code
```

Category tokens compose with the path and locale controls, so you can
scope precisely:

```
# Production code under one subtree, with the legacy tree removed
uv run vaultspec-rag search "auth handler exclude:tests" --type code \
  --include-path "src/**" --exclude-path "**/legacy/**"

# Bias toward tests while still showing production below them
uv run vaultspec-rag search "encode batch" --type code --prefer tests

# Keep every locale variant for a translation audit
uv run vaultspec-rag search "greeting string include:locale" --type code --no-dedup-locales
```

The `search_codebase` MCP tool exposes the same control as typed
`exclude_domains` / `only_domains` / `include_domains` parameters. Set the
per-project defaults - which categories hide, which demote, and how hard - with the
`code_noise_hide_domains`, `code_noise_demote_domains`, and
`code_noise_demote_penalty` configuration knobs (see the configuration guide).

## Collapse locale duplicates

Locale-variant collapse is on by default. Turn it off for a search with
`--no-dedup-locales`, or force it on with `--dedup-locales`:

```
uv run vaultspec-rag search "greeting" --type code --no-dedup-locales
```

## Prefer production, tests, or documentation

To bias a code search toward one kind of file, use `--prefer` with `production`, `tests`, or `documentation`:

```
uv run vaultspec-rag search "encode batch" --type code --prefer production
```

## Filter flag summary

| Flag                                        | Applies to | What it does                                               |
| ------------------------------------------- | ---------- | ---------------------------------------------------------- |
| `--type vault\|code\|document\|combined`    | all        | Chooses one domain or all three; defaults to vault         |
| `--max-results` / `--limit`                 | all        | Sets how many results return; defaults to 10               |
| `--scores`                                  | all        | Shows numeric relevance scores beside each record          |
| `--include-path`                            | code       | Keeps only files matching a glob; repeatable               |
| `--exclude-path`                            | code       | Drops files matching a glob; repeatable                    |
| `--language`                                | code       | Keeps results in one programming language                  |
| `--structure`                               | code       | Keeps results matching one parse-tree node type            |
| `--function-name`                           | code       | Keeps results in a function of this name                   |
| `--class-name`                              | code       | Keeps results in a class of this name                      |
| `--path`                                    | code       | Keeps results from one exact project-relative path         |
| `--dedup-locales` / `--no-dedup-locales`    | code       | Forces locale-duplicate collapse on or off (on by default) |
| `--prefer production\|tests\|documentation` | code       | Biases results toward one kind of file                     |
| `exclude:<domains>` (query token)           | code       | Hides one or more noise domains for this search            |
| `only:<domains>` (query token)              | code       | Restricts results to the named domains                     |
| `include:<domains>` (query token)           | code       | Re-admits a domain the profile hides or demotes by default |
| `--doc-type`                                | vault      | Keeps documents of one type                                |
| `--feature`                                 | vault      | Keeps documents tagged with one feature                    |
| `--date`                                    | vault      | Keeps documents from one `yyyy-mm-dd` date                 |
| `--tag`                                     | vault      | Keeps documents carrying one tag (no leading `#`)          |
| `--preprocessor-id`                         | document   | Keeps output from one extractor identity                   |
| `--extractor-version`                       | document   | Keeps output from one extractor version                    |

## Use the service and MCP surfaces

The resident service owns the same closed source vocabulary on `POST /search`,
`POST /reindex`, and `POST /clean`. Send `vault`, `code`, `document`, or `combined` as
the source; service requests do not accept aliases. `GET /readiness` and the service
status surface report independent document counts, policy fingerprints, generation
state, support profiles, and degraded reasons without loading a model on the reporting
path.

MCP exposes `search_documents`, `search_combined`, `reindex_documents`, `reindex_all`,
`clean_documents`, `clean_all`, and `get_index_status` alongside the existing vault and
code tools. Combined operations retain one outcome per domain, including failures. A
domain admission failure therefore does not erase a valid job or result from another
domain, while a complete failure remains a visible error.

## Build and refresh the index

Indexing keeps search results current with your files. By default, `index` uses the
compatibility `combined` target and runs incrementally, processing only changed work in
each domain:

```
uv run vaultspec-rag index
```

If a service is running, the command hands the job to it. The work runs in the background; check progress with:

```
uv run vaultspec-rag server jobs
```

If no service is running, the command indexes in the current process and returns when it's done.

To scope the run, name `vault`, `code`, `document`, or `combined`:

```
uv run vaultspec-rag index --type code
uv run vaultspec-rag index --type document
```

Code admission is not a recursive “all readable files” scan. It follows the configured
source profile and explicit project routing. Configure non-source extraction and its
owner in [preprocessing hooks](preprocessing-hooks.md).

## Rebuild from scratch

Use `--rebuild` with an explicit `--type` to drop one index and recreate it (for example, after changing the embedding model or recovering from a corrupted index):

```
uv run vaultspec-rag index --rebuild --type vault
uv run vaultspec-rag index --rebuild --type code
uv run vaultspec-rag index --rebuild --type document
```

`--rebuild` requires an explicit `--type`. A bare `index --rebuild` errors out, so it can't rebuild everything by accident.

## Clean index data

To delete index data without rebuilding it, use `clean` with a required target of
`vault`, `code`, `document`, or `combined`, and confirm with `--yes`:

```
uv run vaultspec-rag clean vault --yes
uv run vaultspec-rag clean document --yes
uv run vaultspec-rag clean combined --yes
```

The target is required, so no corpus is removed unless you name it. `clean` doesn't load models or touch the GPU.

## Where to go next

- Run searches and indexing through a background daemon: [service mode](service-mode.md).
- Every command, flag, and exit code: [CLI reference](cli.md).
- Tune defaults like result counts, batch sizes, and the data directory: [configuration](configuration.md).

For more help, see [support and help](../README.md#status-help-and-license).
