---
tags:
  - '#research'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
related: []
---

# `mcp-conformance` research: `MCP conformance: connection defect and CLI parity gap`

The `vaultspec-rag` MCP surface is installed in agent sessions and agents prefer it when
available, yet it has not been an exercised or tested surface for a long time. A live
session transcript showed an agent reach for MCP to search the project it was standing
in, get nothing usable, and fall back to raw CLI archaeology — a silent degradation with
high blast radius because every MCP-preferring session inherits it. This research
characterizes the breakage from live evidence and code, separating an architectural
connection/discovery defect from box-specific infrastructure confounds, and inventories
the full CLI-to-MCP coverage gap. It grounds a forthcoming ADR for an MCP conformance
epic whose two pillars are (1) make MCP reliably reach the correct running service and
(2) bring the MCP surface to tested parity with the CLI.

## Findings

### 1. The symptom (live transcript)

An agent issued MCP `get_service_state(project_root=…\main)`. The service reported *up*,
but with an unrelated `aeat` project loaded and `vault_count 0` for the caller's own
root; MCP `search_vault` consequently returned `status: missing`. To recover, the agent
abandoned MCP entirely and shelled out to the CLI: it first targeted the wrong port
(Qdrant's `8765`, yielding an opaque `Error: 404:` with an empty body), retried on the
service port `8766` where the CLI queued a job fine, then watched that job die mid-write
with `[WinError 10054]`. It ultimately answered from vault docs, git, and source
directly. The episode demonstrates the inversion the epic targets: MCP's *availability*
led the agent into a dead end before it fell back to first principles.

### 2. Root cause: service selection is STATUS_DIR-bound and frozen in the MCP process

Both the CLI and the MCP select *which* running service to talk to through one shared
helper, `_default_service_port()` in `serviceclient/_discovery.py`, which reads a
per-status-dir `service.json` (`_status_dir()` resolves to the config's `status_dir`:
the `VAULTSPEC_RAG_STATUS_DIR` override, else `~/.vaultspec-rag/`). The two surfaces part
ways on process lifetime:

- The **CLI** is short-lived, so it re-resolves config every invocation; and an explicit
  `--port` bypasses discovery entirely (`cli/_index.py` skips the `port is None` branch).
  This is why `vaultspec-rag index --port 8766` reached the working service directly.
- The **MCP** is a single long-lived `FastMCP` process with no project binding
  (`mcp/_mcp.py`). Every tool resolves the port via `_require_port()` in `mcp/_tools.py`,
  which calls the same `_default_service_port()` — but `config.get_config()` is a
  **cached singleton** (`config.py`, `_cached_config` frozen on first call). Whatever
  `VAULTSPEC_RAG_STATUS_DIR` / cwd the MCP was spawned under is therefore frozen for the
  entire process lifetime.

Consequently, an MCP spawned under the `aeat` project's status dir permanently reads
`aeat`'s `service.json`, selects `aeat`'s port, and talks to `aeat`'s daemon. The
daemon's `get_service_state_route` honours the passed `project_root` via `_resolve_root`
(HTTP mode requires a non-empty root and resolves it exactly), so the `aeat` daemon
faithfully answers `get_service_state(main)` against its own slots — having never indexed
`main`, it returns `vault_count 0` while its slot listing still shows `aeat`. That is the
reported symptom precisely.

**`project_root` never re-targets the service.** Across `mcp/_tools.py` and
`mcp/_admin_tools.py`, `project_root` is inserted only into the HTTP payload/query (e.g.
appended as `?project_root=…` by `_admin_url_with_root` in `serviceclient/_transport.py`)
to scope *which project the chosen daemon answers about* — never as an input to port
selection. Token mismatch is ruled out as the divergence axis: `_do_http_call` in
`serviceclient/_transport.py` auto-heals a 401 by fetching the live token from the target
port's ungated `/health` and retrying once, so it never lands the caller on a different
service; it simply re-authenticates against the *already-selected* port.

### 3. The machine-global discovery pointer is write-only

The recently added machine-global pointer (`machine_discovery_path()` in
`_machine_lock.py`, located at `qdrant-server/service.json` beside the machine lock,
deliberately status-dir-independent) was introduced precisely so a consumer that does not
share rag's status dir could find the one running machine service. Its **write half
shipped and its read half did not**: the daemon heartbeat writes it
(`server/_lifecycle.py`), but `read_machine_discovery()` has **zero production callers** —
`_default_service_port()` / `_require_port()` have no fallback to it. So a consumer whose
status dir lacks a `service.json` is told "service not running" even when the machine
pointer names a live service. The pointer thus neither causes the bug nor heals it; its
stated purpose is currently undelivered. It also records a **single** service
(pid/port/token), with no project-root list — it is single-global, last-writer-wins, not
multi-project-aware.

### 4. Live on-disk evidence (read-only, captured during research)

- `~/.vaultspec-rag/service.json` — **absent** now; under the default status dir this
  makes `_default_service_port()` return `None` → CLI reports `Server: stopped`,
  matching live `server status`.
- `~/.vaultspec-rag/qdrant-server/service.json` (machine pointer) — **present and
  orphaned**: pid `102308`, port `8766`, last heartbeat days stale, carrying a leaked
  `service_token: "test-token"` in the real managed dir. The clean-shutdown unlink never
  ran.
- `qdrant-server/service.lock` records pid `31104` — a *different* pid than the pointer's
  `102308`; `identity.json` records yet another set. The managed dir is littered with
  stale state from prior crashed or killed daemons.
- `local-only.json` contains `{"local_only": false}` — **server mode is configured on
  this box**, correcting an earlier assumption that it was running local-only.
- `server doctor` reports the service as `not_started` ("no discovery file") and `torch`
  as a **CPU-only build** (`cuda_available: false`).

### 5. CLI-to-MCP coverage parity gap

The CLI exposes **30 invocable verbs**; the MCP exposes **16 tools** plus one resource
(`vault://{doc_id}`) and one prompt (`analyze_feature`). The structural gaps, ranked by
impact on an MCP-preferring agent:

- **The dead-end is architectural.** MCP has no `server start`, no `server doctor`, and
  no way to index when the service is down: its `reindex_vault` / `reindex_codebase`
  tools require a live daemon, whereas CLI `index` builds locally in-process. An
  MCP-only agent that finds the service unreachable cannot start it, cannot diagnose why,
  and cannot bootstrap an index — it can only surface the "run `vaultspec-rag server start`" string and stop. This is the transcript's structural cause.
- **Duplicate tool, one route.** `get_index_status` and `get_service_state` both delegate
  to `/service-state` and return identical envelopes — a near-duplicate to reconcile.
- **Silent contract drift** between nominally-matched pairs: search `top_k` defaults to
  `5` on MCP vs `--max-results` `10` on the CLI (same query, different result count);
  `--structure` ↔ `node_type`, `server projects unload` ↔ `evict_project` (arg `project`
  ↔ `root`), and `server updates timing` (`--update-delay-ms` / `--repeat-update-delay-s`)
  ↔ `reconfigure_watcher` (`debounce_ms` / `cooldown_s`) are the same routes under
  divergent names/params.
- **MCP-only capabilities** with no CLI verb: `get_code_file` (fetch a source file by
  path) and the `vault://{doc_id}` resource (fetch a vault document by stem).
- **Aligned pairs** (no divergence found): `get_jobs`/`server jobs`,
  `get_logs`/`server logs`, `list_projects`/`server projects list`,
  `get_watcher_state`/`server updates status`, `start_watcher`/`stop_watcher`,
  `survey_storage`/`server storage survey`.
- **Intentionally CLI-only** (acceptable asymmetry, to be confirmed as policy in the
  ADR): `install` / `uninstall`, `clean`, the destructive `server storage delete/prune/migrate`, `server qdrant install/status/clean`, and `preprocess list/check/run-one`.

### 6. Infrastructure confounds, controlled for

Two box-specific failures are *not* the MCP architecture defect and must not be
"fixed" by papering over them: the server-mode Qdrant instability surfacing as
`[WinError 10054]` mid-index, and the current CPU-only `torch` build (no CUDA). Both
degrade the *backend*; the conformance requirement is that MCP behaves *correctly given*
its backend state — clear errors, accurate status, no silent dead end — not that the
backend never fails.

### 7. Fix space for the ADR (design tension)

Two non-exclusive directions emerge, in tension that the ADR must resolve:

- **Wire the read half of the machine-global pointer.** Have `_default_service_port()` /
  `_require_port()` fall back to `read_machine_discovery()` when the status-dir
  `service.json` is absent, delivering the pointer's stated purpose so a cross-status-dir
  consumer finds the one machine service.
- **Make service selection project-aware.** Let the caller's `project_root` (or the MCP's
  cwd) drive which status dir / port is chosen, rather than the frozen process singleton,
  since the daemon is already multi-tenant and `_resolve_root` already scopes correctly
  inside it.

These are in tension because the machine pointer is single-global (one service, one
port): under the true machine-singleton invariant there is exactly one daemon and
`project_root` scoping inside it suffices, so the bug reduces to *selection resolving to a
stale or foreign status-dir file instead of the live machine singleton*. The ADR must
decide whether conformance is built on the machine-singleton model (one daemon, fix
selection to find it) or on project-aware multi-daemon selection, and must additionally
cover: legible transport errors (no empty-body `404:`), an MCP-native readiness/recovery
path so an agent is not dead-ended when the service is down, stale managed-state hygiene
(the orphaned pointer and leaked `test-token`), reconciliation of the duplicate
`get_index_status`/`get_service_state` tools, the search default and name/param
divergences, and a standing CLI-to-MCP conformance test matrix so this surface stops
regressing untested.

### 8. Open item to fully close the root cause

The one fact unobservable from static analysis is the MCP process's effective
`VAULTSPEC_RAG_STATUS_DIR` and cwd at the failing call. The decisive confirmation: if the
MCP's status dir were the default `~/.vaultspec-rag/` with `service.json` absent (as
now), `_require_port()` would raise "service not running" — not "service up with aeat."
That it returned `aeat` means the MCP was spawned under an `aeat`-scoped status dir whose
`service.json` named the live `aeat` service. Capturing the MCP server process's
environment and that dir's `service.json` at failure time would confirm it directly.
