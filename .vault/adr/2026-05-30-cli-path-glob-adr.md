---
tags:
  - '#adr'
  - '#cli-path-glob'
date: '2026-05-30'
modified: '2026-05-30'
related:
  - '[[2026-05-30-cli-path-glob-research]]'
---

# `cli-path-glob` adr: `post-query fnmatch over posix path payload` | (**status:** `accepted`)

## Problem Statement

Users of `vaultspec-rag search --type code` in polyglot codebases
need to **exclude** path patterns (e.g. `locales/*.yml`,
`tests/**`) or **restrict** to a path subtree
(e.g. `src/aeat/application/**`) so the production code surface is
not crowded out by i18n YAMLs and test docstrings. PR #109's
exact-match `--path` flag is sufficient for "this one file" but
not for "everything under src/foo except locales".

## Considerations

- The existing `path` payload is KEYWORD-indexed for exact match.
  qdrant-client 1.17.1 offers no prefix or wildcard operator on
  KEYWORD fields. Switching to a TEXT index would break exact-match
  `--path` (shipped a week ago in 0.3.0) and require a reindex.
- The indexer normalises path separators to POSIX at write time on
  every platform, so a Python-side `fnmatch.fnmatch(r["path"], pattern)` is consistent and portable as long as caller-supplied
  patterns are normalised once.
- Post-query filtering risks starving top-k when an aggressive
  exclude pattern discards most candidates. The existing
  `fetch_limit` heuristic (`top_k * 4` with reranker, `top_k * 2`
  without) is sized for "trim a few duds"; glob filters can prune
  the majority.
- Wave 1's `--path` flag established the four-layer wiring template
  (CLI → MCP → backend → store). The new flags must follow the
  same shape so consumers learn one pattern.

## Constraints

- No backend schema change. The KEYWORD `path` payload stays as-is;
  the existing exact-match `--path` flag's contract is preserved.
- No new Qdrant feature flag or version bump.
- Flag names must not collide with existing options. The Wave 1
  audit (`research`) showed `--include-path` / `--exclude-path` are
  free.
- Repeatable flags must work both on the CLI fast path and the
  in-process path with identical semantics (no behavioural drift
  between paths).

## Implementation

- `search.VaultSearcher._search_codebase_encoded` accepts
  `include_paths: list[str] | None = None` and
  `exclude_paths: list[str] | None = None` as keyword-only params.
  After `hybrid_search_codebase` returns raw_results, a single
  in-place filter walks the list once: keep a result if no include
  patterns are supplied or at least one include pattern matches,
  AND no exclude pattern matches. Patterns are normalised
  (`\\` → `/`) once at function entry; payload paths are already
  POSIX. The filter runs **before** SearchResult construction so
  the reranker and graph boost only see survivors.
- Module-level `_GLOB_FETCH_MULTIPLIER = 10`. When either list is
  supplied and non-empty, fetch_limit becomes
  `max(top_k * _GLOB_FETCH_MULTIPLIER, 50)` instead of the
  existing `max(top_k * 4, 20)`. The constant is module-level so
  it can be tuned (or env-var-overridden later) without churning
  the call site.
- `search.VaultSearcher.search_codebase`,
  `api.search_codebase`, `mcp_server.search_codebase`, and CLI
  `handle_search` gain the same two list params. CLI surfaces them
  as `--include-path PATTERN` and `--exclude-path PATTERN`, both
  repeatable. `_try_mcp_search` forwards them in the MCP payload.
- Usage guard: `--include-path` / `--exclude-path` with
  `--type vault` raises the same `invalid_filter_for_search_type`
  error the Wave 1 code filters already use.

## Rationale

Option A (post-query fnmatch) is chosen because Option B is not
viable without a backend rebuild and a contract break (research
finding). Option A is also the smallest cut: one filter step in
`_search_codebase_encoded`, list params plumbed through four
files, no store-side change. The fetch_limit bump is a tuning
constant, not a behavioural change for users without filters.

`--include-path` / `--exclude-path` over the alternative
`--prefer prod` / `--prefer tests` chunk-type weighting because
glob globs are a pure mechanism users already understand
(gitignore semantics, fnmatch from Python). Chunk-type weighting
needs a separate classification layer and a richer config surface
— filed as a possible future enhancement, not this issue.

## Consequences

- Users gain two repeatable flags that close the substantive #108
  ranking gap without a reindex or breaking changes.
- Aggressive exclude patterns may return fewer than `top_k`
  results when the over-fetch ceiling (`top_k * 10`) is still not
  enough. The output already handles "fewer than asked" cleanly
  (existing "No results" path); no new failure mode.
- The post-query position means the reranker only ever scores
  survivors, so the CrossEncoder cost is proportional to the
  filtered set, not the raw fetch. Aggressive globs are cheaper to
  rerank, not more expensive.
- A future Wave can swap in Qdrant prefix support (if a later
  qdrant-client release adds it) by replacing the fnmatch loop
  with a store-side filter and dropping the fetch_limit bump.
  The CLI/MCP surface stays stable across that change.
