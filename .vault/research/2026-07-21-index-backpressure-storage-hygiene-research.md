---
tags:
  - '#research'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:34449bd6116a09c53b291a210f131850bb32f49938c3c4c9259a79ab99816ff4'
related: []
---

# `index-backpressure-storage-hygiene` research: `silent index wedge under qdrant write failure and unbounded shared-backend degradation`

Issue #242 (handover 2026-07-21): a 250,681-chunk codebase index sat for hours at
`step="embed + upsert chunks" completed=0` with the GPU at 100% while Qdrant rejected
every write with disk-full errors and crashed repeatedly (OS 1455/1450 thread-spawn
panics); no error surfaced in job progress, `server status`, or `server jobs`. The disk
was full because the single shared server backend had grown to 117.9 GB across 51
namespaces, 36 of them temp-dir roots minted by test/demo/harness runs that never tore
down. This research maps the write-path failure handling and the storage lifecycle gaps
with file:line evidence, to ground an ADR covering the six handover asks.

## Findings

### Write path (indexer, store, jobs)

- **W1 — two code-index write paths; the incident was the serial streaming one.** The
  full-rebuild pipeline (`_pipeline_chunk_and_embed`, phase `"chunk + embed"`,
  `src/vaultspec_rag/indexer/_codebase_indexer.py:900`) has a producer/consumer with
  bounded shutdown. Both incremental paths (`_codebase_indexer.py:1331-1339`,
  `:1509-1517`) call `_stream_encode_and_upsert_codebase` (phase
  `"embed + upsert chunks"`, `src/vaultspec_rag/indexer/_streaming.py:274`) — the exact
  incident step. A first index of an unindexed tree routes here (every file is "new").
- **W2 — progress advances only after a slice's upsert returns.** Per slice,
  `encode_and_upsert_code_slice` then `reporter.advance` (`_streaming.py:284,293` →
  `jobs.py:355-363`). Persistent `completed=0` proves slice-0's upsert never returned.
- **W3 — a raised upsert exception is NOT swallowed.** It propagates through the slice
  loop, is logged and re-raised (`_codebase_indexer.py:1190-1203`), and the background
  job wrapper records `record_finish(job_id, error=str(exc))` → phase `"error"`
  (`src/vaultspec_rag/jobs.py:479-481`, `:246-269`). A clean disk-full rejection would
  have failed the job fast; the hours-long wedge required the write never to raise.
- **W4 — the wedge mechanism (medium confidence on trigger, high on mechanics).** The
  store calls plain `client.upsert` with no retry (`src/vaultspec_rag/store.py:653`;
  qdrant-client 1.18.0 retries only in the unused `upload_points` helpers) and the
  client is constructed with no timeout (`store.py:202-205`), leaving httpx's 5 s
  default. What pins the GPU while never advancing is the encode-side
  `while True` CUDA-OOM retry loop (`src/vaultspec_rag/embeddings.py:510-527`, sparse
  ~`:626`): on `torch.cuda.OutOfMemoryError` it halves the batch and re-encodes,
  redrawing the sentence-transformers progress bar. Under system-commit exhaustion
  (the same full disk starving the Windows pagefile — the incident's OS 1455/1450),
  host/pinned allocations fail and encode thrashes indefinitely: GPU busy, bars
  advancing, `completed=0`, and the cleanly-failing upsert never reached.
- **W5 — no write-side error classification or timeout.** `upsert_code_chunks`
  (`store.py:622-657`) and `upsert_document_chunks` (`:581-620`) have no
  try/except, backoff, or timeout. `UnexpectedResponse`/`ResponseHandlingException`
  classification exists only in the search mixin
  (`src/vaultspec_rag/_store_search.py:274-304`).
- **W6 — jobs have no structured error taxonomy; existing mitigations are CLI-only.**
  Job failure reason is free-text `result` (`jobs.py:246-269`); no `error_kind` field.
  Disk-full is special-cased only in the CLI renderer
  (`src/vaultspec_rag/cli/_service_jobs.py:262-263`) and only for an already-failed
  job. A stale-progress banner (`no progress for <t>`, 300 s threshold,
  `cli/_service_jobs.py:45,245-253`) exists only in human `server jobs` output — not
  in `/jobs` JSON, `server status`, or `/health`, and never escalates a stalled job.
- **W7 — bounded abort scaffold exists only in the pipelined path.**
  `_shutdown_consumer` (timed sentinel put + `join(timeout)` vs 300 s,
  `_codebase_indexer.py:63-68,756-771`) and `_handle_pipeline_errors` (`:784-794`)
  implement producer-stop/queue-drain/bounded-join/raise. The serial streaming loop
  has none of this.
- **W8 — no free-disk preflight anywhere.** `shutil.disk_usage` appears only as a
  post-reclaim maintenance metric (`src/vaultspec_rag/server/_lifecycle.py:366-369`).
  Bulk index submission flows through `start_reindex_codebase`/`start_reindex_vault`
  (`jobs.py:430,372`) and `reindex_route` (`server/_routes.py:525`); the CLI delegates
  via `_try_http_reindex` (`cli/_index.py:505-521`). A pre-embed byte signal exists
  (`_plan_chunk_workers` already sums `p.stat().st_size`,
  `_codebase_indexer.py:478-484`); the storage dir to check is
  `cfg.qdrant_storage_dir` (`config.py:195,350`).

### Storage lifecycle (namespaces, backend hygiene)

- **S1 — namespace minting is not alias-proof.** `root_collection_prefix`
  (`src/vaultspec_rag/_store_models.py:53-55`) hashes
  `os.path.normcase(Path(root).resolve())` (blake2b-6). Verified by execution: a
  `\\?\`-prefixed alias survives `resolve()`+`normcase` differently
  (`c:windows` vs `c:\windows`) and mints a duplicate namespace. Single authority —
  also called from `store.py:175`, `storage_manifest.py:219,271,420` — so one fix
  propagates. The manifest `root` field stores `resolve()` without `normcase`
  (`storage_manifest.py:218`).
- **S2 — lifecycle machinery and its invariants.** Classification
  (`storage_survey.py:68-116`, `storage_manifest.py:288-328`):
  live/orphaned/unverifiable/unknown. Persisted grace clock `first_seen_orphaned`
  (`storage_manifest.py:331-395`): stamped once, preserved across observations,
  cleared by any live/unverifiable observation, survives restarts.
  `evaluate_reclaim` (`storage_ops.py:463-550`): orphaned-only, empty tier 24 h /
  data tier 168 h, archive-before-destroy (`archive_prefix:553-595` raises on any
  snapshot failure), per-cycle cap, canonical-prefix regex gate
  (`storage_ops.py:42,192-239`). Hourly in-daemon tick
  (`server/_lifecycle.py:309-424,513`). **A still-existing temp dir classifies
  `live` and survives forever — the core of #242's accumulation.** Any faster temp
  reclamation must extend the danglingness definition (e.g. TTL since last index
  activity) through the same persisted-clock discipline, which needs explicit ADR
  justification against `automated-destruction-requires-time-confirmed-danglingness`.
- **S3 — the ~2.1 GB empty-namespace cost comes from default collection config and
  eager creation.** `_ensure_collection` (`store.py:330-388`) passes only vector
  configs — no `wal_config`, `optimizers_config`, or on-disk options — so Qdrant
  defaults preallocate WAL + segments. Creation is eager: indexing ensures
  collections in the "prepare collection" phase before any upsert
  (`_codebase_indexer.py:1081,1087`; `_vault_indexer.py:747,752`), so a zero-chunk
  temp root still pays the full cost. Verified against installed qdrant-client
  1.18.0: `create_collection` accepts `wal_config=WalConfigDiff(wal_capacity_mb=…)`
  and `optimizers_config=OptimizersConfigDiff(default_segment_number=…)` — the
  levers for shrinking preallocation. The `clean=True` drop-and-recreate purge
  (`_codebase_indexer.py:1078-1085`) relies on eager ensure.
- **S4 — no temp-root awareness exists.** No production classification of temp
  roots (`tempfile.gettempdir` appears only in a quality-check scratch path,
  `api.py:719-728`). The incident's temp namespaces came from external harness/demo
  runs against the real machine service; the repo's own integration suite isolates
  correctly via `_service_env`. The single choke point for flagging temp roots at
  registration is `record_root`/`_record_manifest` (`store.py:437-467`,
  `storage_manifest.py:199-219`). The sanctioned idempotent teardown verb already
  ships: `server storage delete --root <path> --json` exits 0 on
  `no_such_namespace` (`storage_ops.py:225-226`).
- **S5 — crash debris is invisible.** `gather_survey` (`storage_ops.py:165-189`)
  enumerates namespaces only from `client.get_collections()`; a config-less
  collection dir Qdrant skips at startup is never surveyed, never counted, never
  reclaimable. Detection is a cheap diff of `server_storage_collections_dir()`
  subdirs (`storage_ops.py:117-131`) against live collection names.
- **S6 — backend size observability is blind to exactly this incident.**
  Maintenance gauges exist (`_lifecycle.py:380-389`) but `dangling_bytes` counts
  only orphaned footprints (`storage_ops.py:812-814`) — the 117.9 GB pile of `live`
  temp namespaces never appeared in any metric. No total-backend-bytes,
  per-status byte rollup, or total-namespace-count gauge.

### Post-research developments (same day)

- **D1 — PR 245 merged to main (276312e)** while this pipeline was in flight:
  alias normalization in `root_collection_prefix` (strips `\\?\` and
  `\\?\UNC\` before resolve+normcase), a report-only `temp_rooted` flag on
  survey namespaces through `storage_survey.py`, the storage route, and both
  CLI emitters, plus harness-teardown docs in `docs/storage-maintenance.md`.
  Its commit message disputes ask 5's premise: the ~2.1 GB per leaked
  namespace was found to be real indexed content, not WAL preallocation.
  This conflicts with the 2026-07-14 autoprune ADR's measurement of ~2.1 GB
  for zero-point namespaces; the conflict must be settled empirically under
  the isolated harness before any collection-config tuning ships.
- **D2 — Defect 3 recorded on the issue** during recovery: a
  `pytest -m unit` run from a development worktree terminated the shared
  machine-global service mid-job (`event=shutdown reason=cli_terminate`
  with pytest initiator attribution), killing two in-flight index jobs
  which then vanished from `server jobs` after restart — the in-memory jobs
  ring has no persistence, so daemon death erases the evidence. The
  isolation rule exists but nothing enforces it structurally. A ~10x
  index slowdown under concurrent multi-tenant load was also observed and
  is noted as out of scope (performance, not correctness).

### Test surfaces and conventions

- **T1** — indexer/pipeline: `tests/integration/test_gpu_pipeline_integration.py`,
  `test_indexer_progress_integration.py`, `test_indexer_integration.py`,
  `tests/test_indexer_unit.py`. Store/server mode:
  `tests/integration/test_store_integration.py`, `test_qdrant_server_mode.py`,
  `tests/test_server_routes.py`. Jobs: `tests/integration/test_service_jobs.py`,
  `test_jobs_registry.py`. ADR guards: `tests/test_adr_regression.py`
  (lifecycle-inertness import-graph test at `:429-486`).
- **T2** — isolation: every storage/service test sets both
  `VAULTSPEC_RAG_STATUS_DIR` and `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to tmp and
  calls `reset_config()`; server-mode integration relocates port + storage via
  `_service_env`.

## Constraints that bind the design

- `automated-destruction-requires-time-confirmed-danglingness` — no immediate
  deletion of temp-rooted namespaces; any faster reclamation is a shorter grace
  tier over a persisted clock, and extending danglingness beyond "root missing"
  needs its own justification.
- `storage-maintenance-is-lifecycle-inert` — new hygiene code stays inside the
  regression-tested import graph; no CLI lifecycle imports.
- `gpu-consumer-single-thread` / `gpu-lock-wraps-forward-passes-only` — fail-fast
  abort reuses the bounded consumer shutdown; preflight, classification, timeouts,
  and watchdogs run outside `gpu_lock`.
- `service-domain-owns-operability` — preflight, stall detection, error taxonomy,
  and storage banners live in the service domain (`jobs.py`, routes, survey);
  CLI/MCP/HTTP adapt. HTTP stays read-only.
- `broker-facing-cli-outcomes-are-structured-and-idempotent` — preflight refusal
  and job failure are single structured non-zero envelopes with remediation.
- `managed-singleton-paths-isolate-storage-dir-in-tests` — all new tests isolate
  both env dirs.

## Where each handover ask lands

- **Ask 1 (fail loudly):** raised upserts already fail the job (W3); the real gaps
  are the stalled-never-raises wedge (W4), no client timeout (W5), no encode-retry
  ceiling (W4), and no bounded abort in the serial path (W7).
- **Ask 2 (surface storage errors):** structured `error_kind` on jobs + service-domain
  stall/storage banners in `/jobs`, `server status`, `/health` (W6).
- **Ask 3 (free-disk preflight):** at job submission (`start_reindex_*`,
  `reindex_route`) using `shutil.disk_usage(cfg.qdrant_storage_dir)` vs the scan's
  byte estimate (W8).
- **Ask 4 (namespace lifecycle):** path-normalize before hashing (S1), flag temp
  roots at registration (S4), TTL-tier reclamation through the grace discipline
  (S2), harness teardown via the shipped `storage delete --root` (S4).
- **Ask 5 (empty-namespace cost):** `wal_config`/`optimizers_config` at creation
  and/or lazy creation on first upsert (S3).
- **Ask 6 (startup hygiene):** disk-vs-collections diff in survey; report and make
  debris reclaimable (S5).

## Sources

- Evidence cited inline: `src/vaultspec_rag/indexer/_codebase_indexer.py`, `src/vaultspec_rag/indexer/_streaming.py`.
