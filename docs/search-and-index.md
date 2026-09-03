# Search and index your project

vaultspec-rag searches vault records, source code, and explicitly routed extracted
documents by meaning. This guide covers running searches and keeping each independent
index current.

This guide assumes the workspace is installed and provisioned. If it isn't, see the [installation guide](installation.md) first. For how search and indexing fit together, see the [architecture overview](architecture.md). To run searches against a background daemon instead of in-process, see [service mode](service-mode.md).

## Run a search

Nothing is searchable until the index exists. If this is a new project, run
[Build and refresh the index](#build-and-refresh-the-index) first.

How you phrase a query matters more than any filter here: pair a short
description of the behavior with the concrete words the target would contain.
[Writing a query](query-craft.md) covers it properly.

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
remains an alias for `combined`. The command rejects unknown source types rather than falling
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
uv run vaultspec-rag search "why the service publishes a heartbeat" --type vault --scores --max-results 5
```

That run, cut to the first two of its five records:

```text
1. .vault/adr/2026-07-21-machine-discovery-recovery-adr.md (score 0.6004)
   adr | feature: machine-discovery-recovery | 2026-07-21
   ## Implementation

   **D1 — Machine-pointer mutation is owner-only.** The machine-lock domain owns publication
   and deletion primitives. A caller may mutate the pointer only while presenting the active
2. .vault/adr/2026-05-30-service-lifecycle-adr.md (score 0.2748)
   adr | feature: service-lifecycle | 2026-05-30
   ## Rationale

   A daemon-side atexit + SIGTERM handler is the smallest cut that
   turns "the log went quiet" into "the log explicitly says I died
   and how". The heartbeat exists for the unreachable case (
```

Two things to read there. The second line of each record is the document's own
type, feature, and date, so a vault result says what kind of decision it is
before you open it. And the passages are cut where the chunk ends rather than at
a sentence, which is what a chunk is: the unit the index stores and scores, not
a summary written for you. [Writing a query](query-craft.md) covers what the gap
between 0.6004 and 0.2748 tells you.

If nothing comes back, the index may be empty or still building. Build it first; see [Build and refresh the index](#build-and-refresh-the-index). With a running service, an index job may still be in flight, so wait for it to finish, then search again.

## Narrow code results by path

Use `--include-path` to keep only files matching a pattern, and `--exclude-path` to drop matching files. Both flags are repeatable and accept standard globs:

```
uv run vaultspec-rag search "lock ordering" --type code \
  --include-path "src/**" --exclude-path "**/tests/**"
```

A pattern with no glob character names a location, and matches that path and everything beneath it, so `--include-path src/vaultspec_rag/indexer` and `--include-path "src/vaultspec_rag/indexer/**"` select the same subtree. Repeating a pattern unions the selections.

The query string takes the same narrowing as a `path:` token. Reach for that form
when the search travels as one string, through an agent or the Model Context
Protocol (MCP) tools:

```
uv run vaultspec-rag search "reopen a drifted indexed path path:src/vaultspec_rag/indexer/" --type code
```

Patterns match indexed project-relative paths, not files on disk. When a pattern excludes every candidate the query matched, the empty result says so and names the pattern rather than reporting a plain no-match.

These flags apply to code only. Passing them with a vault search is a usage error.

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

Target one exact project-relative path with `--path`. Unlike `--include-path`, it matches that one file and nothing under it:

```
uv run vaultspec-rag search "lock" --type code --path src/vaultspec_rag/store_runtime.py
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

## Filter noise by domain

Each code chunk gets a *noise domain* from its path. This is the axis you use to
cut noise inside the code content domain. The [glossary](glossary.md) covers both
senses of the word: `--type` selects a content domain, while the tokens here
select noise domains.

| Noise domain | What it covers                                                          |
| ------------ | ----------------------------------------------------------------------- |
| `prod`       | Production source - what a search usually wants                         |
| `tests`      | Test files and directories, such as `tests/`, `*_test.*`, `conftest.py` |
| `docs`       | Documentation (`docs/`, `README*`, `*.md`/`*.rst`)                      |
| `locale`     | Localization tables, such as `locales/`, `i18n/`, `<lang>.yml`          |
| `generated`  | Machine-emitted files, such as `*_pb2.py`, `*.min.js`, `__generated__/` |
| `vendored`   | Third-party trees, such as `vendor/`, `dist/`, `node_modules/`          |
| `worktree`   | Agent worktree clones that duplicate the real source                    |

By default, the search keeps production first. It hides `generated` output and
`worktree` clones, demotes `tests`, `docs`, `locale`, and `vendored` below
production, and collapses locale duplicates. Worktree clones are also skipped at
index time.

When a query still returns noise, narrow by domain rather than raising
`--max-results` and reading past it.

Steer a single search with inline query tokens. They ride in the query string, so
they need no flags and pass through the running service unchanged. Values are
comma-separated and repeatable.

```
# Hide one noise domain for this search
uv run vaultspec-rag search "retry backoff policy exclude:tests" --type code

# Hide several at once (comma-separated, or repeat the token)
uv run vaultspec-rag search "payment capture flow exclude:tests,docs,vendored" --type code

# Restrict to one or more domains - for example, find only the tests for a behavior
uv run vaultspec-rag search "fixture setup helpers only:tests" --type code

# Re-admit a domain the profile hides or demotes by default
uv run vaultspec-rag search "translation table lookup include:locale" --type code
```

Domain tokens compose with the path and locale controls, so you can
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
per-project defaults, meaning which domains hide, which demote, and how hard, with the
`code_noise_hide_domains`, `code_noise_demote_domains`, and
`code_noise_demote_penalty` configuration settings (see the configuration guide).

## Every filter in one place

The [CLI reference](cli.md) lists every search flag with its type, default, and
which content domain it applies to. The sections here cover the ones you reach
for most.

## Use the service and MCP surfaces

The running service accepts the same fixed set of source names on `POST /search`,
`POST /reindex`, and `POST /clean`. Send `vault`, `code`, `document`, or `combined`.
Service requests don't accept the CLI aliases. `GET /readiness` reports per-domain
document counts and health without loading a model.

An assistant reaches the same operations through MCP.
Combined operations keep one outcome per content domain, including failures, so a
failure in one domain never erases a valid result from another. See
[MCP integration](mcp.md) for the tool list and
[service mode](service-mode.md) for operating the service.

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

Code admission is not a recursive "all readable files" scan. It follows the configured
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

The target is required, so `clean` removes a corpus only when you name it. `clean` doesn't load models or touch the GPU.

## Where to go next

- Run searches and indexing through a background daemon: [service mode](service-mode.md).
- Every command, flag, and exit code: [CLI reference](cli.md).
- Tune defaults like result counts, batch sizes, and the data directory: [configuration](configuration.md).

## Getting help

The [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues) takes questions as well as bug reports.
