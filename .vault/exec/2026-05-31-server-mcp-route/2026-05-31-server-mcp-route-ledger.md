---
tags:
  - '#exec'
  - '#server-mcp-route'
date: '2026-05-31'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:4f60d2abf76825aabd391e36a4cd5fe93c39b4ec39d8809c7afc1ebef8559cdd'
related:
  - "[[2026-05-31-server-mcp-route-plan]]"
---

# `server-mcp-route` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/mcp_server.py`
- `S02` `M` `src/vaultspec_rag/tests/test_mcp_server.py`
- `S03` `verify:` `Retained commit smoke 41d23e46 Live GET /mcp returns SSE ReadTimeout instead of307` -> `pass`

## Notes

- `S01` Historical change attribution from Git commit 41d23e46ae9dcec033cea2fb5a1d6284593e0817. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S02` Historical change attribution from Git commit 41d23e46ae9dcec033cea2fb5a1d6284593e0817. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S03` Immutable original commit 41d23e46ae9dcec033cea2fb5a1d6284593e0817 explicitly records this historical observation. Full original shell argv, detailed transcripts and broader compound criteria are not retained; no current runtime or whole-Step acceptance inferred. MCP tool-stream completion is not proved by the recorded bare-path ReadTimeout observation.
