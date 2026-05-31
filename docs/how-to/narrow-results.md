# How to narrow vaultspec-rag results with path filters and category preferences

This guide shows you how to focus code search results when the default ranking returns more than you want to read. Four flags help: `--include-path`, `--exclude-path`, `--dedup-locales`, and `--prefer`.

All four apply to `vaultspec-rag search --type code` only. Passing them with `--type vault` exits with status 2.

## Keep only paths you care about

Use `--include-path` to drop any result whose project-relative POSIX path does not match at least one fnmatch pattern. The flag repeats, and matches are unioned.

```bash
vaultspec-rag search "token refresh" --type code \
  --include-path 'src/api/**' \
  --include-path 'src/auth/**'
```

Patterns are standard fnmatch globs, so `*` stops at a path separator and `**` crosses directories. The engine fetches extra candidates behind the scenes so that `--max-results` still produces a full page after filtering.

## Drop paths you never want to see

Use `--exclude-path` to remove results whose path matches any of the given patterns. The flag repeats, and exclusions win over inclusions when both are set.

```bash
vaultspec-rag search "rate limit" --type code \
  --exclude-path 'tests/**' \
  --exclude-path 'locales/*.yml'
```

A result that matches an include pattern and an exclude pattern is removed.

## Collapse locale variants

Translation files often produce near-duplicate hits for the same content in different languages. Pass `--dedup-locales` to collapse them.

The flag recognizes three path shapes:

- `<dir>/<lang>.<ext>`, such as `locales/en.yml` next to `locales/es.yml`
- `<dir>/<lang>/<name>.<ext>`, such as `i18n/en/messages.po`
- `<name>.<lang>.<ext>`, such as `messages.en.po`

Recognised extensions are `yml`, `yaml`, `json`, `po`, `properties`, `ini`, and `toml`.

When two results share the same logical content and their scores fall within 0.10 of each other, only the higher-scoring result survives. The collapsed paths are listed in the surviving snippet so you can still see which locales matched.

## Nudge production, tests, or docs

Use `--prefer` to apply a score adjustment of plus or minus 0.05 after reranking. Three values are accepted:

- `--prefer prod` raises production code and lowers tests and docs
- `--prefer tests` raises tests and lowers production code and docs
- `--prefer docs` raises docs and lowers production code and tests

The nudge is small on purpose: it reorders close ties without burying a strong match in the wrong category.

Classification works on path segments and basenames:

- Tests: any segment named `tests`, `test`, `spec`, or `__tests__`, plus basenames matching `test_*`, `*_test.*`, or `*_spec.*`
- Docs: any segment named `docs` or `doc`, plus basenames `readme*` or `changelog*`, plus extensions `md`, `rst`, and `adoc`
- Prod: everything else

Tests beats docs when both apply. A file at `tests/docs/fixtures.md` classifies as tests.

## Combine all four

The flags compose. Order does not matter.

```bash
vaultspec-rag search "rate limit" --type code \
  --include-path 'src/**' \
  --exclude-path 'src/legacy/**' \
  --prefer prod \
  --dedup-locales
```

This query keeps results under `src/`, drops anything in `src/legacy/`, removes near-duplicate locale files, and then nudges production code above tests and docs.

All four flags default off, so existing pipelines see no change until you opt in.

## Other filters

For language, AST node type, function name, class name, vault doc type, feature, date, and tag filters, see the [CLI reference](../reference/cli.md).
