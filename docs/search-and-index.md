# Searching and indexing

Indexing builds the search index over your project once. Searching queries that
index. Day to day, you re-index when files change and search whenever you have
a question. This page covers both, plus the flags that narrow what comes back.

Before you start, this page assumes you installed vaultspec-rag and ran
`vaultspec-rag install` successfully. See [installation](installation.md) for
setup and [architecture](architecture.md) for the conceptual model of what the
search index is.

## Build the index

```bash
uv run vaultspec-rag index
```

This reads `.md` files in your vault and source files in the project, splits
each into chunks, and stores them in a local search index. The first run does
the full pass. Subsequent runs are incremental: only changed files get
re-processed, so they finish faster than the first run.

## Re-index after big changes

To scope the index to one side, pass `--type`:

```bash
uv run vaultspec-rag index --type vault
```

```bash
uv run vaultspec-rag index --type code
```

Use `--type vault` after edits limited to `.vault/`, and `--type code` after
edits limited to source files. For most edits, plain `index` is enough.

After a big restructure (large rename, schema change, removed directories),
drop and rebuild a single collection from scratch:

```bash
uv run vaultspec-rag index --rebuild --type vault
```

## Run a search

Vault search is the default:

```bash
uv run vaultspec-rag search "how authentication works"
```

To query source code instead, pass `--type code`:

```bash
uv run vaultspec-rag search "how authentication works" --type code
```

The default returns the top 10 results in a Rich table with Score, Location,
and Snippet columns. Change the count with `--max-results`:

```bash
uv run vaultspec-rag search "how authentication works" --max-results 25
```

## Narrow by file path

Code search supports repeatable fnmatch globs. Use `--include-path` to keep
only matching results, and `--exclude-path` to drop matching results:

```bash
uv run vaultspec-rag search "token verify" --type code \
  --include-path "src/auth/*" --include-path "src/middleware/*"
```

```bash
uv run vaultspec-rag search "token verify" --type code \
  --exclude-path "*/tests/*" --exclude-path "*/__tests__/*"
```

Both flags apply to `--type code` only. Passing them with `--type vault`
produces a usage error.

## Narrow by language or vault metadata

Code search exposes these filters: `--language` (for example `python`),
`--node-type` (parse-tree node type, for example `function_definition`),
`--function-name`, `--class-name`, and `--path` (exact project-relative file
path). Vault search exposes `--doc-type` (for example `adr`), `--feature`
(kebab-case tag), `--date` (exact ISO date), and `--tag` (free-form tag).

Combine `--type code` with a language filter:

```bash
uv run vaultspec-rag search "retry policy" --type code --language python
```

Combine `--type vault` with a doc type filter:

```bash
uv run vaultspec-rag search "rollout plan" --type vault --doc-type adr
```

See [the CLI reference](cli.md) for the complete flag list.

## Collapse locale duplicates

When source results are dominated by translated strings, pass `--dedup-locales`
to collapse near-tie locale variants of the same content into one canonical
result. Two results within a score window of 0.10 whose paths look like
translations of the same file (for example `locales/en.yml`, `locales/es.yml`,
and `locales/ca.yml`) collapse to a single entry.

```bash
uv run vaultspec-rag search "welcome email subject" --type code --dedup-locales
```

The detector recognises path shapes like `locales/<lang>.<ext>`,
`i18n/<lang>/...`, `<lang>.json` siblings, and similar conventional layouts.

## Prefer production code over tests or docs

Pass `--prefer prod`, `--prefer tests`, or `--prefer docs` to apply a small
score nudge of +/- 0.05 to the matching category after re-ranking:

```bash
uv run vaultspec-rag search "session expiry" --type code --prefer prod
```

The classifier counts paths containing `tests`, `spec`, or `__tests__` as
tests, paths containing `docs`, `doc`, or files ending in `.md` or `.rst` as
docs, and everything else as prod.

## Filter flag summary

| Flag              | Applies to | What it does                                                       |
| ----------------- | ---------- | ------------------------------------------------------------------ |
| `--type`          | both       | Select source: `vault` or `code` (default `vault`).                |
| `--max-results`   | both       | Cap the number of returned results (default 10).                   |
| `--language`      | code       | Restrict to a programming language, for example `python`.          |
| `--path`          | code       | Restrict to an exact project-relative file path.                   |
| `--include-path`  | code       | Repeatable fnmatch glob; keep matching paths only.                 |
| `--exclude-path`  | code       | Repeatable fnmatch glob; drop matching paths.                      |
| `--node-type`     | code       | Restrict to a parse-tree node type.                                |
| `--function-name` | code       | Restrict to a function or method name.                             |
| `--class-name`    | code       | Restrict to a class or struct name.                                |
| `--dedup-locales` | code       | Collapse near-tie locale variants (score window 0.10).             |
| `--prefer`        | code       | Nudge `prod`, `tests`, or `docs` results by +/- 0.05 after rerank. |
| `--doc-type`      | vault      | Restrict to a vault doc type, for example `adr`.                   |
| `--feature`       | vault      | Restrict to a feature tag (kebab-case).                            |
| `--date`          | vault      | Restrict to an exact ISO date (`yyyy-mm-dd`).                      |
| `--tag`           | vault      | Restrict to a free-form tag, without the leading `#`.              |
| `--no-truncate`   | both       | Disable the 120-character snippet truncation in the results table. |

See [the CLI reference](cli.md) for full exit codes and the index flag list.

## Need help?

For questions or problems, see the
[Support](../README.md#support-and-help) section of the repo README.
