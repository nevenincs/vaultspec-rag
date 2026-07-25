---
tags:
  - '#plan'
  - '#server-mcp-route'
date: '2026-05-31'
modified: '2026-07-25'
related:
  - '[[2026-05-31-server-mcp-route-adr]]'
  - '[[2026-05-31-server-mcp-route-research]]'
---

# `server-mcp-route` `server-side /mcp 307 elimination` plan

Implements gh issue #126. Replaces the Starlette 307 redirect on
bare `/mcp` with an in-process ASGI scope-rewrite wrapper so
every MCP client (CLI, Claude Desktop, third-party harnesses)
lands on the inner app directly.

### Phase `P01` - ASGI scope-rewrite wrapper

Promote a bare `/mcp` request path to the trailing-slash form inside an in-process ASGI wrapper so no client ever sees the mount redirect, keeping the daemon lifespan active behind the plain callable.

- [x] `P01.S01` - Wrap the HTTP application in an in-process ASGI callable that promotes a bare `/mcp` scope path to the trailing-slash form before delegating, and hand the wrapper to the server with the lifespan explicitly enabled so the heartbeat and shutdown hooks still fire; `src/vaultspec_rag/mcp/_mcp.py`.

### Phase `P02` - Tests and live smoke

Cover the rewrite behaviour, guard against a refactor handing the bare application back to the server, and confirm against a live daemon that the redirect is gone.

- [x] `P02.S02` - Cover the scope rewrite with unit tests asserting a bare path is promoted, a trailing-slash path passes through untouched, and an unrelated path is unaffected, plus a guard that the server is handed the wrapper rather than the bare application; `src/vaultspec_rag/tests/`.
- [x] `P02.S03` - Confirm against a live daemon that a bare request returns no redirect status and no redirect location, and that a streaming client lists the expected tools without a redirect hop; `src/vaultspec_rag/tests/integration/`.

## Description

- `mcp_server.py main()` HTTP branch: define a small async
  function that promotes `scope["path"] == "/mcp"` to `"/mcp/"`
  before delegating to the existing Starlette app; hand the
  wrapper to `uvicorn.run` instead of the bare app. Add
  `lifespan="on"` so uvicorn does not skip the lifespan when
  handed a plain async callable.
- Three unit tests covering scope-rewrite behaviour + a
  regression guard.
- Live smoke verification documented in this plan.

## Steps

### Phase 1 — wrapper

1. Define `_mcp_no_redirect(scope, receive, send)` inside
   `main()` HTTP branch, immediately after the
   `app = Starlette(...)` construction.
1. Pass `_mcp_no_redirect` to `uvicorn.run(...)` instead of
   `app`. Add `lifespan="on"` so the daemon's lifespan
   (heartbeat task, atexit hooks) still fires.

### Phase 2 — tests

1. `tests/test_mcp_server.py` `TestMcpPathRewrite`:
   - `test_main_uses_path_rewriting_wrapper` — source
     inspection: `inspect.getsource(main)` contains
     `_mcp_no_redirect` and the `uvicorn.run(\n  _mcp_no_redirect`
     handoff. Catches refactors that accidentally pass `app`
     again.
   - `test_path_rewrite_logic` — three sub-assertions:
     bare `/mcp` rewrites to `/mcp/`, trailing-slash form
     passes through, `/health` passes through.

### Phase 3 — smoke

1. Start the daemon on a free port (used 18878 during
   development).
1. `httpx.get('http://127.0.0.1:18878/mcp', follow_redirects=False)`
   — assert no `307` status, no `Location` header pointing at
   `/mcp/`. Expected behaviour: `ReadTimeout` (SSE endpoint
   awaiting POST), same as `/mcp/`.
1. `streamable_http_client('http://127.0.0.1:18878/mcp')` lists
   the 8 expected tools without a redirect hop.
1. Stop the daemon cleanly.

## Verification

- `uv run ruff check src/vaultspec_rag/` clean.
- `uv run pytest src/vaultspec_rag/tests/test_mcp_server.py`
  passes including the three new cases.
- Live smoke confirms the 307 is gone for both `/mcp` and
  `/mcp/`.
- No new `except` clauses introduced — the wrapper is a pure
  scope-mutation step that delegates to the existing Starlette
  app. Errors inside the inner app propagate to uvicorn's
  standard error path (which logs the traceback).

## Out of scope

- Broader swallow-audit across `cli.py` / `mcp_server.py` is
  filed as gh issue #130 and tracked separately.
- Starlette version bump (would enable native
  `redirect_slashes=False`) is out of scope for a 307-only fix.

## Reference

- ADR: \[[2026-05-31-server-mcp-route-adr]\]
- Research: \[[2026-05-31-server-mcp-route-research]\]
- Wave 1F-6 verification record:
  `.vault/plan/2026-05-28-cli-backend-parity-plan.md`
  (showed `GET /mcp` returned 307 against the unpatched server)
