---
tags:
  - '#research'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
related:
  - "[[2026-06-07-mcp-server-deconflation-adr]]"
  - "[[2026-06-05-cli-mcp-decoupling-adr]]"
  - "[[2026-06-13-server-first-default-adr]]"
---

# `mcp-service-client` research: `MCP backend rework as a thin service client`

The service backend is now the only production-ready path: one supervised daemon owns
the GPU models and the Qdrant server, and many clients issue concurrent search/index
requests against it without exhausting local resources. The MCP surface, by contrast,
has regressed across five superseding ADRs into a dual-mode, self-referential design
that contradicts its own "consumer client" framing. This research grounds a superseding
ADR (issue #194, PR #195) that reframes the MCP as a **thin service client only**: it
mirrors the CLI's existing client layer, loads no heavy resources, locks nothing,
operates nothing locally outside the server, and is explicitly dysfunctional with a
clear error when the server is down.

The pivotal, load-bearing finding: the CLI **already has** the exact thin-client layer
the MCP needs, and the MCP currently re-implements it byte-for-byte instead of reusing
it. The rework is therefore mostly *collapse and delete*, not *build*.

## Findings

### 1. Current MCP module state

The `src/vaultspec_rag/mcp/` package is a protocol-adapter layer registering **13
tools**, **1 resource** (`vault://{doc_id}`), and **1 prompt** (`analyze_feature`)
against a single shared `FastMCP("VaultSpec Search", stateless_http=True)` instance in
`src/vaultspec_rag/mcp/_mcp.py`. Every tool is `async def` and delegates to the running
daemon over loopback HTTP through one private seam, `_call_daemon` / `_call_daemon_async`
in `src/vaultspec_rag/mcp/_tools.py` (lines 38-91).

Confirmed good: importing `vaultspec_rag.mcp` loads **no** `torch`,
`sentence_transformers`, or `qdrant_client` — the lazy-torch discipline from the
`index-workers-stay-cpu-only` rule holds. When `service.json` is absent the seam raises
`RuntimeError("vaultspec-rag daemon is not running (service.json not found).")`
immediately, with no local fallback. So two of the target invariants already hold in the
package itself.

Confirmed broken / contradictory:

- **The seam is a duplicate.** `_call_daemon` / `_call_daemon_async` re-implement the
  CLI's own wire primitive (see section 2) almost verbatim, reusing only
  `_read_service_status` from the CLI package.
- **`get_index_status` targets a non-existent route.** The tool hits `GET /status`,
  which the daemon does not register anywhere in `server/` — the tool always fails.
- **Phantom artifacts.** `server/_main.py` docstrings and the
  `test_no_mcp_server_conflation` exemption name a `mcp start` command and a
  `cli/_mcp_admin.py` control module; **neither exists**. The ecosystem test still
  asserts the rule documents `"server mcp start"`, a command the CLI does not provide.
- **Stale "server owns `mcp`" docstrings** in `server/__init__.py` and `server/_state.py`
  describe a pre-split reality; the `mcp` instance now lives only in `mcp/_mcp.py`.
- **The package is heavier than advertised at the Python level.** `mcp/_tools.py` does
  `from ..cli import _read_service_status`, and `vaultspec_rag/__init__.py` imports
  `.api` at module top, so importing the "thin adapter" drags `api`, `store`, `search`,
  `embeddings`, and the whole `cli` package into the process — only the CUDA/model
  *runtime* stays lazy. The existing AST isolation test forbids `server`/`store`/
  `service`/`registry` but **not** `cli`/`api`, so it passes while the isolation it
  advertises is violated transitively.

### 2. The reusable CLI client surface (the answer)

The CLI's client layer is one small, import-light module: `src/vaultspec_rag/cli/_http_search.py`.
Every CLI command that talks to the daemon funnels through exactly three public entry
points, all sitting on the private wire primitive `_do_http_call(port, path, payload, timeout)` (lines 75-106), which reads `service.json` via `_read_service_status`, attaches
the `service_token`/`token` bearer, and returns the decoded JSON dict:

- `_try_http_search(...)` (lines 452-552) — `POST /search`. Trinary contract:
  `None` = service unreachable, `dict` with `results` = success, `dict` without =
  structured error (and a `diagnostics` dict on timeout).
- `_try_http_reindex(tool_name, clean, port, project_root)` (lines 109-136) —
  `POST /reindex`.
- `_try_http_admin(tool_name, args, port, timeout)` (lines 235-272), dispatching through
  `_route_admin_tool` (lines 165-232) — the single funnel for every read/control admin
  call: `get_jobs`, `get_logs`, `get_index_status` (`GET /status`... see note),
  `get_service_state`, `list_projects`, `evict_project`, `get_watcher_state`,
  `start_watcher`/`stop_watcher`/`reconfigure_watcher`, `get_code_file`.

Service discovery lives in `src/vaultspec_rag/cli/_service_status.py`:
`_read_service_status()` (lines 189-207, returns `None` unless the JSON carries both
`pid` and `port`) and `_default_service_port()` (lines 210-235, the auto-discovery every
CLI command uses when `--port` is omitted). Status dir honors
`VAULTSPEC_RAG_STATUS_DIR`.

This module imports only stdlib (`urllib`, `json`, `socket`) plus the lightweight
`validate_search_filters` from `..search`; it loads no torch, models, or store. This is
the "CLI -> service is the only proven production path" the user named. Return shapes are
plain `dict` / `list[dict]` / `None` (raw daemon JSON) — exactly what an MCP tool wants
to hand back.

Two gaps the ADR must rule on explicitly: (a) `get_code_file` has a transport route but
no CLI command uses it; (b) `benchmark` and `quality` have CLI commands that run
**in-process only** (no client function) while the MCP today hits daemon `/benchmark`
and `/quality` — so for those two there is no CLI client function to inherit, and the ADR
must either add a thin client wrapper or scope them out.

### 3. Regression archaeology — how the MCP drifted

The MCP has been re-architected five times; the throughline is an unfinished inversion
from *being* the daemon to *consuming* it.

- **2026-03-07 mcp-sync-tools** — tools became `async def` with `anyio.to_thread`
  offload (the SDK does not auto-wrap sync tools). Baseline assumption: the RAG runs
  **in-process inside the tool**. The async-offload invariant survives to today.
- **2026-05-31 server-mcp-route** — added the `_mcp_no_redirect` ASGI wrapper so
  `Mount("/mcp")` never 307-redirects. This cemented that **MCP is served as a Starlette
  mount inside the daemon process** (still live at `server/_main.py:133`, wrapper at
  lines 109-115).
- **2026-06-05 cli-mcp-decoupling** — declared CLI and MCP thin transport wrappers with
  zero business logic, delegating to the `api.py` facade. Still in-process.
- **2026-06-07 mcp-server-deconflation** (pivotal) — split `mcp_server` into `server`
  (the REST daemon) and `mcp` (a protocol adapter), declared the MCP and CLI **"pure
  consumer clients"** making HTTP requests to the service, and mandated a "hard, clean
  cut ... no shims, shadows, mirrors, or dead code." The cut was **incomplete**: the MCP
  app is *still* mounted inside the daemon, so a tool call issues an HTTP request to the
  very daemon serving it.
- **2026-06-10 install-mcp-dependency-fix** — promoted `mcp` to a core dependency because
  the daemon's HTTP transport literally *is* `mcp.streamable_http_app()`; the daemon
  cannot boot without `mcp`. This concedes the daemon-needs-mcp reality and contradicts
  the "optional adapter" framing.

The server-first default flip (PR #189, merged as `9455730`; note `97b6f64` is an
**empty** commit whose tree equals its parent) made the supervised Qdrant server the
default backend and added a token-gated `GET /readiness` route — but only the CLI
`server doctor` consumes it. PR #189 also replaced the synchronous `_call_daemon` with
`await _call_daemon_async` on every tool, whose own docstring states the reason: the
daemon "mounts this same MCP app and would otherwise issue a blocking loopback HTTP
request from its own loop thread (a full-server stall, or a deadlock once the loop is
saturated)." That is the smoking gun — PR #189 did not decouple the MCP; it added a
defensive thread-offload so the still-present **loopback** would not deadlock the daemon.

### 4. Contradictions the superseding ADR must override

1. **"Standalone consumer client" vs "mounted inside the daemon."** The deconflation
   ADR's clean-cut consumer-client mandate coexists with the live `Mount("/mcp")`. The
   ADR must decide: remove the daemon mount and make the MCP a standalone stdio client,
   or keep the mount and retire the "consumer client" language. The user's directive
   ("dysfunctional if the server is down", "operate nothing locally outside the server")
   points decisively at **standalone stdio client; remove the mount**.
1. **The loopback round-trip.** When served by the daemon, a tool serializes → HTTP →
   the daemon's own REST route → in-process RAG → deserializes. Pure overhead plus a
   deadlock hazard papered over by a 300s-timeout thread offload.
1. **Dual transports with opposite execution models.** The stdio entry point
   (`mcp.run(transport="stdio")`, `server/_main.py:154-157`) **eagerly loads the GPU
   model in-process** before serving, yet every tool body then delegates over HTTP to a
   *separate* daemon — so the stdio process pays the full model-load cost it never uses.
   The agent registration in `.mcp.json` (`uv run vaultspec-search-mcp`, no `--port`)
   takes exactly this stdio branch. This is the single worst regression: it directly
   violates "load no Torch, exhaust no resources."
1. **`mcp` as core dep vs optional adapter.** If the daemon mount is removed, `mcp` can
   become a stdio-client-only boundary; if kept, the "optional adapter" framing is
   permanently wrong.
1. **Readiness blindness.** On a cold server-first start the MCP calls `/search` with a
   blind 300s timeout and no readiness handshake against the new `GET /readiness` gate;
   it will hang or fail opaquely while the supervised Qdrant child provisions.

### 5. Target architecture (recommended for the ADR)

- **MCP is a standalone stdio client process.** Launched by the agent via `.mcp.json`,
  it serves MCP over stdio and never loads a model. Delete the in-process
  `_registry.load_model()` from the stdio branch.
- **Remove the daemon's `/mcp` Mount and the `_mcp_no_redirect` wrapper.** The daemon
  exposes native REST only; the MCP reaches it as an external client. This honors the
  deconflation ADR's intent for the first time and lets the loopback hazard, the 300s
  defensive timeout's rationale, and the readiness-blind mount disappear together.
- **Pin every tool to the CLI client layer.** Replace `_call_daemon` /
  `_call_daemon_async` with calls into `_try_http_search`, `_try_http_reindex`, and
  `_try_http_admin` (plus `_read_service_status` / `_default_service_port`), and delete
  the duplicate seam. Map the trinary `None` return to the clear "service not running"
  error so "dysfunctional when the server is down" is enforced at one place.
- **Sever the heavy transitive import.** The MCP must read service status and call the
  client layer without triggering `vaultspec_rag/__init__.py`'s top-level `.api` import.
  This likely means factoring the client functions (`_http_search.py`,
  `_service_status` discovery) so the MCP can import them without importing `api`/`store`
  /`search`/`embeddings`.
- **Resolve the two gaps**: give `get_code_file`, `benchmark`, and `quality` a client
  function or scope them out; fix or drop `get_index_status` (`/status` does not exist —
  it should be the admin `get_service_state` / `/service-state`).
- **Fix the phantom/stale artifacts**: remove the `mcp start` / `cli/_mcp_admin.py`
  references, correct the stale "server owns `mcp`" docstrings, and align the ecosystem
  test's documented command surface.

### 6. Test strategy (mock-free)

This project forbids mocks/patches/fakes/stubs/skips. Two regression tests lock the
invariants, both `@pytest.mark.unit`:

- **Runtime import isolation** — a fresh-interpreter subprocess (the exact technique in
  `test_chunk_worker_parity.py:199-212`, the `index-workers-stay-cpu-only` template):
  after `import vaultspec_rag.mcp`, assert `sys.modules` contains none of `torch`,
  `sentence_transformers`, `qdrant_client`, `transformers`, `onnxruntime`. The fresh
  interpreter is essential so a torch-loading test elsewhere in the session cannot mask a
  regression. Keep the existing AST guard and **extend its forbidden set to include
  `cli` and `api`** so the transitive heavy pull is caught statically too.
- **No-local-fallback** — using the `isolated_status_dir` fixture pattern
  (`test_service_lifecycle_helpers.py:28-43`, sets `VAULTSPEC_RAG_STATUS_DIR` to an empty
  tmp dir and calls `reset_config()`, per the service-test isolation rule), point at an
  empty status dir (no `service.json`) and assert each tool/resource raises
  `RuntimeError` matching `"daemon is not running"` around `asyncio.run(tool(...))` — the
  shape already proven at `test_server.py:618-635`. A subprocess variant additionally
  asserts `sys.modules` stays heavy-lib-free after the failed call. Non-tautological: it
  exercises the real status-file read and the real client path up to the missing-file
  guard, proving no local engine was built.

### 7. Open questions for the ADR

- **Mount removal blast radius.** Removing `Mount("/mcp")` retires the daemon's HTTP MCP
  endpoint. Confirm no consumer depends on the streamable-HTTP MCP surface (vs stdio);
  if one does, the ADR must keep an HTTP transport but route it to the client layer, not
  loopback.
- **`benchmark` / `quality` / `get_code_file`** — add thin client wrappers in
  `_http_search.py` (preferred, for CLI/MCP parity) or scope them out of the MCP.
- **Readiness handshake** — should the MCP probe `GET /readiness` before its first call,
  or surface the daemon's structured "not ready" error as-is? Lean toward surfacing the
  error (thin client), not adding handshake logic.
- **Import factoring** — decide where the client functions live so the MCP can import
  them without `vaultspec_rag/__init__.py`'s `.api` pull (a dedicated client subpackage
  vs leaving them in `cli` and making `cli` import-light).
