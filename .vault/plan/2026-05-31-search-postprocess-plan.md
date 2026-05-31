---
tags:
  - '#plan'
  - '#search-postprocess'
date: '2026-05-31'
related:
  - '[[2026-05-31-search-postprocess-adr]]'
  - '[[2026-05-31-search-postprocess-research]]'
---

# `search-postprocess` `search post-process: --dedup-locales + --prefer prod/tests/docs` plan

Implements gh #121 (locale dedup) + gh #122 (chunk-type
weighting) as one PR. Both opt-in, both run post-rerank in
`search.py:_search_codebase_encoded`. Plumbing mirrors PR #114.

## Proposed Changes

- Two pure helpers + two module constants in `search.py`.
- Two new kwargs on `_search_codebase_encoded` /
  `search_codebase` / `api.search_codebase` /
  `mcp_server.search_codebase` / `cli.handle_search` /
  `cli._try_mcp_search`.
- Two CLI flags (`--dedup-locales`, `--prefer`) with usage
  guard against `--type vault`.
- Tests + docs + smoke.

## Tasks

### Phase 1 — backend (search.py)

1. Add `_LOCALE_DEDUP_SCORE_WINDOW = 0.10` and
   `_PREFER_SCORE_NUDGE = 0.05` near `_GLOB_FETCH_MULTIPLIER`.

1. Define `_LOCALE_FILE_EXTS` set and
   `_LOCALE_CODE_RE` regex (2-letter ISO 639) at module
   level.

1. Define `_locale_variant_key(path: str) -> str | None`:
   recognises `locales/<lang>.<ext>`,
   `i18n/<lang>/<name>.<ext>`, and
   `<name>.<lang>.<ext>` shapes. Returns the stem when matched,
   None otherwise.

1. Define `_classify_chunk_type(path: str) -> Literal["prod", "tests", "docs"]`:

   - `tests` first: `**/test_*.py`, `**/*_test.py`,
     `**/tests/**`, `**/spec/**`, `**/__tests__/**`.
   - `docs` next: `**/docs/**`, `**/doc/**`, `README*`,
     `**/*.md`, `**/*.rst`.
   - Else `prod`.

1. Extend `_search_codebase_encoded` signature with
   `dedup_locales: bool = False, prefer: str | None = None`.

1. After the existing `_rerank` call, insert:

   ```python
   if prefer:
       for r in results:
           cat = _classify_chunk_type(r.path)
           r.score += _PREFER_SCORE_NUDGE if cat == prefer else -_PREFER_SCORE_NUDGE
       results.sort(key=lambda r: r.score, reverse=True)
   if dedup_locales:
       results = _collapse_locale_variants(results)
   return results
   ```

1. Define `_collapse_locale_variants(results: list[SearchResult]) -> list[SearchResult]`: group by locale key, keep top-scoring,
   annotate snippet with the collapsed locale set.

### Phase 2 — public surface

1. `search.VaultSearcher.search_codebase`: forward both
   kwargs.
1. `api.search_codebase`: forward both kwargs.
1. `mcp_server.search_codebase`: declare the two params
   (`dedup_locales: bool = False, prefer: str | None = None`),
   forward to `slot.searcher.search_codebase`.
1. `cli.handle_search`: add two typer.Options:
   - `--dedup-locales` (bool flag).
   - `--prefer` accepting `prod|tests|docs` via
     `Literal["prod", "tests", "docs"]`.
1. `cli._try_mcp_search`: add the kwargs, forward to MCP
   payload only when set + `search_type == "code"`.
1. In-process branch of `handle_search`: forward to
   `searcher.search_codebase`.
1. Usage guard: both flags with `--type vault` raise
   `invalid_filter_for_search_type` via the existing
   `_emit_filter_mismatch` helper (or matching JSON-aware
   `_emit_json_error_and_exit`).

### Phase 3 — tests

1. `tests/test_search_unit.py`:
   - `TestLocaleVariantKey`: positive matches for
     `locales/en.yml`, `i18n/es/messages.po`,
     `messages.en.po`; negative matches for `src/foo.py`,
     `README.md`.
   - `TestClassifyChunkType`: positive matches for the three
     categories + precedence (`tests/docs/...` → tests).
1. `tests/test_cli.py`:
   - `--dedup-locales --type vault` → exit 2 with
     usage error.
   - `--prefer prod --type vault` → exit 2.
   - Fast-path forwarding: `_try_mcp_search` payload contains
     `dedup_locales=True` and `prefer="prod"` when set.
1. `tests/test_mcp_server.py`:
   - `search_codebase` tool exposes `dedup_locales` and
     `prefer` params.
1. `tests/integration/test_codebase_integration.py`:
   - Seed two locale-variant files with the same content;
     `search_codebase(..., dedup_locales=True)` returns one.
   - Seed a `tests/` file mirroring a `src/` file;
     `--prefer prod` ranks `src/` above `tests/`.

### Phase 4 — smoke

1. Against the rag worktree itself:
   `vaultspec-rag search "service status" --type code --prefer tests` should surface `test_*.py` results above
   `cli.py`. `--prefer prod` reverses.

### Phase 5 — commit + push + PR + merge

1. One commit with vault docs + helpers + plumbing + tests in
   the same changeset.
1. PR title `feat(search): --dedup-locales + --prefer prod/tests/docs (#121, #122)`.
1. Ignore Gemini per standing instruction. Merge after CI
   green.

## Parallelization

Phase 1 + Phase 2 touch disjoint files (except for the
signature plumbing in `search.py:search_codebase` which depends
on the new params). Sequential edits within each file.

## Verification

- ruff + mdformat + vault check schema clean.
- New unit tests pass; full suite stays green.
- Integration tests cover the dedup + prefer behaviour
  end-to-end.
- Smoke confirms the flags re-order results as expected.
- No new bare excepts.

## Out of scope

- Configurability of the score window / nudge magnitude
  beyond module constants. Future env-var or config knob if
  needed.
- Non-English path conventions for the chunk-type classifier
  (e.g. `pruebas/` for tests). Future i18n-aware classifier if
  the surface proves valuable.
- Replacing the locale heuristic with a learned classifier.
  The closed list of i18n shapes covers the documented #108
  complaint; richer detection is future work.
