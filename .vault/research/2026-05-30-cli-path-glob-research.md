---
tags:
  - '#research'
  - '#cli-path-glob'
date: '2026-05-30'
related: []
---

# `cli-path-glob` research: `qdrant filter capability + path payload audit`

## Trigger

Issue #114 (substantive ask from #108): `vaultspec-rag search --type code`
returns top-k crowded with translation files / test docstrings in
polyglot codebases. PR #109 wired the existing exact-match `path`
filter through MCP and CLI as `--path`; that is not enough — users
need to **exclude** path patterns (e.g. `locales/*.yml`) or restrict
to a prefix (e.g. `src/aeat/application/**`).

This research grounds the implementation choice before touching code.

## Question

Can we satisfy the glob/prefix need with a Qdrant-side filter, or must
we post-filter in Python? Two design options were on the table in the
issue body:

- A: post-query Python `fnmatch` after `hybrid_search_codebase`
- B: Qdrant-side prefix/text filter against the `path` payload

## Findings

### Qdrant capability (qdrant-client 1.17.1)

Installed pin in `pyproject.toml:21` requires `>= 1.16.0`; resolved is
`1.17.1`. The `path` field is `PayloadSchemaType.KEYWORD`
(`store.py:332-342`). The Match classes available in this version are:

- `MatchValue` — exact equality on KEYWORD fields. No prefix support.
- `MatchAny` — exact membership in a list.
- `MatchText` / `MatchTextAny` — token-level match, requires a TEXT
  index. Path separators are tokenisation boundaries, so
  `MatchText("src/foo")` would match documents that contain both
  `src` and `foo` as separate tokens anywhere — useless for path
  filtering.
- `MatchPhrase` — same TEXT-index requirement.

No `MatchPrefix`, no wildcard operator. **Option B is not viable**
without converting the `path` payload to a TEXT index, which would
break the existing exact-match `--path` flag's contract (shipped in
PR #109) and require a reindex of every existing collection.

### Path payload format

The indexer normalises path separators at write time:

- `indexer.py:1600` (codebase): `str(path.relative_to(self.root_dir)) .replace("\\", "/")`.
- `indexer.py:748` (vault): same pattern.

Integration tests confirm POSIX format on every platform
(`test_codebase_integration.py:317` asserts `"src/app.py"` literally).
`fnmatch.fnmatch` operates on the stored string directly with no
separator-translation overhead, as long as caller patterns are
normalised too.

### Existing `--path` consumer audit

`path` flows through exactly five layers, mirroring the structure
PR #109 standardised:

- `cli.py:1276-1279` — Typer `--path` option
- `cli.py:_try_mcp_search` payload — forwarded as keyword
- `api.py:145,151,179` — facade kwarg
- `mcp_server.py:662,711` — MCP tool param
- `search.py:_search_codebase_encoded` — merges into store filters
- `store.py:950-963` — `_build_code_filter` emits `MatchValue`

Adding `include_paths` / `exclude_paths` list params slots in at four
of these (the store builder is bypassed because globs are post-query,
not store-side). `SearchResult.path` reads `r["path"]` raw, so glob
matching against the same string is consistent with what users see.

## Recommendation

**Implement Option A only.** Post-query `fnmatch` in
`_search_codebase_encoded` after `hybrid_search_codebase` returns
`raw_results`, before SearchResult construction so reranker / graph
boost only see the survivors. Normalise caller patterns once (`\\` →
`/`); trust the indexer for the payload side.

Bump the existing `fetch_limit` (`search.py:540`) when filters are
active: `max(top_k * 10, 50)` instead of `max(top_k * 4, 20)` so an
aggressive `--exclude-path locales/*.yml` does not starve top-k. The
multiplier lives in a module-level constant so it can be tuned later
without churning the call site.

Wire the lists through `api.search_codebase`, `mcp_server. search_codebase`, `cli.handle_search`, and `cli._try_mcp_search` in
the same shape as the existing `--path` flag — see PR #109 for the
template.
