---
tags:
  - '#research'
  - '#operability-hardening'
date: '2026-06-09'
related: []
---

# `operability-hardening` research: `service, runtime, and UX hardening`

Post-deconflation hardening of the RAG service. Scope is every deferred, delayed, and
new issue outstanding after the MCP/RAG-service deconflation landed on `main`: service
lifecycle/management (#181, #166), runtime/environment/compatibility bugs (#176, #177,
#178/#179, #180), and CLI UX + documentation (#170, #171, #172). Three parallel
code-grounded research passes were run against `main` at the feature base commit.

**Headline:** the service-management cluster (#181/#166), previously assumed to need an
architectural redesign, decomposes into seven targeted, localized fixes — none touch the
GPU pipeline, search path, embedding stack, or indexer worker rules. The umbrella is
tractable as bounded fixes plus two doc/test efforts.

## Findings

### Cluster A — Service lifecycle & management (#181, #166)

- **A1 — orphan daemon invisible to `status`/`stop`.** `cli/_service_status.py`
  `_read_service_status()` returns `None` when `service.json` is absent, and both
  `service_status` and `service_stop` in `cli/_service_lifecycle.py` early-return
  ("stopped" / "not running") with no port probe — so a live daemon with a missing
  `service.json` cannot be observed or vacated. Fix: add a `_health_probe` port-probe
  fallback; report an `orphaned` state (exit 4) and surface the port for manual reclaim.
- **A2 — `service start` exits 0 on busy port.** `cli/_service_lifecycle.py` prints
  "Port N is already in use" then returns normally (exit 0). Fix: `raise typer.Exit(1)`.
- **A3 — `service logs` always empty.** `cli/_http_search.py` routes `get_logs` to the
  plaintext `/logs` route, but `_do_http_call` always `json.loads` the body → decode
  error swallowed → `{}` → "No log lines available". Fix: route to the existing
  `/logs/json` endpoint (already returns `{"lines": [...]}`).
- **A4 — unhandled `ValueError` → HTTP 500 on missing `project_root`.** `server/_utils.py`
  `_resolve_root(None)` → `_default_root()` raises `ValueError` in HTTP mode; routes in
  `server/_routes.py` (`/search`, `/reindex`, `/service-state`, `/code-file`,
  `/vault-document`) don't catch it. Fix: a distinct `ProjectRootRequiredError` caught
  uniformly → 400 with a clear message.
- **A5 — auto-delegation token race → 401.** `service.json` is written without
  `service_token` at spawn time; the daemon only writes the token on its first heartbeat
  (after multi-second model load), but the start health-poll returns as soon as `/health`
  is "ready". A CLI command that auto-delegates in that window sends no `Authorization`
  header → 401. Fix: have the start poll loop read `service_token` from `/health` and
  persist it into `service.json` before exiting; warn on 401 in `_do_http_call`.
- **A6 — Windows Job Object kills the daemon tree, orphaning the Qdrant lock.**
  `cli/_process.py` `_spawn_service` uses `CREATE_NEW_PROCESS_GROUP` but not
  `CREATE_BREAKAWAY_FROM_JOB`, so the detached daemon stays in the launching shell's Job
  Object and is killed on shell exit, leaving `exclusive.lock` held. Fix: add
  `CREATE_BREAKAWAY_FROM_JOB` (0x01000000) with an `OSError` fallback for restricted CI
  job objects.
- **A7 — redundant pre-delete in `store.py` `drop_table`/`drop_code_table`.** Both call
  `client.delete(points_selector=Filter())` (O(N), holds `_client_lock`) before
  `delete_collection()`, which drops the storage dir anyway. Fix: remove the pre-delete.

**Verdict:** all seven are targeted fixes, not a redesign. A2/A3/A7 are one/two-liners;
A4/A6 small; A1/A5 moderate (both extend the startup/poll path, no GPU/store risk).

### Cluster B — Runtime / environment / compatibility (#176, #177, #178/#179, #180)

- **B1 — wrong interpreter on detached spawn (#178/#179, duplicates).** `cli/_process.py`
  builds the daemon command with `sys.executable`, which can be the system Python 3.14
  when the CLI runs outside the uv venv. Fix: resolve the venv interpreter explicitly via
  `sysconfig.get_path("scripts")` with a `sys.executable` fallback. **Root cause of the
  cluster.** Recommend closing #179 as a duplicate of #178.
- **B2 — Py3.14 protobuf `TypeError` (#177).** `qdrant_client` import (via `protobuf`
  `google._upb._message`) fails under CPython 3.14's metaclass `tp_new` restriction. Not
  an app bug — resolved once B1 spawns the pinned 3.13 interpreter. Add a defensive
  `sys.version_info` guard in `store.py` `_check_rag_deps()` for an actionable error.
- **B3 — gated HF model silent crash (#176).** `embeddings.py` constructs
  `SentenceTransformer`/`SparseEncoder`; a gated repo (e.g. `naver/splade-v3`) raises
  `huggingface_hub.errors.GatedRepoError` (401) that propagates uncaught and kills daemon
  startup with no remediation. Fix: wrap with a `RuntimeError` carrying `HF_TOKEN` /
  `huggingface-cli login` / model-URL guidance. Graceful degrade is infeasible (no
  CPU/sparse-only mode) — a clear fatal error is correct.
- **B4 — in-process reindex "EmbeddingModel not loaded" (#180).** `jobs.py` `_bg_run`
  closures call `get_registry().lease(root)` without a prior `load_model()`; on the
  in-process path (no service lifespan having run) `_create_slot` hits the
  `model`-property guard. Fix: call the idempotent `get_registry().load_model()` at the
  top of both `_bg_run` closures (no-op on the service path).

**Recommended order:** B1 → B2 → B3 → B4. B1 is foundational (makes the service actually
run on Windows); the rest are independent at the code level.

### Cluster C — CLI UX & documentation (#170, #171, #172)

- **C1 — CLI help leaks developer docstrings (#170).** ~8–10 Typer commands
  (`handle_index`, `handle_search`, `handle_status`, `service_start`, `service_warmup`,
  `mcp_start`, the root `main` callback, `version_callback`) render `Args:`/`Raises:`/
  `ctx`/internal symbol names into `--help`. A clean pattern already exists (`handle_clean`,
  `service_logs`): short prose summary + per-option `help=`. Fix: strip the dev sections;
  optionally add `rich_help_panel` groupings. Small, mechanical.
- **C2 — indexing architecture docs gap (#172).** No user-facing guide. Technical content
  fully grounded: Qwen3-Embedding-0.6B (1024d fp16, asymmetric query prompt), SPLADE-v3
  (`encode_document`/`encode_query`), bge-reranker-v2-m3 (Sigmoid, OOM backoff), Qdrant
  hybrid `RrfQuery(Rrf(k=60))` with per-Prefetch filters, blake2b incremental hashing,
  spawn ProcessPool chunking + single GPU consumer thread, watcher auto-reindex. Author
  `docs/indexing.md` and cross-reference from `index`/`clean`/`status`/`warmup` help.
- **C3 — testimonial-driven CLI testing (#171).** Real (no-mock) operator-persona
  integration test: personas ("first-time indexer", "search power user", "service
  operator") run scripted CLI sequences against a live workspace/service, capturing
  exit codes + friction notes, asserting no leaked internals in help/output. Depends on
  C1 (clean baseline) and the Cluster-A service fixes (so it tests intended behavior).

**Order:** C1 → C2 → C3.

### Cross-cutting ordering and dependencies

- **Foundational first:** B1 (venv interpreter) unblocks B2 and makes the Windows daemon
  actually run — prerequisite for any live-service validation.
- **Then service correctness:** Cluster A fixes (A1–A7), independent of each other; A6
  (Job Object) pairs naturally with B1 in the spawn path.
- **Error-quality pair:** B3 before B4 (so a gated-model failure surfaces a useful message
  rather than the "not loaded" sentinel).
- **UX/docs last:** C1 → C2 → C3, with C3 gated on A-cluster + C1 landing.

### Open item (tooling)

The `gh` token lapsed during this session; findings use issue contents captured earlier
plus live code grounding. On re-auth: reconcile against the live board, close the merged
deconflation issues (#167/#168/#169) and dedupe #179→#178, and confirm no new issues
landed.
