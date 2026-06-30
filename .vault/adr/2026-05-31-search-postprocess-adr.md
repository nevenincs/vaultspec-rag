---
tags:
  - '#adr'
  - '#search-postprocess'
date: '2026-05-31'
modified: '2026-06-30'
related:
  - '[[2026-05-31-search-postprocess-research]]'
---

# `search-postprocess` adr: `post-rerank locale dedup + chunk-type prefer score nudge` | (**status:** `accepted`)

## Problem Statement

The remaining two mitigations from the original #108 design
list (gh #121 locale dedup, gh #122 chunk-type weighting). Both
fit one insertion point in `search.py:_search_codebase_encoded`
and share the CLI/MCP/API plumbing pattern from PR #114.
Shipping together avoids duplicating four files of signature
changes across two PRs.

## Considerations

- Both passes are opt-in. Defaults stay unchanged so existing
  consumers see no surprise reordering.
- Both run after `_rerank`: rerank does query-relevance scoring
  uninhibited by user preferences, then the post-rerank passes
  apply preferences as a small nudge or collapse.
- Locale dedup uses path-pattern detection over a closed list
  of i18n file shapes (yml/yaml/json/po + 2-letter language
  code as filename or directory).
- Chunk-type weighting uses a small fnmatch lookup table.
- Score nudge magnitude `±0.05` is intentionally small —
  about one rank-gap in a typical top-k. The CrossEncoder
  stays authoritative; the nudge re-orders ties and near-ties.
- Both passes are pure-Python string operations. No new
  `except` clauses introduced.

## Constraints

- Backwards compatibility: defaults off, no existing API
  signature breaks (all new params are kwargs).
- No new dependencies: stdlib `fnmatch` + `re` (already
  imported).
- Locale dedup score window default 0.10. Chunk-type nudge
  ±0.05. Both expressed as module-level constants for tuning.
- No silent excepts per `[[feedback_no_adhoc_no_swallow]]`.

## Implementation

Two new module-level constants in `search.py`:

```python
_LOCALE_DEDUP_SCORE_WINDOW = 0.10
_PREFER_SCORE_NUDGE = 0.05
```

Two pure helpers:

- `_locale_variant_key(path)` returns a shared stem for
  recognised locale paths, `None` otherwise.
- `_classify_chunk_type(path)` returns
  `"prod" | "tests" | "docs"`.

`_search_codebase_encoded` gains kwargs `dedup_locales: bool = False` and `prefer: Literal["prod", "tests", "docs"] | None = None`. Both passes run **after** the existing `_rerank` call;
both short-circuit when their flag is off, so disabled
behaviour is byte-identical to today.

Public surface mirrors PR #114:

- `search.VaultSearcher.search_codebase`, `api.search_codebase`,
  `mcp_server.search_codebase`, `cli.handle_search` all gain
  the two new params. `_try_mcp_search` forwards them. Usage
  guard rejects both when `--type vault`.

## Rationale

A `±0.05` nudge over more aggressive reordering preserves
discoverability — `--prefer prod` demotes tests, doesn't hide
them. Post-rerank insertion point because rerank does the
query-relevance work that user preferences shouldn't bias.
Heuristic classifier over learned ML because the four-line
lookup addresses the complaint without over-engineering.

## Consequences

- Two new CLI flags, two new MCP params, four files of
  signature plumbing. Mechanical, mirrors PR #114.
- Defaults off — no behaviour change for existing consumers.
- Hardcoded English path conventions (`tests/`, `docs/`,
  `README*`) — repos with other layouts fall through to
  `prod`. Documented; future config knob if needed.
- Locale dedup threshold is a calibration choice. Genuinely
  different translations with tied scores would collapse;
  user opts out by leaving `--dedup-locales` off (the default).
- No new dependencies, no new exception suppression.
