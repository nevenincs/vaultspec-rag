---
tags:
  - '#research'
  - '#mcp-read-only-mode'
date: '2026-08-26'
modified: '2026-08-26'
body_schema: 'body-v1'
body_hash: 'sha256:68bb1856ddcd70ceab59d52be5a34403259e6cf19b235df3e3bafb7e68a47bcf'
related: []
---

# `mcp-read-only-mode` research: `read-only MCP launch surface`

## Findings

### What is being asked for

A launch flag that serves only the search and read tools, with the
index-management tools **absent from the advertised listing** rather than
present-and-refusing. Omission is the load-bearing part: the consuming harness
holds that an agent must not be handed the schema of a capability it may not
use.

Six tools would be omitted. Two are destructive (`clean_all`,
`clean_documents`) and four are expensive process management (`reindex_vault`,
`reindex_codebase`, `reindex_documents`, `reindex_all`). All six act on the
machine-wide shared index, not on anything scoped to the caller's run.

### Why a consumer-side allowlist does not settle it

The consumer already allowlists the search and read tools in its registry. That
narrows what it permits, not what the server advertises, so the model still
sees the destructive schemas. The requesting project reports a live incident
where deny-by-permission leaked: a write-capable server reachable through a
user-global config performed writes that bypassed the containment meant to stop
them. Blast radius is the second half of the argument - a run-scoped write harms
one run, while dropping the shared index harms every consumer on the machine.

### Where the surface is actually decided

Registration happens as a side effect of **importing** `_tools.py`: each tool
is bound by an `@mcp.tool()` decorator evaluated at import time, against the
single shared server instance built in `mcp/_mcp.py`. There is no registry
consulted later that a flag could filter.

That is the whole architectural question. A flag cannot simply branch at call
time, because by the time any call arrives the tool is already advertised. The
options are to decide before the decorators run, or to remove entries after
they have run.

### The entry point already parses flags

`vaultspec-search-mcp` resolves to `server:main`, and `server/_main.py` already
builds an `argparse` parser for `--port`, `--parent-pid` and `--launch-token`.
A new flag has an established home; nothing needs inventing to carry it.

### There is already a test that owns this surface

`test_server.py` holds `TestToolRegistration`, which asserts the expected tool
names and the tool count against `mcp.list_tools()`. The acceptance criterion
that a newly added mutating tool must not silently appear under the flag has a
natural home there, and the count assertion is what would catch it.

### What the requester asks be treated as stable

The flag is to be the contract rather than a release version: consumers assert
the served surface at runtime instead of pinning. Pinning across this ecosystem
is explicitly unwanted, since it stalls development and pushes upgrade burden
onto every consumer. That makes the flag name and its served set an interface
decision, not an implementation detail - which is what carries this into an ADR
rather than a direct fix.

## Sources

- The requesting issue, its stated acceptance criteria, and the companion
  request filed against the core project.
- `src/vaultspec_rag/mcp/_tools.py` - the `@mcp.tool()` registration sites and
  the six mutating tools named above.
- `src/vaultspec_rag/mcp/_mcp.py` - the single shared `MCPServer` instance.
- `src/vaultspec_rag/server/_main.py` - the existing argument parser.
- `src/vaultspec_rag/tests/test_server.py` - `TestToolRegistration`.
- `pyproject.toml` - the `vaultspec-search-mcp` entry point.
