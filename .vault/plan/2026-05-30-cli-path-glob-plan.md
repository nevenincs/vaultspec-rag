---
tags:
  - '#plan'
  - '#cli-path-glob'
date: '2026-05-30'
modified: '2026-06-30'
related:
  - '[[2026-05-30-cli-path-glob-adr]]'
  - '[[2026-05-30-cli-path-glob-research]]'
---

# `cli-path-glob` `include-path exclude-path glob filter` plan

Implements gh issue #114 — the substantive `#108` ask. Adds
`--include-path PATTERN` and `--exclude-path PATTERN` (both
repeatable, fnmatch syntax) to `vaultspec-rag search --type code`,
applied post-query in Python against the POSIX-normalised `path`
payload. No backend schema change. See related ADR for rationale.

## Proposed Changes

- `search.VaultSearcher._search_codebase_encoded`: accept the two
  list params, normalise patterns once (`\\` → `/`), apply
  fnmatch filter to `raw_results` before SearchResult
  construction. Bump fetch_limit when filters are active.
- `search.VaultSearcher.search_codebase`: forward the two list
  params.
- `api.search_codebase`: forward the two list params.
- `mcp_server.search_codebase`: expose the two list params with
  `list[str] | None = None` typing so MCP clients can pass them.
- `cli.handle_search`: add `--include-path` / `--exclude-path`
  (both `typer.Option(... list[str] | None ...)` repeatable).
  Reject when paired with `--type vault` mirroring the existing
  usage guard.
- `cli._try_mcp_search`: forward the two lists in the MCP
  payload (omit when empty).
- README + package README + `vaultspec-rag.builtin.md` rule:
  document the two flags, fnmatch syntax, and the over-fetch
  tradeoff.
- Unit tests covering: single include, single exclude, both
  combined, repeatable flag, vault-type rejection, fast-path
  forwarding.
- Smoke test against a live service.

## Tasks

### Phase 1 — backend post-filter

1. Add `_GLOB_FETCH_MULTIPLIER = 10` module-level constant to
   `src/vaultspec_rag/search.py`.
1. Extend `_search_codebase_encoded` signature with
   `include_paths: list[str] | None = None` and
   `exclude_paths: list[str] | None = None`.
1. Normalise patterns once at function entry (single
   comprehension, `\\` → `/`).
1. When either list is non-empty, set fetch_limit to
   `max(top_k * _GLOB_FETCH_MULTIPLIER, 50)` instead of the
   existing branch.
1. After `raw_results = self.store.hybrid_search_codebase(...)`,
   filter in place: keep if `not include_norm or any(fnmatch(p, pat) for pat in include_norm)` AND `not any(fnmatch(p, pat) for pat in exclude_norm)`.

### Phase 2 — facade + MCP

1. `search.VaultSearcher.search_codebase`: forward both lists.
1. `api.search_codebase`: forward both lists.
1. `mcp_server.search_codebase`: declare the two params on the
   tool signature; forward to `slot.searcher.search_codebase`.

### Phase 3 — CLI

1. `handle_search`: add two `typer.Option(..., list[str] | None, "--include-path", help=...)` repeatable flags. Reject
   with `--type vault` (same exit-2 usage error as the code
   filters).
1. `_try_mcp_search`: add the two list kwargs, forward to MCP
   payload only when non-empty and `search_type == "code"`.
1. In-process branch of `handle_search`: forward to
   `searcher.search_codebase`.

### Phase 4 — docs

1. `README.md`: example showing `--exclude-path 'locales/*.yml' --exclude-path 'tests/**'`.
1. `src/vaultspec_rag/README.md`: filter list under "Searching"
   gains the two new flags; MCP-tools table gains
   `include_path` / `exclude_path` in the `search_codebase`
   row.
1. `.vaultspec/rules/rules/vaultspec-rag.builtin.md`: code
   filters table gains the two new flags.

### Phase 5 — tests + smoke

1. Unit tests in `tests/test_search_unit.py` for the fnmatch
   filter against synthetic results.
1. Unit tests in `tests/test_cli.py` for the CLI flag
   forwarding and the vault-rejection guard.
1. Unit tests in `tests/test_mcp_server.py` for the new param
   exposure on the tool schema.
1. Integration test: live searcher with a real corpus that
   contains `locales/`-style and `tests/`-style files; assert
   `--exclude-path` prunes them.
1. Smoke: live service on port 18877, index, search with and
   without the new flags, confirm exclusion.

### Phase 6 — commit + push + PR + merge

Conventional-commit prefixes; PR links #114 and references #108.
Ignore Gemini per standing instruction. Merge after CI green.

## Parallelization

Phase 1 must land before Phases 2-3 (signature dependency). Phases
2-3 can land together. Phases 4-5 depend on the final flag shape;
do them last.

## Verification

- All unit + integration tests pass.
- ruff + mdformat + vault check clean.
- Real-world smoke: against the rag worktree itself, index code,
  then `search --type code "search filter" --port 18877` returns
  expected hits; adding `--exclude-path '*tests*'` prunes the
  test-file results visibly.
