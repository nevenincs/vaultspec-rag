---
tags:
  - '#research'
  - '#cli-search-filters'
date: '2026-05-28'
related: []
---

# `cli-search-filters` research: `issue #107 root-cause analysis`

## Question

Why does `vaultspec-rag search` silently drop `--language`, `--node-type`,
`--function-name`, and `--class-name` when the user passes `--port` to route
through the resident MCP service, while the in-process path honours them?

## Reproduction (from issue #107)

```
$ vaultspec-rag search "classify transaction" --type code --max-results 4 --port 8766
... 4 unfiltered hits
$ vaultspec-rag search "classify transaction" --type code --max-results 4 \
    --function-name NONEXISTENTFUNCXYZ --port 8766
... identical 4 hits, identical scores
$ vaultspec-rag search "classify transaction" --type code --max-results 4 \
    --language cobol --port 8766
... identical 4 hits (codebase has zero COBOL)
```

A working contract should return zero hits for both narrowing values.

## Findings

- The `search` Typer command (`src/vaultspec_rag/cli.py`) accepts all four
  filter options and threads them into the in-process branch via
  `searcher.search_codebase(...)`.
- The fast-path helper `_try_mcp_search` does not expose the filter
  parameters at all. The MCP `call_tool` payload is hard-coded to
  `{"query", "top_k", "project_root"}`, so the filter values never leave
  the CLI process.
- The MCP server side (`mcp_server.py`'s `search_codebase` tool) accepts
  every filter field. The wire format already supports the contract; the
  defect is in the CLI-to-MCP glue only.

## Implication

Because the fast path is the recommended path for concurrent agents
(single resident service, shared GPU warm-up, single Qdrant lock holder),
the silent drop means every multi-agent setup loses AST narrowing without
warning. Users see noisy unfiltered top-k results instead of empty sets
for nonsense values.

## Recommendation

Extend `_try_mcp_search` to accept the four filter kwargs and forward
non-None values into the payload when `search_type == "code"`. Reject
filter + non-code search-type combinations on both paths so the contract
is uniform (today the in-process path also silently ignores them on
`--type vault`). Add unit tests asserting the new contract.
