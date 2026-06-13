---
tags:
  - '#adr'
  - '#server-mcp-route'
date: '2026-05-31'
modified: '2026-05-31'
related:
  - '[[2026-05-31-server-mcp-route-research]]'
---

# `server-mcp-route` adr: `asgi path-rewrite middleware to skip starlette mount redirect` | (**status:** `accepted`)

## Problem Statement

Starlette's `Mount("/mcp")` redirects bare `GET /mcp` to `/mcp/`
with a 307 response. Every MCP client hitting the documented
endpoint pays an extra round-trip. PR #109's Wave 1C patched the
CLI client to use `/mcp/`; external MCP clients (Claude Desktop,
Claude Code config, third-party harnesses) still 307 because the
server-side behaviour is unchanged.

## Considerations

- Starlette 1.2.0 has no `redirect_slashes=False` constructor
  argument. Later Starlette versions expose it; bumping the dep
  is out of scope for a 307-only fix.
- A small ASGI wrapper around the Starlette app can promote
  `scope["path"] == "/mcp"` to `"/mcp/"` in-process. The Mount
  never sees the bare form, never issues a redirect.
- Adding a second Starlette `Route("/mcp", ...)` alongside the
  Mount creates two pathways to the same handler — duplication
  the wrapper avoids.

## Constraints

- No dep bump. Starlette stays pinned at 1.2.0.
- No new code paths. The wrapper rewrites the scope and delegates
  to the existing Starlette app; the routing table stays
  single-source.
- No silent exception suppression in the wrapper. Per the
  no-swallow rule, any error inside the inner app propagates to
  uvicorn's standard error path which logs the traceback.

## Implementation

In `mcp_server.py main()` HTTP branch, after the existing
`app = Starlette(...)` construction, define a small async
function and hand it to `uvicorn.run` instead of `app`:

```python
async def _mcp_no_redirect(scope, receive, send):
    if scope["type"] == "http" and scope.get("path") == "/mcp":
        scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
    await app(scope, receive, send)

uvicorn.run(_mcp_no_redirect, host=..., port=..., lifespan="on")
```

`lifespan="on"` is explicit because uvicorn's lifespan
autodetection can be unreliable when handed a plain async
function instead of a Starlette instance.

## Rationale

- Smallest diff. One async function, one parameter swap on
  `uvicorn.run`.
- No new dep, no new routing surface.
- The wrapper applies only to the documented bare path. Other
  paths (`/health`, `/mcp/whatever`) pass through unchanged.

## Consequences

- `GET /mcp` no longer returns 307. Clients that handled the
  redirect transparently see no behaviour change beyond the
  saved round-trip. Clients that explicitly required `/mcp/`
  (e.g. the CLI helpers patched in Wave 1C) continue to work.
- The wrapper adds one comparison per HTTP request. Negligible.
- The wrapper is the only piece of ASGI plumbing outside the
  Starlette routing table. Future routing additions should be
  registered as Starlette routes, not wrapped further.

## Verification

- Unit tests: three new cases in `tests/test_mcp_server.py` —
  scope-rewrite logic for the bare path, pass-through for the
  trailing-slash form, pass-through for `/health`. Plus a
  regression guard that `main()` actually hands the wrapper to
  `uvicorn.run` (source inspection — survives refactors that
  keep the intent).
- Live smoke: boot the daemon on a free port, probe `GET /mcp`
  with `follow_redirects=False`, confirm no `307` response.
  MCP client connects against both URLs without a redirect hop.
  Documented inline in this PR.
