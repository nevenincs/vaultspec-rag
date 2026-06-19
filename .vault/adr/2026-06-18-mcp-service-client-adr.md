---
tags:
  - "#adr"
  - "#mcp-service-client"
date: '2026-06-18'
related:
  - "[[2026-06-18-mcp-service-client-research]]"
supersedes:
  - '2026-03-07-mcp-sync-tools-adr'
  - '2026-05-31-server-mcp-route-adr'
  - '2026-06-05-cli-mcp-decoupling-adr'
  - '2026-06-07-mcp-server-deconflation-adr'
  - '2026-06-10-install-mcp-dependency-fix-adr'
modified: '2026-06-18'
---

# `mcp-service-client` adr: `MCP backend reframed as a thin service client` | (**status:** `accepted`)

## Problem Statement

The resident service backend is the only production-ready path: one supervised daemon
owns the GPU models and the Qdrant server, and many clients issue concurrent
search/index requests against it without exhausting local resources. The MCP surface has
regressed in the opposite direction. Across five prior MCP decisions it inverted from
*being* the daemon to *consuming* it, but the inversion was never finished: the MCP app
is still mounted inside the daemon, the stdio entry point still loads the GPU model
in-process, several tools are dead or point at routes that do not exist, and the package
re-implements a wire client the CLI already owns. The net result is an MCP that loads
heavy resources it never uses, can deadlock the daemon it is served by, and contradicts
its own "consumer client" framing.

This ADR reframes the MCP server as a **thin service client and nothing more**, and
explicitly supersedes all five prior MCP ADRs whose accreted decisions produced the
regression. It is grounded in the research at `[[2026-06-18-mcp-service-client-research]]`
and tracks issue #194 / PR #195.

## Considerations

The decisive grounding from research:

- The CLI **already owns** the exact thin-client layer the MCP needs:
  `cli/_http_search.py` exposes `_try_http_search`, `_try_http_reindex`, and
  `_try_http_admin` over the wire primitive `_do_http_call`, with service discovery
  (`_read_service_status`, `_default_service_port`) in `cli/_service_status.py`. That
  layer imports only stdlib plus a lightweight filter validator — no Torch, no models, no
  store. This is the "CLI → service is the only proven production path."
- The current MCP carries a byte-for-byte **duplicate** of that wire client
  (`_call_daemon` / `_call_daemon_async` in `mcp/_tools.py`).
- The stdio MCP branch in `server/_main.py` eagerly loads the GPU model in-process, and
  the agent registration in `.mcp.json` (no `--port`) takes exactly that branch — the
  single worst regression against "load no Torch."
- The daemon still mounts the MCP app at `/mcp` behind a no-redirect ASGI wrapper, so a
  served tool issues an HTTP request to its own daemon (a loopback the codebase papers
  over with a 300s thread-offload timeout), and the MCP is blind to the new server-first
  readiness gate.
- Transport is not ours to invent. The MCP spec (revision 2025-11-25) defines stdio and
  Streamable HTTP, states clients SHOULD prefer stdio, and deprecated only the older
  HTTP+SSE transport — never stdio. Every major coding agent (Claude Code, Cursor, Codex,
  VS Code) defaults to stdio for local single-machine servers and reserves Streamable
  HTTP for remote/hosted ones. A local RAG service is, by every agent's framing, the
  stdio case.
- Dead/phantom surface: `get_index_status` targets a non-existent `/status` route; a
  phantom `mcp start` command and `cli/_mcp_admin.py` module are referenced but do not
  exist; "server owns `mcp`" docstrings describe a pre-split reality.

## Constraints

- **No mocks/fakes/skips.** Project test mandate: every invariant is proven against real
  behavior (real empty status dir, real subprocess import). The verification design must
  honor this.
- **Import isolation is load-bearing.** Importing `vaultspec_rag.mcp` today transitively
  pulls `api`/`store`/`search`/`embeddings` because `vaultspec_rag/__init__.py` imports
  `.api` at module top and `mcp/_tools.py` imports from `..cli`. Severing this requires
  the client functions to be importable without triggering that top-level `.api` import —
  a real factoring constraint, not a cosmetic one.
- **`mcp` core dependency stays.** The daemon imports `mcp` unconditionally; the prior
  install-fix ADR's promotion of `mcp` to a core dependency remains correct and is
  carried forward (this ADR supersedes that ADR's *framing*, not its dependency fact).
- **Parent stability.** This ADR builds on the shipped server-first default backend
  (supervised Qdrant + readiness gate) and the existing CLI client layer; both are
  stable and in production. No frontier risk.
- **Backward compatibility is explicitly NOT a goal.** Consistent with the deconflation
  ADR's "hard, clean cut" intent that was never honored: no shims, shadows, or dual-mode
  fallbacks survive this rework.

## Implementation

High-level shape (the plan phase details steps):

- **D1 — MCP is a thin service client only.** Every tool delegates to the running daemon
  through the CLI client layer and does nothing else. It loads no Torch/models, acquires
  no lock, opens no store, and holds no local resource. When the daemon is unreachable it
  raises a single clear "service not running" error; there is no local fallback. The MCP
  is intentionally dysfunctional when the server is down.
- **D2 — stdio is the transport.** On industry-norm grounds, stdio is the primary,
  agent-facing transport. The daemon's in-process Streamable-HTTP `Mount("/mcp")` and the
  `_mcp_no_redirect` wrapper are **removed**, which eliminates the loopback and the
  readiness-blindness in one cut. stdio-only is the recommended default; a Streamable-HTTP
  endpoint returns only as a deliberate future opt-in if a networked-client requirement
  appears (none exists today).
- **D3 — pin to the CLI client functions.** Every MCP tool calls
  `_try_http_search` / `_try_http_reindex` / `_try_http_admin` (plus the
  `_service_status` discovery helpers); the duplicate `_call_daemon` / `_call_daemon_async`
  seam is deleted. The trinary `None`-return → "service not running" mapping lives in one
  place.
- **D4 — no bespoke MCP commands.** All business logic lives in the backend libraries; the
  MCP defines no behavior of its own. `benchmark`, `quality`, and `get_code_file` — which
  lack a CLI client function today — gain a thin **client** wrapper in the shared client
  layer so the CLI and MCP consume one surface. (The ADR confirms wrappers over
  scoping-out: a shared client surface is the durable expression of "no bespoke MCP
  commands.")
- **D5 — strip the heavy load.** The in-process GPU model load is removed from the stdio
  branch of `server/_main.py`. The client functions are factored (a dedicated import-light
  client module/subpackage is the likely shape) so importing `vaultspec_rag.mcp` does not
  trigger the `vaultspec_rag/__init__.py` → `.api` chain that pulls
  `store`/`search`/`embeddings`.
- **D6 — remove dead/phantom artifacts.** Route `get_index_status` to the live
  `/service-state` (the daemon has no `/status`); delete the phantom `mcp start` /
  `cli/_mcp_admin.py` references and the stale "server owns `mcp`" docstrings; align the
  ecosystem test's documented command surface with what the CLI actually ships.
- **D7 — verification.** A fresh-interpreter subprocess test asserts `sys.modules`
  contains none of `torch`, `sentence_transformers`, `qdrant_client`, `transformers`,
  `onnxruntime` after `import vaultspec_rag.mcp`. A no-local-fallback test uses an isolated
  empty status dir (`VAULTSPEC_RAG_STATUS_DIR`) and asserts each tool/resource raises
  `RuntimeError` matching "daemon is not running". The existing AST isolation guard's
  forbidden set is extended to include `cli` and `api` so the transitive heavy pull is
  also caught statically.

## Rationale

The research showed the rework is mostly *collapse and delete*, not build: the
production-proven client already exists in the CLI, and the MCP's job is simply to wrap
it in an MCP shell. Pinning to that one client layer removes the duplicate, removes the
in-process engine, and makes "thin client, dysfunctional when the server is down" the
structural default rather than an aspiration. The transport decision is taken on
documented industry norms (the MCP spec's stdio-preference plus uniform local-server
stdio defaults across coding agents), not on local preference — which is exactly the
basis the decision should rest on. Removing the daemon mount honors, for the first time,
the "hard clean cut to a consumer client" that the deconflation ADR declared but never
delivered.

## Consequences

- **Gains:** the MCP stops loading Torch and the GPU model it never uses; the loopback
  deadlock hazard and its 300s defensive timeout disappear; one client surface serves both
  CLI and MCP, so they cannot drift; the import chain becomes genuinely thin; dead tools
  and phantom references are gone. The agent integration matches industry-default stdio
  config with no special-casing.
- **Costs / difficulties:** the import factoring (D5) is the real work — severing the
  top-level `.api` import without breaking the CLI's own imports needs care, and may mean a
  new import-light client module. Adding client wrappers for `benchmark`/`quality`/
  `get_code_file` (D4) is small but touches the shared client layer. Removing the `/mcp`
  mount (D2) retires the daemon's HTTP MCP endpoint — acceptable because no consumer uses
  it, but it is a deliberate surface removal to call out in review.
- **Pitfalls:** the no-fallback contract must be enforced at exactly one place or it will
  rot; the import-isolation tests are the guardrail and must run in a fresh interpreter to
  be meaningful. The stdio shim spawns one process per agent — fine, because each is a
  trivial forwarder to the singleton daemon, not a duplicate service.
- **Supersession:** this ADR deprecates `[[2026-03-07-mcp-sync-tools-adr]]`,
  `[[2026-05-31-server-mcp-route-adr]]`, `[[2026-06-05-cli-mcp-decoupling-adr]]`,
  `[[2026-06-07-mcp-server-deconflation-adr]]`, and `[[2026-06-10-install-mcp-dependency-fix-adr]]`.
  The async-tool offload (sync-tools ADR) and the `mcp`-is-a-core-dependency fact
  (install-fix ADR) are carried forward as facts; their surrounding framing is replaced.

## Codification candidates

- **Rule slug:** `mcp-is-a-thin-service-client`.
  **Rule:** The MCP server must delegate every tool to the shared service-client layer,
  load no Torch/models, acquire no lock, hold no local resource, and raise a clear
  "service not running" error when the daemon is down — never a local fallback.

- **Rule slug:** `interface-layers-share-one-client`.
  **Rule:** CLI and MCP must consume one shared service-client surface; neither may carry
  bespoke business logic or a duplicate wire client — all behavior lives in the backend
  libraries.
