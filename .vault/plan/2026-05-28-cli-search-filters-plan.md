---
tags:
  - '#plan'
  - '#cli-search-filters'
date: '2026-05-28'
modified: '2026-06-30'
related:
  - '[[2026-05-28-cli-search-filters-adr]]'
  - '[[2026-05-28-cli-search-filters-research]]'
---

# `cli-search-filters` `cli search filter forwarding fix` plan

Fix github issue #107: the `vaultspec-rag search` CLI advertises four code-search
narrowing filters (`--language`, `--node-type`, `--function-name`,
`--class-name`) but silently drops them on the `--port` fast path. The MCP
`search_codebase` tool already accepts these fields; the gap is purely in the
CLI-to-MCP glue inside `_try_mcp_search`.

## Proposed Changes

- Extend `_try_mcp_search` in `src/vaultspec_rag/cli.py` to accept the four
  filter parameters as keyword-only arguments and forward them in the
  `call_tool` payload when `search_type == "code"`.
- When any filter is supplied with `search_type != "code"`, return a structured
  error dict so `_display_mcp_error` reports the usage problem instead of
  silently dropping filters.
- Update the `handle_search` call site to pass the filters through.
- Apply the same `vault + filter` usage guard to the in-process path so both
  paths share one contract.
- Add unit tests covering: filter kwargs reach the payload for code search,
  filter+vault yields a usage error, and back-compat for filter-less calls.

## Tasks

- Patch `_try_mcp_search` signature and payload construction.
- Patch `handle_search` to forward filters; raise usage error for `vault + filter`.
- Extend `TestMcpFastPath` with new unit tests.
- Run `uv run pytest src/vaultspec_rag/tests/test_cli.py` and `uv run ruff check`.
- Commit, push, open PR linking #107, address Gemini findings, merge.
- Trigger release-please patch release after merge.

## Parallelization

Trivial single-file patch + test addition. No parallelization needed.

## Verification

- Unit tests pass for `TestMcpFastPath` (existing + new).
- Manual reasoning matches the issue's repro: nonsense `--function-name` /
  `--language cobol` on the fast path now reaches the MCP tool and returns
  empty.
- `--type vault --language python` raises a usage error on both fast and
  in-process paths.
- `ruff check` clean.
