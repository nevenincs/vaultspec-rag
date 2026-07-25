---
tags:
  - '#research'
  - '#mcp-project-root-contract'
date: '2026-07-25'
modified: '2026-07-25'
related: []
---

# `mcp-project-root-contract` research: `which side of the project-root contract is wrong`

Every MCP search and reindex tool advertises `project_root` as optional and then
forwards the empty string, which the daemon route rejects with a 400. Two halves
of one contract disagree, so exactly one of them is wrong and the question is
which. The evidence says the schema is right and the client-side forwarding is
wrong: the daemon genuinely cannot supply this value, and the MCP process
genuinely can.

## Findings

### The advertised optionality is unreachable

Every tool signs the argument as optional with a `None` default and then
forwards `project_root or ""`. A caller that omits it - the documented default -
therefore always puts an empty string on the wire, and the route rejects it. The
optional-ness is advertised but cannot be exercised, so no MCP client can use
the documented default successfully.

### The daemon cannot resolve a default, and must not try

The service is a machine-global, multi-root singleton: one process serves every
indexed root on the box. It has no project of its own, and its working directory
is wherever the operator started it from - typically unrelated to any caller's
project. Loosening the route to accept a blank root would mean guessing, and the
failure mode of a wrong guess is silent rather than loud: one root's query
resolving against another root's index, returning plausible results from the
wrong codebase. The route's strictness is the mechanism preventing that.

### The MCP process can resolve it, exactly and locally

A stdio MCP server is launched per project by its host, so its working directory
is that project's root. The value the caller would otherwise have to restate on
every call is already sitting in the process. This is the one place in the chain
where a default is knowable rather than guessable.

### The empty string is forwarded at more sites than the report lists

Beyond the search, reindex, clean, status and code-file tools, the vault
document resource passes the same empty string. A resource URI carries no root
at all, so that call site can never supply one and depends entirely on a
resolved default. Any fix scoped only to the reported tool list would leave it
broken.

### Not investigated

Whether a host that launches the stdio server from somewhere other than the
project root exists in practice. If one does the explicit argument remains
available and takes precedence, so such a host is not locked out - but the
default would be wrong for it, and that has not been measured.

## Sources

- `src/vaultspec_rag/mcp/_tools.py`
- `src/vaultspec_rag/mcp/_resources.py`
- `src/vaultspec_rag/server/_routes.py`
