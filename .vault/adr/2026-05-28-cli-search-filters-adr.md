---
tags:
  - '#adr'
  - '#cli-search-filters'
date: '2026-05-28'
modified: '2026-05-28'
related:
  - '[[2026-05-28-cli-search-filters-plan]]'
  - '[[2026-05-28-cli-search-filters-research]]'
---

# `cli-search-filters` adr: `cli fast-path filter contract` | (**status:** `accepted`)

## Problem Statement

The `vaultspec-rag search` CLI advertises four AST-narrowing filters for code
search (`--language`, `--node-type`, `--function-name`, `--class-name`). When
`--port` is supplied to route through the resident MCP service, the filters
are silently dropped: the in-process and fast paths therefore have divergent
contracts and the fast path returns unfiltered top-k for any filter value,
including nonsense ones. See gh issue #107.

## Considerations

- Documentation and workspace rules push every caller toward the resident
  service for shared GPU warm-up and a single Qdrant lock holder; the fast
  path is the default, not an optimization.
- The MCP `search_codebase` tool already accepts every filter field over the
  wire; the gap is purely in CLI-to-MCP payload construction.
- Filters are code-specific. Their meaning for `--type vault` (or future
  `all`) is undefined; silent acceptance hides typos.

## Constraints

- Backwards compatibility: existing call sites pass filters by position
  through `searcher.search_codebase`; the fast-path helper must remain
  callable without filter kwargs for unrelated tests.
- No new dependencies; keep the MCP payload schema unchanged on the server
  side.

## Implementation

- Extend `_try_mcp_search` in `src/vaultspec_rag/cli.py` with keyword-only
  `language`, `node_type`, `function_name`, `class_name` parameters and
  forward non-None values in the `call_tool` payload when
  `search_type == "code"`.
- Reject filter + non-code search-type combinations with a structured
  `invalid_filter_for_search_type` error dict on the fast path and a
  `typer.Exit(code=2)` console message on the in-process path so both paths
  share one contract.
- Update `handle_search` to thread the four filters through.

## Rationale

A single uniform contract — filters always require `--type code`, on every
path — beats silently ignoring them on the recommended path. Returning a
structured MCP error keeps the existing `_display_mcp_error` rendering path
in use and avoids inventing a new transport.

## Consequences

- Callers that previously combined filter flags with `--type vault` now get
  an explicit error instead of a misleading top-k. This is a behavioural
  change but aligns advertised flags with actual semantics.
- Future search types (e.g. `all`) inherit the same guard automatically.
