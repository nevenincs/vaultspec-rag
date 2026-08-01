---
tags:
  - '#plan'
  - '#cli-search-filters'
date: '2026-05-28'
modified: '2026-07-25'
body_hash: 'sha256:eb0ea5dd7fc4112fd4e83ce24365cdf7fbd9cdf4615de45139ceb74714b568f7'
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

### Phase `P01` - Forward the code filters on the service fast path

Carry the four code-search narrowing filters through the service fast path instead of dropping them, and make a filter paired with a vault-type search a usage error on both paths rather than a silent no-op.

- [x] `P01.S01` - Accept the four code-search narrowing filters on the service fast path and forward them in the call payload for a code search, instead of dropping them silently; `src/vaultspec_rag/cli/_search.py`.
- [x] `P01.S02` - Report a filter paired with a vault-type search as a structured usage error, applying the same guard on the in-process path so both share one contract; `src/vaultspec_rag/cli/_search.py`.

### Phase `P02` - Tests

Cover the forwarding, the usage guard, and the unfiltered call so the contract holds in both directions.

- [x] `P02.S03` - Cover that the filters reach the fast-path payload for a code search, that a filter with a vault-type search raises the usage error, and that an unfiltered call is unchanged; `src/vaultspec_rag/tests/test_cli_search.py`.

## Description

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

## Steps

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
