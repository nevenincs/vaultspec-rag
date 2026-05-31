---
tags:
  - '#research'
  - '#server-mcp-route'
date: '2026-05-31'
related: []
---

# `server-mcp-route` research: `get /mcp 307 redirect — starlette mount behaviour audit`

## Trigger

Issue #126: bare `GET /mcp` against the running RAG service
returns a 307 Location redirect to `/mcp/`, costing every MCP
client an extra round-trip. The CLI fast-path (Wave 1C) was
patched to use `/mcp/` to skip the hop, but external MCP clients
that follow the documented endpoint still pay it. Verified
during Wave 1F-6 (`.vault/plan/2026-05-28-cli-backend-parity-plan.md`):
`GET /mcp` returned `307 Location: http://127.0.0.1:18877/mcp/`.

## Method

One Haiku grounding pass against the worktree + one verification
pass against a live service.

## Findings

### Source of the redirect

`mcp_server.py` `main()` HTTP branch (line ~1369) wraps the
FastMCP streamable-HTTP app in a Starlette `Mount("/mcp")`:

```
app = Starlette(routes=[Mount("/mcp", app=mcp_http_app), Route("/health", ...)])
```

Starlette's `Mount` matches `/mcp` as a prefix. When the request
arrives at the bare `/mcp` (no trailing slash) Starlette issues a
307 to `/mcp/` so the inner app sees its own root path. This is
hard-coded behaviour in Starlette's `Mount.matches` /
`routing._handle_no_match` path.

### Starlette version + workarounds

Installed pin: `starlette 1.2.0`. The constructor signature is
`Starlette(debug, routes, middleware, exception_handlers, lifespan)`
— no `redirect_slashes` argument. (Later Starlette versions
expose this flag; we're below that line.)

Workarounds available without bumping the dep:

- **A. ASGI wrapper that rewrites the scope path.** A small `async def` middleware promotes `scope["path"] == "/mcp"` to `"/mcp/"`
  before delegating to the Starlette app. The Mount never sees
  the bare form, never issues a redirect. No new routes, no
  duplication.
- **B. Add an explicit `Route("/mcp", ...)` that calls into
  `mcp_http_app` with a scope rewrite.** Equivalent to A but
  bound inside Starlette's routing table. Marginally more
  intrusive (two ways to reach the same handler).
- **C. Bump Starlette and use `redirect_slashes=False`.**
  Requires `>= 0.41` (the flag landed mid-0.4x). Bigger blast
  radius across the dep tree; off the table for a 307-only fix.

### Live verification

Booted the daemon on port 18878 with the path-rewrite wrapper in
place. `httpx.get('/mcp', follow_redirects=False)` no longer
returns `307`; the request hangs reading the SSE response (the
expected behaviour for a streamable endpoint). MCP client
(`streamable_http_client('.../mcp')`) lists 8 tools without a
redirect hop. Confirmed identical behaviour against `/mcp/`.

### No new tests existed for the routing layer

`test_mcp_server.py` covered tool registration, prompt
registration, and the daemon lifecycle helpers. Zero tests
probed HTTP route behaviour. New tests added in PR exercise the
scope-rewrite logic + a regression guard that `main()` actually
hands the wrapper to `uvicorn.run`.

## Recommendation

Option A. Smallest cut, no dep bump, no second pathway to the
same handler. Wrapper lives in `main()` so the route table stays
single-source.

## Exception-handling note

Per the no-swallow rule (`[[feedback_no_adhoc_no_swallow]]`),
the wrapper has no `try/except`; any error inside the inner app
propagates to uvicorn's standard error reporting (which logs the
traceback). No new swallows introduced by this fix. The broader
swallow-audit across `cli.py` / `mcp_server.py` is filed as
gh issue #130 and tracked separately to keep this PR scoped.
