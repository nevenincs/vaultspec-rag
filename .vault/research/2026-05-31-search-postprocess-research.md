---
tags:
  - '#research'
  - '#search-postprocess'
date: '2026-05-31'
modified: '2026-06-30'
related: []
---

# `search-postprocess` research: `locale dedup and chunk-type weighting design`

## Trigger

Two follow-up issues filed during the end-of-Wave-2 honest audit
as the remaining mitigations from the original #108 design list:

- **gh #121**: locale-aware dedup. Searching a polyglot
  codebase for a translated string returns four near-identical
  hits (`locales/{en,es,ca,hu}.yml`) with tied scores, consuming
  most of `--max-results`. `--exclude-path 'locales/*.yml'`
  works as a hammer; locale dedup is the scalpel.
- **gh #122**: chunk-type weighting. Tests and docstrings
  routinely outrank production code on concept queries (verified
  in the original #108 repro: test wins by 0.09 over the
  production verb). A small score nudge based on path-derived
  category (`prod` / `tests` / `docs`) lets users surface the
  category they actually want without filtering the others out.

Both run as post-rerank passes in `search.py:_search_codebase_encoded`,
share the same insertion point, and ship together because the
plumbing (CLI flags, MCP params, signature changes) overlaps
1:1.

## Method

Code-read against `main` after PR #133 (#124/#125 service_token).
Spot-checked the existing #114 post-query glob filter as the
template for the new post-rerank passes.

## Findings

### Existing post-process anchor

`_search_codebase_encoded` (`search.py:499`) already runs a
two-pass pipeline after `hybrid_search_codebase`:

1. Build `store_filters` from explicit kwargs + `parsed.filters`.
1. Apply Qdrant hybrid search with `fetch_limit` (10x top_k when
   path globs supplied, 4x otherwise).
1. **Post-query glob filter** (#114): walk raw_results, drop
   anything failing `include_paths` / `exclude_paths`. The
   surviving list is `raw_results`.
1. Build `SearchResult` instances from the filtered raw_results.
1. Apply `_rerank` (CrossEncoder) over the SearchResult list.

The new passes plug in **between steps 4 and 5** (locale dedup
must inspect SearchResult.path; chunk-type weighting must mutate
SearchResult.score before rerank or after, depending on design).

Decision: run BOTH new passes **after rerank**, on the
top-k-truncated list. Rerank already considers query relevance;
applying user preferences as a post-rerank nudge lets the
CrossEncoder do its job uninhibited, then re-orders. This
matches the existing `rerank_with_graph` pattern (which also
runs after `_rerank`).

### Locale dedup heuristic

A locale variant pair shares everything except a final-segment
language code. The detection rule:

- Both paths end in a known extension (`.yml`, `.yaml`,
  `.json`, `.po`, `.mo`, `.properties`, `.ini`, `.toml`).
- Strip the extension. The stem ends with one of: a directory
  named after a 2-letter ISO 639 code (e.g. `locales/en.yml`,
  `i18n/en/translation.yml`), or a basename matching `<name>. <lang>.{ext}` (e.g. `messages.en.po`).
- Scores within `LOCALE_DEDUP_SCORE_WINDOW` of each other
  (default 0.10 — tight enough that genuinely different content
  doesn't get collapsed).

When detected, keep the highest-scoring entry as the canonical
result; append `[locales: en, es, ca, hu]` to its snippet (or a
new `locale_variants` field) so the user knows the breadth.
Drop the others.

The classifier lives in a small module-level helper
`_locale_variant_key(path: str) -> str | None`. Returns the
shared stem when the path looks like a localised file, None
otherwise. Two results with the same key + tied scores collapse.

### Chunk-type weighting heuristic

A small lookup table maps path patterns to a category:

- `tests`: `**/test_*.py`, `**/*_test.py`, `**/tests/**`,
  `**/spec/**`, `**/__tests__/**` (Java-style).
- `docs`: `**/docs/**`, `**/doc/**`, `README*`, `**/*.md`,
  `**/*.rst`.
- `prod`: everything else (i.e. unrecognised → assumed
  production source).

`--prefer prod` (or `tests` or `docs`) applies a `+0.05` nudge
to results matching the preferred category and `-0.05` to
non-matching categories. Window is intentionally tight — about
the same magnitude as the score gap between adjacent results in
a typical search — so the preference re-orders top-k without
making irrelevant results jump rank.

Classifier helper: `_classify_chunk_type(path: str) -> Literal["prod", "tests", "docs"]`. Single-pass `fnmatch` over
the lookup table.

### CLI / MCP plumbing

Mirrors the #114 surface:

- `cli.handle_search`: two new typer.Options — `--dedup-locales`
  (bool flag) and `--prefer` (`Literal["prod", "tests", "docs"] | None = None`).
- `cli._try_mcp_search`: forward `dedup_locales` and `prefer`
  in the MCP `call_tool` payload.
- `mcp_server.search_codebase`: new params
  `dedup_locales: bool = False, prefer: str | None = None`
  passed through to `searcher.search_codebase`.
- `api.search_codebase`: same.
- `search.search_codebase` + `_search_codebase_encoded`: same.

Usage guard: both are code-only filters. `--prefer` with
`--type vault` raises the existing `invalid_filter_for_search_type`
error (PR #109's pattern); `--dedup-locales` is technically
harmless on vault but limit to code for shape consistency.

### Exception-handling

The classifier helpers (`_locale_variant_key`,
`_classify_chunk_type`) are pure-Python string operations — no
I/O, no parsing of external data, no realistic exception
surface. No new `except` clauses introduced. The post-rerank
pass iterates `SearchResult` instances and mutates their score
in place; any unexpected attribute access would propagate up to
the caller per the no-swallow rule.

### Tests

- `tests/test_search_unit.py`:
  - `TestLocaleVariantKey`: input paths → expected stem (or
    None).
  - `TestClassifyChunkType`: input paths → expected category.
- `tests/test_cli.py`:
  - `--dedup-locales --type vault` → usage error.
  - `--prefer prod --type vault` → usage error.
  - Fast-path forwarding: `_try_mcp_search` payload contains
    `dedup_locales=True` and `prefer="prod"` when set.
- `tests/test_mcp_server.py`:
  - `search_codebase` tool exposes `dedup_locales` + `prefer`
    params.
- Integration test in `test_codebase_integration.py`:
  - Seed two locale-variant files with identical content; run
    `search_codebase(..., dedup_locales=True)`; assert only one
    result returned.
  - Seed a `tests/` file with the same content as `src/`; run
    `--prefer prod`; assert the `src/` hit ranks above the
    `tests/` hit.

### Smoke

Against the rag worktree itself: `--prefer tests` should
surface `test_*.py` results above `cli.py` for query like
"service status"; `--prefer prod` reverses.

## Recommendation

Ship as one PR. The two issues share the post-rerank
insertion point + the plumbing. Splitting would duplicate four
files of signature changes.

Defaults stay off — neither pass runs unless the user opts in
with the flag. This avoids surprise reordering for existing
consumers; the new behaviour is purely additive.
