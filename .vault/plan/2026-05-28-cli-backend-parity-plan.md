---
tags:
  - '#plan'
  - '#cli-backend-parity'
date: '2026-05-28'
related:
  - '[[2026-05-28-cli-backend-parity-adr]]'
  - '[[2026-05-28-cli-backend-parity-research]]'
  - '[[2026-05-28-cli-search-filters-plan]]'
---

# `cli-backend-parity` `cli backend parity bundle plan` plan

Bundle plan resolving gh issues #107, #108 (partial), #110 (easy items),
and #111 in one PR. Builds on the original `cli-search-filters` plan
(scoped to #107) by widening the scope to the CLI/MCP/backend parity
audit captured in the related research document. Design-heavy follow-ups
are queued as Wave 2 issues, not implemented here.

## Proposed Changes

Wave 1 is one PR. It ships:

- CLI/MCP/backend parity wires for every filter the backend already
  honors.
- Fail-hard fast-path semantics when `--port` is given but the
  resident service is unreachable, with `--allow-fallback` opt-in for
  legacy behaviour.
- Path indicator on `search` output, tqdm suppression by default,
  larger `--max-results` default, `--no-truncate` flag.
- `clean` requires explicit target (#111).
- `node_type` payload index in Qdrant; trailing-slash route fix so MCP
  calls do not 307-redirect.
- README, package README, and rule file updated to document the full
  Wave 1 surface.

Wave 2 is filed as follow-up issues only:

- `--json` output mode across every command.
- Daemon-side silent-death detection (atexit, heartbeat in service.json).
- `service status` divergence cross-check (PID, alive, listening).
- `service.log` clean-shutdown / crash distinction.
- Glob / prefix path filtering for #108 (needs design: Python
  post-filter vs Qdrant `MatchText` / prefix support).
- `index --type all` default re-evaluation (mirrors #111 concern).

## Tasks

### Phase 1 - Parity wires

1. `mcp_server.search_codebase` (`src/vaultspec_rag/mcp_server.py`):
   add `path: str | None = None` parameter; forward to
   `searcher.search_codebase(path=path, ...)`.
1. `mcp_server.search_vault`
   (`src/vaultspec_rag/mcp_server.py`): add `doc_type`, `feature`,
   `date`, `tag` parameters; build a synthetic query suffix with
   `type:` / `feature:` / `date:` / `tag:` tokens before calling
   `searcher.search_vault`, OR (preferred) extend
   `search.VaultSearcher.search_vault` to accept the same kwargs and
   merge them into `parsed.filters` after `_encode_query`.
1. `search.VaultSearcher.search_vault` (`src/vaultspec_rag/search.py`):
   accept the four vault filter kwargs and merge them into
   `parsed.filters` before calling `_search_vault_encoded`. Mirrors
   the keyword override pattern already in `search_codebase`.
1. CLI `search` command (`src/vaultspec_rag/cli.py`):
   - Add `--path` (code search).
   - Add `--doc-type`, `--feature`, `--date`, `--tag` (vault search).
     `--doc-type` is the chosen name; `--type` is the existing
     source switch and cannot be reused.
   - Reject filter flags whose value is supplied with the wrong
     search type (mirror the existing #107 usage guard).
1. `_try_mcp_search` (`src/vaultspec_rag/cli.py`): forward every new
   field in the MCP `call_tool` payload. Same kwarg-only shape as the
   `cli-search-filters` patch.
1. In-process branch of `handle_search`: forward every new field to
   `searcher.search_vault` / `searcher.search_codebase`.

### Phase 2 - Fail-hard fast path

1. `_try_mcp_search` and `_try_mcp_reindex`
   (`src/vaultspec_rag/cli.py`): adopt the
   ECONNREFUSED-vs-other-error discrimination already in
   `_try_mcp_admin`. Return `None` only on connection refused; return
   a structured `{"ok": False, "error": ...}` dict on other transport
   errors so the caller can surface them.
1. `handle_search` and `handle_index`
   (`src/vaultspec_rag/cli.py`): when `--port` is given and the
   service returns the structured "connection refused" / `None`
   signal, exit with the same remediation text the lock-error UX
   shows. Add `--allow-fallback` (boolean) opt-in that restores the
   silent-fallback behaviour. Default: hard-fail.
1. `_display_search_results` (`src/vaultspec_rag/cli.py`): accept a
   `path_indicator: Literal["mcp", "in-process"]` parameter; render
   `"Search Results: {search_type} (via MCP)"` or
   `"Search Results: {search_type} (via in-process)"` mirroring
   `handle_index:591` / `handle_index:703`.

### Phase 3 - UX polish

1. tqdm suppression. Set `HF_HUB_DISABLE_PROGRESS_BARS=1` and
   `TRANSFORMERS_NO_TQDM=1` in `EmbeddingModel.__init__` and pass
   `show_progress_bar=False` to every `SentenceTransformer`,
   `SparseEncoder`, and `CrossEncoder` constructor by default. Gate
   re-enabling behind a `--verbose` flag on `search` and `index`
   (sets the env vars to "0" before construction).
1. `search --max-results` default 5 -> 10.
1. `search --no-truncate` flag: bypass the 120-character snippet and
   path-column truncation in `_display_search_results` when set.
1. `clean` (`src/vaultspec_rag/cli.py:731`): make `clean_type`
   required (drop the `"all"` default). Update the typer Argument
   signature; help text already lists the choices.

### Phase 4 - Schema / transport

1. `store.ensure_code_table` (`src/vaultspec_rag/store.py`): add
   `create_payload_index(collection, "node_type", KEYWORD)`. Lazy on
   next index; no migration required for existing collections (the
   linear-scan fallback still returns correct results).
1. MCP server trailing-slash route
   (`src/vaultspec_rag/mcp_server.py`): add a no-redirect route for
   `/mcp` -> the same handler as `/mcp/` so calls land in one
   round-trip instead of two.

### Phase 5 - Docs

1. `README.md`: document `--path`, `--doc-type`, `--feature`,
   `--date`, `--tag`, the query-string token syntax, the new
   `--max-results` default, `--no-truncate`, `--allow-fallback`, the
   fail-hard default, and the `[via MCP]` / `[via in-process]`
   indicator. Update the `clean` example so the explicit target is
   visible.
1. `src/vaultspec_rag/README.md`: mirror.
1. `.vaultspec/rules/rules/vaultspec-rag.builtin.md`: mirror the
   CLI flag table; document the query-string token syntax in the MCP
   tools section.

### Phase 6 - Tests, lint, push

1. Unit tests in `src/vaultspec_rag/tests/test_cli.py`:
   - Each new CLI flag is honored on the fast path (kwarg reaches
     payload) and the in-process path.
   - `--port` unreachable + no `--allow-fallback` -> exit code 1 with
     remediation text.
   - `--port` unreachable + `--allow-fallback` -> falls through to
     in-process path.
   - `search` table title carries `(via MCP)` or
     `(via in-process)` depending on path.
   - `clean` with no positional arg exits with usage error (Typer
     surfaces the missing argument).
   - `--no-truncate` removes the truncation.
1. Unit tests in `src/vaultspec_rag/tests/test_mcp_server.py`:
   - `search_codebase(path=...)` builds a payload that the engine
     honors.
   - `search_vault(doc_type=..., feature=..., date=..., tag=...)`
     applies the same filter merging as the in-process path.
1. Unit tests in `src/vaultspec_rag/tests/test_store.py`:
   - `ensure_code_table` creates a `node_type` payload index.
1. `uv run pytest src/vaultspec_rag/tests` clean.
1. `uv run ruff check` + `mdformat` clean.
1. Commit each phase separately; push to
   `feature/107-cli-search-filters`; rely on existing PR #109.

## Parallelization

Phases 1-4 are independent enough to land in parallel commits, but the
test phase (6) needs the surface from 1-3 to write the assertions.
Phase 5 docs depend on the final flag shape, so do it last.

## Verification

- All unit tests pass (`uv run pytest src/vaultspec_rag/tests`).
- `uv run ruff check` + `mdformat` + `vaultspec-core vault check`
  clean.
- CI green on all five jobs.
- Manual smoke: `vaultspec-rag search "x" --type code --path src/foo --port 8766` on a live service applies the path filter; the same
  invocation with a dead service exits with remediation text;
  `--allow-fallback` restores fallthrough.
- `vaultspec-rag clean` (no target) errors with usage; `clean vault`
  / `clean code` / `clean all` still work.
- README examples reproduce the documented behaviour end-to-end.

Wave 2 verification is deferred to the follow-up issues; this plan
does not implement them.

## Wave 1 hardening (post-bundle self-audit)

After Waves 1A-1E shipped to PR #109 a self-audit identified
several gaps where the bundle had been less thorough than the
issues warranted. The hardening pass below was tracked as Wave 1F
and folded into the same PR so the published surface is internally
consistent.

### Findings

- `handle_index`'s in-process fallback rendered `Indexing Summary`
  without a path indicator while `handle_search` already shipped
  `(via in-process)`. The asymmetry contradicted the rationale in
  the ADR. **Fixed**: `cli.py:746` now reads
  `Indexing Summary (via in-process)`.
- `_suppress_hf_progress` set HuggingFace env vars but
  `CrossEncoder.predict` still emitted batch bars during in-process
  reranking. **Fixed**: passed `show_progress_bar=False` to
  `reranker.predict` in `search.py`.
- `src/vaultspec_rag/README.md`'s MCP-tools table and Python API
  table still showed the pre-bundle `search_codebase` /
  `search_vault` signatures. **Fixed**: both tables now list every
  new filter parameter.
- The Wave 1B exception discrimination in `_try_mcp_search` /
  `_try_mcp_reindex` was tested only on the connection-refused
  leg. **Fixed**: three new tests exercise the live-but-broken
  structured-error return path via monkeypatched `asyncio.run`.
- The 307 `/mcp` -> `/mcp/` redirect fix was reasoned about but
  not verified. **Verified**: booted the service on port 18877,
  observed `GET /mcp` -> 307 Location: /mcp/ and confirmed
  `streamable_http_client('.../mcp/')` returns 8 tools without a
  redirect hop. The trailing-slash fix is correct.

### Verification outcomes

- **Integration suite (1F-7):** 180 tests passed in 949s against
  `feature/107-cli-search-filters` at `d559ae5`. No regressions
  introduced by the bundle.
- **Real-world smoke test (1F-8):** booted the service on port
  18877 and walked the fail-hard contract end-to-end:
  - Indexed the vault via `--port`; the summary title rendered
    `Indexing Summary (via MCP)`. 170 chunks indexed.
  - `search --port --type vault --doc-type adr` returned an
    ADR as the top hit. Filter forwarding through MCP is live.
  - `search --port --type vault --doc-type NONEXISTENT-TYPE`
    returned zero results, confirming the filter is real (not
    silently dropped as in 0.2.8).
  - Stopped the service; `search --port` exited 1 with the new
    remediation text instead of silently relaning.
  - `search --port --allow-fallback` printed the legacy
    fallthrough warning, executed the search in-process, and
    rendered `Search Results: vault (via in-process)`.
  - No `Loading weights:` tqdm output appeared on stdout during
    any in-process invocation, confirming the env-var +
    show_progress_bar suppression works in practice.

### Deferred

- CHANGELOG content: this repo is release-please-managed and does
  not keep a manual `## Unreleased` section (see commit
  `bb90689`). Conventional-commit prefixes in the bundle commits
  populate the next entry automatically.
