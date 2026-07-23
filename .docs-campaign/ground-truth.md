# vaultspec-rag ground truth (server-first-default branch)

Authoritative, CODE-VERIFIED current state for the documentation rewrite. Every
claim is either cited to `src/...:line`/`src/...` or based on a live
`--help` extraction run against the working-tree module entry point. Where
something is scaffolded-but-not-fully-wired it is flagged explicitly. Do not
carry over old behavior; trust this file.

Verified against the working tree at commit `5b6ecd34` (package version
`0.3.3`) on 2026-07-23. This is a full refresh of the prior 2026-06-13 /
v0.2.20 version of this file — nearly every section below has drifted since
then; see the "Refresh notes" callouts. CLI facts in Sections 2/4/8/9/14 were
re-verified by RUNNING `.venv\Scripts\python.exe -m vaultspec_rag ... --help`
recursively against the working-tree module (NOT the `vaultspec-rag` binary,
which resolves to a stale global install). Sections not explicitly flagged as
re-verified (3, 5 partial, 6, 7, 13, 15) were left as the 2026-06-13 version
recorded them and should be spot-checked before being treated as current.

---

## 1. Package version and entry points

- **Version: `0.3.3`** — `pyproject.toml:61` (`version = "0.3.3"`). (Was
  `0.2.20` in the prior version of this file.)
- Build backend: hatchling. Python `>=3.13` (`requires-python = ">=3.13"`).
- Console scripts unchanged in shape: `vaultspec-rag` (Typer CLI),
  `vaultspec-search-mcp` (MCP/HTTP daemon entry). `python -m vaultspec_rag`
  runs the CLI; `python -m vaultspec_rag.server [--port N]` runs the daemon
  (HTTP with `--port`, stdio MCP without).
- Not re-verified this pass: exact runtime dependency list. Known-current
  MCP-optionality change (Section 4): the mcp dependency is now enrolled by
  the `install` front door and skippable via `--no-mcp`, rather than an
  always-core dependency — reconfirm the pyproject dependency declaration
  before documenting this as a hard requirement.

---

## 2. Complete CLI command tree

**Refresh notes:** `benchmark` and `quality` top-level commands from the
prior version of this file are **GONE** — no `@app.command` registers them
anywhere in `src/vaultspec_rag/cli/`. Three entirely new `server` subgroups
exist: `job` (singular, per-job control), `storage` (namespace lifecycle),
and a new flat `reconcile` command. `preprocess` gained a `status` verb.
Every domain-scoped command (`search`, `index`, `clean`) grew a fourth
domain, `document`, plus a `combined`/`all` union — the "extracted document"
index domain is new since the prior version of this file.

Root app: `app` in `cli/_app.py`. Help: "VaultSpec RAG: search project
documentation and source code."

**Group nesting** (`cli/_app.py`, live-verified):
- `app` → `server` (`server_root_app`)
- `server` → `job` (`server_job_app`) — **NEW**
- `server` → `projects` (`server_projects_app`)
- `server` → `updates` (`server_watcher_app`)
- `server` → `qdrant` (`server_qdrant_app`)
- `server` → `storage` (`server_storage_app`) — **NEW**
- `app` → `preprocess` (`preprocess_app`)

There is still **NO `server service` layer** — lifecycle/jobs/logs verbs live
directly under `server`.

### Root callback global options

Unchanged in shape from the prior version of this file: `--target/-t`,
`--verbose/-v`, `--debug/-d`, `--data-dir`, `--storage-dir`, `--status-dir`,
`--log-file`, `--version/-V`.

### Top-level commands (live-verified)

| Command | Purpose |
|---|---|
| `index` | Build/update the vault, code, and extracted-document search indexes |
| `clean <vault\|code\|document\|combined\|docs\|codebase\|all>` | Delete selected index data without rebuilding |
| `search <query>` | Search project documents, source code, or extracted documents |
| `status` | Project index counts, data location, compute device |
| `install` | Enroll workspace + provision deps |
| `uninstall` | Remove enrollment |
| `test [PYTEST_ARGS...]` | Run pytest over the test tree |
| `server` | Manage the background search service |
| `preprocess` | Inspect and validate document preprocessing rules |

**REMOVED vs the prior version of this file:** `benchmark`, `quality` are no
longer top-level commands. (The MCP surface also dropped its `benchmark()`
and `quality()` tools — see Section 14.)

### `server` group — 13 subcommands (live-verified, was 7 flat + 3 groups)

| Command | Purpose |
|---|---|
| `server start` | Start the background search service |
| `server stop` | Stop the background search service |
| `server status` | Human operator summary for readiness/work/next checks |
| `server warmup` | Download GPU model files before they are needed |
| `server doctor` | Readiness across two axes: installed deps AND live service health |
| `server jobs` | Recent index update activity, with filters |
| `server logs` | Grouped raw service/Qdrant logs, live or offline |
| `server reconcile` | **NEW.** Wait for the service to republish discovery records (non-destructive) |
| `server job` | **NEW group.** Inspect and control one exact service job |
| `server projects` | Inspect and unload loaded project slots |
| `server updates` | Inspect and control automatic index updates |
| `server qdrant` | Install and inspect the managed Qdrant server |
| `server storage` | **NEW group.** Survey and reclaim per-root RAG index storage |

### `server start` flags (live-verified)

- `--port INT` (env `VAULTSPEC_RAG_PORT`, default 8766).
- `--updates / --no-updates` (auto index updates, default enabled).
- `--update-delay-ms INT`, `--repeat-update-delay-s FLOAT`.
- `--local-only` — on-disk store, skip the Qdrant child.
- `--qdrant / --no-qdrant` — explicit server-mode opt in/out (redundant with
  the default; unset leaves current setting).
- `--qdrant-auto-provision` — download managed Qdrant if missing.
- `--no-preprocess` — **NEW.** Kill switch: the service loads no
  document-preprocessing rules for any root (forwards
  `VAULTSPEC_RAG_PREPROCESS=off`).
- `--json` — **NEW.** One machine-readable outcome envelope; an
  already-running owned service is the success `already_running` (exit 0),
  so a supervising broker attaches instead of treating it as a fault. See
  Section 11 for the full envelope contract.

### `server stop` flags (live-verified)

- `--port INT` — resolves identity from `/health` rather than the status
  file.
- `--json` — **NEW.** `already_stopped` is a success (exit 0);
  `identity_unconfirmed` (a stop that leaves the service running) is a
  failure (exit 1) in **both** output modes.

### `server status` flags (live-verified)

- `--port INT`, `--json`, `--verbose`.
- **NEW 5th exit code**: preserves 0 (running), 3 (stopped), 4 (crashed or
  divergent), and now **5 (warming: models loading, not yet serving)**. See
  Section 12.

### `server jobs` flags (live-verified)

- `--limit INT` (default 20), `--state`, `--index`, `--started-by`,
  `-q/--query`, `--failed`, `--job-id`, `--since FLOAT`, `--port`, `--json`.
- **NEW**: `--watch` (continuously refresh the human view), `--interval
  FLOAT` (default 2.0), `--refresh-count INT`.

### `server job` (singular) — ENTIRELY NEW group, per-job control

| Command | Purpose |
|---|---|
| `server job show <job_id>` | Show one exact job resource; human mode accepts a unique id prefix |
| `server job pause <job_id>` | Request a cooperative pause for one job |
| `server job resume <job_id>` | Resume one paused job through reconciliation |
| `server job stop <job_id>` | Request cancellation without disabling automatic updates |
| `server job retry <job_id>` | Create a linked retry for one retryable terminal job |
| `server job delete <job_id>` | Delete one terminal job from retained history |

All take `--port`/`--json`.

### `server logs` flags (live-verified)

- `--limit INT` (default 200), `--job-id`, `--contains`, `--port`, `--json`.
- **NEW**: `--source service|qdrant|all` (default `all`) — grouped log
  source selection; ground-truth prior version had no source grouping.

### `server reconcile` — ENTIRELY NEW command

Non-destructive: waits for the running service to republish its discovery
records. Nothing is written, deleted, stopped, or restarted. `--timeout
FLOAT` (default 35.0), `--json`. Exit 0 once discovery converges, 1 if it
does not converge in time.

### `server projects`

Unchanged: `list`, `unload <project>`.

### `server updates` (formerly watcher)

Unchanged: `status`, `start <project>`, `stop <project>`, `timing <project>`
(`--update-delay-ms`, `--repeat-update-delay-s`, `--port`, `--json`).

### `server qdrant` — drift

| Command | Purpose |
|---|---|
| `server qdrant install` | Download + verify the managed Qdrant server |
| `server qdrant status` | Executable/address/connection/process |
| `server qdrant clean` | Delete managed Qdrant installs |
| `server qdrant quarantine` | **NEW.** Move a corrupt collection out of the shared store |

### `server storage` — ENTIRELY NEW group (per-root namespace lifecycle)

| Command | Purpose |
|---|---|
| `server storage survey` | List stored RAG namespaces classified as live, orphaned, or unknown |
| `server storage delete` | Delete one named RAG namespace, addressed by its `r{hash}_` prefix |
| `server storage prune` | Reclaim every orphaned RAG namespace (source root gone) |
| `server storage reconcile` | Shrink existing collections to the bounded segment geometry (non-destructive) |
| `server storage migrate` | Migrate a root's index between local and server backends |

This whole group backs the storage-autoprune/geometry-reconcile feature
(Section 10 env vars) — entirely undocumented against the prior version of
this file. Exact per-command flags not yet extracted this pass; pull with
`server storage <cmd> --help` before writing `docs/backends.md` /
`docs/service-mode.md` content on this group.

### `preprocess` — drift

| Command | Purpose |
|---|---|
| `preprocess list` | Show resolved preprocess rules |
| `preprocess check` | Validate `.vaultragpreprocess.toml` |
| `preprocess run-one <path>` | Trial-run the matching rule on one file |
| `preprocess status` | **NEW.** Report the preprocess mode, config presence, and rule count |

### Removed/renamed vs the old "server service" CLI — see Section 16.

---

## 3. Server-first default model

Not re-verified line-for-line this pass; spot-checked and still consistent
with live `--help` output (`--local-only`/`--qdrant`/`--qdrant-auto-provision`
flags on `server start` match). Treat the detailed `config.py:NNN` line
citations in the pre-2026-07-23 version of this section as approximate —
several config.py line numbers have shifted given the file grew substantially
(see Section 10). The narrative (qdrant_server default True, local_only
default False, effective_server_mode = qdrant_server and not local_only,
local-only always wins) is confirmed still current via Section 10's defaults
extraction.

---

## 4. `install` provisioning front door

**Refresh notes — substantial drift.** Two new flags and one REVERSED
decision since the prior version of this file:
- **NEW `--mode tool|dependency|dev`** — provisioning mode, auto-detected
  from `pyproject.toml` when omitted (`tool` = launched via uvx; `dependency`
  = a runtime project dependency resolved through the project's own venv,
  ships in built distributions; `dev` = the default dev dependency group,
  renders like dependency but does not ship in built distributions).
- **NEW `--torch-group TEXT`** — places the managed CUDA torch
  direct-dependency under the PEP 735 `[dependency-groups].NAME` surface
  instead of `[project].dependencies`, so a dev-only consumer does not leak
  torch into published requirements. Defaults the group name to `dev` when
  passed without a value. Omit entirely to keep the historic
  `[project].dependencies` placement. The group must be enabled for the
  resolve (`uv sync --group NAME`) for the cu130 pin to apply.
- **REVERSED: `--mcp / --no-mcp`** — the prior version of this file stated
  "the `[mcp]` extra is a deprecated no-op alias (mcp is now a core dep)".
  That has been walked back: MCP is optional again. `install` enrolls the
  agent-facing MCP search surface and reconciles its optional dependency by
  default; `--no-mcp` sets up a CLI-only workspace without the mcp
  dependency (and, on Windows, without pywin32).

### Full current install flag list (live-verified)

- `-t/--target PATH` (default cwd).
- `--upgrade`, `--dry-run`, `--force` (bypasses torch-config prompt; implies
  `--yes` for that step; `--no-torch-config` still wins).
- `--skip TEXT` (repeatable).
- `--mode tool|dependency|dev` — **NEW**, see above.
- `--torch-config / --no-torch-config` (default on).
- `--torch-group TEXT` — **NEW**, see above.
- `-y/--yes` — skip the PyTorch config prompt (required for non-interactive
  installs unless `--no-torch-config`).
- `--sync` — run `uv sync --reinstall-package torch` after torch config.
- `--provision / --no-provision` (default on).
- `--mcp / --no-mcp` (default `mcp` = enrolled) — **REVERSED**, see above.
- `--local-only` — skips the Qdrant binary download, persists the local
  backend.
- `--skip-torch`, `--skip-models`, `--skip-qdrant`.
- `--json`.

### Wiring status

Prior version's "fully wired, no scaffolded-only stubs" note not
re-verified for the new `--mode`/`--torch-group`/`--mcp` flags this pass;
they are live and callable per `--help`, but internal report field coverage
(`InstallReport` shape) was not re-checked.

---

## 5. `server doctor` readiness verb

**Refresh note:** doctor's scope EXPANDED. Live `--help` text: "Report
readiness across two axes: installed dependencies (torch, models, qdrant
binary) and **the live service (a running daemon's health)**. A dead daemon
is reported as not ready." The prior version of this file documented
dependency-readiness only (torch/models/qdrant, all read-only/no live-daemon
check) — the live-service axis is new. Flags: `--json` only (per current
`--help`; the dimension internals — `_torch_readiness`/`_models_readiness`/
`_qdrant_readiness` — were not re-read this pass to confirm the exact
info-field shapes still match the prior version's citations).

---

## 6. `server qdrant` group

Not re-verified line-for-line this pass beyond the command list (Section 2),
which added `quarantine`. The pinned-version, verify-before-execute, and
air-gapped-escape-hatch narrative from the prior version of this file is
architectural and was not seen to have changed, but exact line citations
(`_resolve.py:NNN`, `_provision.py:NNN`) should be re-confirmed before
quoting them verbatim in docs.

---

## 7. Managed Qdrant server vs local mode (store layer)

Not re-verified this pass. Prior version's narrative (one supervised
loopback child, per-root namespacing via `root_collection_prefix()`,
backend-aware locking) is architectural and consistent with everything else
extracted this pass (e.g. the `server storage` group operates on namespaced
`r{hash}_` prefixes, confirming the namespacing scheme is still current).

---

## 8. Search output and flags

**Refresh notes:** `search --type` gained a 4th domain, `document`, plus a
`combined` union — mirrors the MCP `search_documents`/`search_combined`
tools (Section 14). Rendering/location/text-body behavior not re-verified
this pass (no reason to suspect drift; the flags below were captured from a
live `--help` run).

### search flags (live-verified, `.venv\Scripts\python.exe -m vaultspec_rag search --help`)

- `--type vault|code|document|combined` (default `vault`). Aliases: `docs`,
  `codebase`, `all`.
- `--max-results, --limit INT` (default 10).
- `--language`, `--path`, `--include-path` (repeatable glob),
  `--exclude-path` (repeatable glob), `--dedup-locales/--no-dedup-locales`,
  `--prefer <production|tests|documentation>`, `--structure`,
  `--function-name`, `--class-name` (code filters).
- `--doc-type`, `--feature`, `--date`, `--tag` (vault filters).
- **NEW document filters**: `--source-path`, `--extractor-id`,
  `--extractor-version`, `--locator-kind`.
- `--scores`, `--port`, `--allow-fallback`, `--verbose`, `--json`.
- `--timeout FLOAT` (default 300s, env `VAULTSPEC_RAG_SEARCH_TIMEOUT`).

Routing/auto-detect-service behavior not re-verified this pass; no evidence
of drift.

---

## 9. `index` and `clean` command flags and behavior

**Refresh notes:** both commands gained the `document`/`combined` domain
(mirroring `search`), and `index` gained a `--no-preprocess` kill switch.

### `index` flags (live-verified)

- `--type <str>` — `vault|code|document|combined` (aliases `docs`,
  `codebase`, `all`), default `all`.
- `--model TEXT`, `--rebuild`, `--port INT`.
- `--dry-run` — code/document admission summary without indexing; valid for
  `--type code`, `document`, `combined`, or the default `all` alias.
- `--dry-run-limit INT` (default 50).
- `--exclude TEXT` (repeatable).
- `--allow-fallback`.
- `--no-preprocess` — **NEW.** In-process-only kill switch (forwards
  `VAULTSPEC_RAG_PREPROCESS=off`); a running service keeps the preprocess
  mode it was started with.
- `--verbose`, `--json`.

Exact validation-error codes (`rebuild_requires_explicit_type`,
`dry_run_requires_code`, etc.) not re-verified this pass; the prior version's
citations may need updating for the new document/combined domains (e.g. does
dry-run's "code-only" restriction still hold, or does it now cover
document/combined too? Current `--help` text says dry-run is valid for
"code, document, combined, or the default all alias" — this is a NARROWING
change from the prior version's "code-only" restriction; confirm before
documenting).

### `clean` flags (live-verified)

- Positional `clean_type` — `vault|code|document|combined/all` (required).
- `-y/--yes`, `--json` (requires `--yes`).
- Does not load models/GPU.

---

## 10. Full config / env var inventory

**Refresh notes — the biggest drift in this file.** The prior version listed
~35 env vars; the current `EnvVar` enum (`config.py`) has 60+. Whole feature
areas are net new since the prior version: storage autoprune, storage
geometry reconcile, index resource ceilings, job/store write-retry timeouts,
watcher retry/circuit-breaker policy, intent-aware vault ranking, code-search
noise-domain filtering, and the stdio watchdog kill switch.

| Config key | Env var | Type | Default | Controls / CLI flag |
|---|---|---|---|---|
| `qdrant_url` | `VAULTSPEC_RAG_QDRANT_URL` | str\|None | `None` | Remote/managed server URL |
| `qdrant_api_key` | `VAULTSPEC_RAG_QDRANT_API_KEY` | str\|None | `None` | Remote server API key |
| `qdrant_quantization` | `VAULTSPEC_RAG_QDRANT_QUANTIZATION` | str\|None | `None` | Vector quantization |
| `qdrant_server` | `VAULTSPEC_RAG_QDRANT_SERVER` | bool | `True` | Server-first default; `--qdrant/--no-qdrant` |
| `local_only` | `VAULTSPEC_RAG_LOCAL_ONLY` | bool | `False` | On-disk store opt-out; `--local-only` |
| `qdrant_port` | `VAULTSPEC_RAG_QDRANT_PORT` | int | `8765` | Managed server HTTP port (gRPC = port-1) |
| `qdrant_binary` | `VAULTSPEC_RAG_QDRANT_BINARY` | str\|None | `None` | Operator-supplied binary path |
| `qdrant_storage_dir` | `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` | str | `~/.vaultspec-rag/qdrant-server/storage` | Shared multi-root server storage |
| **`storage_autoprune`** | `VAULTSPEC_RAG_STORAGE_AUTOPRUNE` | bool | `True` | **NEW.** Hourly in-daemon auto-prune enable |
| **`storage_autoprune_interval_minutes`** | `..._STORAGE_AUTOPRUNE_INTERVAL_MINUTES` | float | `60.0` | **NEW.** Maintenance tick cadence |
| **`storage_autoprune_grace_hours`** | `..._STORAGE_AUTOPRUNE_GRACE_HOURS` | float | `24.0` | **NEW.** Empty-namespace grace window |
| **`storage_autoprune_grace_hours_data`** | `..._STORAGE_AUTOPRUNE_GRACE_HOURS_DATA` | float | `168.0` | **NEW.** Data-bearing namespace grace window |
| **`storage_autoprune_archive_retention_days`** | `..._STORAGE_AUTOPRUNE_ARCHIVE_RETENTION_DAYS` | float | `30.0` | **NEW.** Archive snapshot retention |
| **`storage_autoprune_archive_max_gb`** | `..._STORAGE_AUTOPRUNE_ARCHIVE_MAX_GB` | float | `20.0` | **NEW.** Archive tree size bound |
| **`storage_autoprune_max_per_cycle`** | `..._STORAGE_AUTOPRUNE_MAX_PER_CYCLE` | int | `16` | **NEW.** Per-cycle reclaim cap |
| **`storage_autoprune_ephemeral_idle_hours`** | `..._STORAGE_AUTOPRUNE_EPHEMERAL_IDLE_HOURS` | float | `72.0` | **NEW.** Temp-rooted namespace idle-TTL tier (0 disables) |
| **`storage_reconcile`** | `VAULTSPEC_RAG_STORAGE_RECONCILE` | bool | `True` | **NEW.** Non-destructive segment-geometry convergence |
| **`storage_reconcile_max_per_cycle`** | `..._STORAGE_RECONCILE_MAX_PER_CYCLE` | int | `4` | **NEW.** Per-cycle reconcile cap |
| **`storage_reconcile_budget_seconds`** | `..._STORAGE_RECONCILE_BUDGET_SECONDS` | float | `300.0` | **NEW.** Per-collection convergence budget |
| `data_dir` | `VAULTSPEC_RAG_DATA_DIR` | str | `.vault/data/search-data` | Index data dir; `--data-dir` |
| `qdrant_dir` | `VAULTSPEC_RAG_QDRANT_DIR` | str | `qdrant` | Local on-disk subdir; `--storage-dir` |
| `index_metadata_file` | `VAULTSPEC_RAG_INDEX_META` | str | `index_meta.json` | Vault index sidecar |
| `code_index_metadata_file` | `VAULTSPEC_RAG_CODE_INDEX_META` | str | `code_index_meta.json` | Code index sidecar |
| `status_dir` | `VAULTSPEC_RAG_STATUS_DIR` | str | `~/.vaultspec-rag` | Service runtime dir; `--status-dir` |
| `log_file` | `VAULTSPEC_RAG_LOG_FILE` | str | `service.log` | Service log filename; `--log-file` |
| `mcp_port` | `VAULTSPEC_RAG_PORT` | int | `8766` | HTTP service port; `--port` |
| `log_level` | `VAULTSPEC_RAG_LOG_LEVEL` | str | `WARNING` | Logging verbosity |
| `graph_ttl_seconds` | (none) | float | `300.0` | Vault graph cache TTL |
| `service_idle_ttl_seconds` | `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS` | int | `1800` | Project slot idle eviction |
| `service_max_projects` | `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS` | int | `16` | LRU project slot cap |
| `managed_log_max_bytes` | `VAULTSPEC_RAG_MANAGED_LOG_MAX_BYTES` | int | `10485760` | Per-source log rotation size (service AND qdrant each get this full budget) |
| `managed_log_backup_count` | `VAULTSPEC_RAG_MANAGED_LOG_BACKUP_COUNT` | int | `5` | Log rotation backups |
| **`job_max_nonterminal`** | `VAULTSPEC_RAG_JOB_MAX_NONTERMINAL` | int | `64` | **NEW.** Active-job registry admission bound |
| **`job_shutdown_timeout_seconds`** | `..._JOB_SHUTDOWN_TIMEOUT_SECONDS` | float | `300.0` | **NEW.** Max wait for cooperative indexing unwind at shutdown |
| **`store_operation_timeout_seconds`** | `..._STORE_OPERATION_TIMEOUT_SECONDS` | float | `120.0` | **NEW.** Per-operation store timeout |
| **`store_write_retry_attempts`** | `..._STORE_WRITE_RETRY_ATTEMPTS` | int | `5` | **NEW.** Bounded write retry count |
| **`store_write_retry_base_seconds`** | `..._STORE_WRITE_RETRY_BASE_SECONDS` | float | `0.5` | **NEW.** Retry backoff base |
| **`store_write_retry_max_seconds`** | `..._STORE_WRITE_RETRY_MAX_SECONDS` | float | `8.0` | **NEW.** Retry backoff cap |
| **`index_segment_max_chunks`** | `VAULTSPEC_RAG_INDEX_SEGMENT_MAX_CHUNKS` | int | `64` | **NEW.** Durable-unit chunk bound |
| **`index_segment_max_bytes`** | `..._INDEX_SEGMENT_MAX_BYTES` | int | `8388608` (8 MiB) | **NEW.** Durable-unit byte bound |
| **`index_queue_max_chunks`** | `..._INDEX_QUEUE_MAX_CHUNKS` | int | `512` | **NEW.** Weighted queue chunk bound |
| **`index_queue_max_bytes`** | `..._INDEX_QUEUE_MAX_BYTES` | int | `134217728` (128 MiB) | **NEW.** Weighted queue byte bound |
| **`index_no_progress_timeout_seconds`** | `..._INDEX_NO_PROGRESS_TIMEOUT_SECONDS` | float | `900.0` | **NEW.** Liveness = time since storage-confirmed progress (not a total run deadline) |
| **`watch_retry_base_seconds`** | `..._WATCH_RETRY_BASE_SECONDS` | float | `30.0` | **NEW.** Watcher retry backoff base |
| **`watch_retry_max_seconds`** | `..._WATCH_RETRY_MAX_SECONDS` | float | `1800.0` | **NEW.** Watcher retry backoff cap |
| **`watch_retry_jitter_fraction`** | `..._WATCH_RETRY_JITTER_FRACTION` | float | `0.1` | **NEW.** Symmetric jitter on backoff |
| **`watch_circuit_failure_threshold`** | `..._WATCH_CIRCUIT_FAILURE_THRESHOLD` | int | `3` | **NEW.** Watcher circuit-breaker trip count |
| **`index_rss_ceiling_mb`** | `VAULTSPEC_RAG_INDEX_RSS_CEILING_MB` | float | `16384.0` | **NEW.** Absolute admitted RSS ceiling |
| **`index_cuda_ceiling_mb`** | `..._INDEX_CUDA_CEILING_MB` | float | `12288.0` | **NEW.** Absolute admitted CUDA ceiling |
| **`index_cuda_allocator_fraction`** | `..._INDEX_CUDA_ALLOCATOR_FRACTION` | float | `0.8` | **NEW.** Allocator cap preserving search headroom |
| **`index_support_profile`** | `VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE` | str | `managed-service` | **NEW.** Named ceiling-profile selector |
| `embedding_batch_size` | `VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE` | int | `64` | Outer embed batch |
| `embedding_encode_batch_size` | `VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE` | int | `32` | Vault inner encode sub-batch |
| `embedding_max_seq_length` | `VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH` | int | `2048` | Hard seq-length cap |
| `max_embed_chars` | `VAULTSPEC_RAG_MAX_EMBED_CHARS` | int | `8000` | Char truncation before encode |
| `index_chunk_workers` | `VAULTSPEC_RAG_INDEX_CHUNK_WORKERS` | int | `0` (auto) | Code-chunk process-pool size |
| `embedding_code_encode_batch_size` | `VAULTSPEC_RAG_EMBEDDING_CODE_ENCODE_BATCH_SIZE` | int | `32` | Code inner encode sub-batch |
| `index_cache_flush_slices` | `VAULTSPEC_RAG_INDEX_CACHE_FLUSH_SLICES` | int | `8` | CUDA allocator flush cadence |
| `index_parallel_min_bytes` | `VAULTSPEC_RAG_INDEX_PARALLEL_MIN_BYTES` | int | `8388608` (8 MiB) | Auto-parallel threshold |
| `dense_backend` | `VAULTSPEC_RAG_DENSE_BACKEND` | str | `torch` | Dense encoder backend (`onnx` experimental) |
| `dense_onnx_file` | `VAULTSPEC_RAG_DENSE_ONNX_FILE` | str | `onnx/model_O4.onnx` | ONNX model rel path |
| `embedding_model` | (none) | str | `Qwen/Qwen3-Embedding-0.6B` | Dense model |
| `embedding_dimension` | (none) | int | `1024` | Dense dim |
| `sparse_enabled` | `VAULTSPEC_RAG_SPARSE_ENABLED` | bool | `True` | SPLADE sparse vectors |
| `sparse_model` | (none) | str | `naver/splade-v3` | Sparse model |
| `reranker_enabled` | (none) | bool | `True` | CrossEncoder rerank |
| `reranker_model` | (none) | str | `BAAI/bge-reranker-v2-m3` | Reranker model |
| `reranker_batch_size` | (none) | int | `32` | Reranker batch |
| `reranker_max_length` | `VAULTSPEC_RAG_RERANKER_MAX_LENGTH` | int | `1024` | Reranker token bound |
| `vault_chunk_chars` | `VAULTSPEC_RAG_VAULT_CHUNK_CHARS` | int | `3000` | Vault chunk budget |
| **`vault_intent_default`** | `VAULTSPEC_RAG_VAULT_INTENT_DEFAULT` | str | `orientation` | **NEW.** Default ranking-intent profile (`orientation`/`debugging`) |
| **`vault_intent_ranking_enabled`** | `..._VAULT_INTENT_RANKING_ENABLED` | bool | `True` | **NEW.** Intent-prior post-rerank toggle |
| **`vault_intent_type_cap`** | `..._VAULT_INTENT_TYPE_CAP` | int | `4` | **NEW.** Per-doc_type page cap (0 disables) |
| **`code_noise_hide_domains`** | `VAULTSPEC_RAG_CODE_NOISE_HIDE_DOMAINS` | str (csv) | `worktree,generated` | **NEW.** Domains dropped from code results by default |
| **`code_noise_demote_domains`** | `..._CODE_NOISE_DEMOTE_DOMAINS` | str (csv) | `tests,docs,locale,vendored` | **NEW.** Domains demoted, not hidden |
| **`code_noise_demote_penalty`** | `..._CODE_NOISE_DEMOTE_PENALTY` | float | (not captured this pass) | **NEW.** Score subtraction for demoted results (0 disables) |
| **`dedup_locales_default`** | `VAULTSPEC_RAG_DEDUP_LOCALES_DEFAULT` | bool | (not captured this pass) | **NEW.** Default for `--dedup-locales` |
| `search_concurrency` | `VAULTSPEC_RAG_SEARCH_CONCURRENCY` | int | `16` | Search worker limiter |
| `index_job_concurrency` | `VAULTSPEC_RAG_INDEX_JOB_CONCURRENCY` | int | `4` | Index job limiter |
| `watch_enabled` | `VAULTSPEC_RAG_WATCH_ENABLED` | bool | `True` | Auto-reindex on/off; `--updates/--no-updates` |
| `watch_debounce_ms` | `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS` | int | `2000` | Debounce; `--update-delay-ms` |
| `watch_cooldown_s` | `VAULTSPEC_RAG_WATCH_COOLDOWN_S` | float | `30.0` | Per-source re-index cooldown; `--repeat-update-delay-s` |
| `preprocess_mode` | `VAULTSPEC_RAG_PREPROCESS` | str | `default` | `=off` is the kill switch; unset/anything else = `default` (rules run) |
| `preprocess_max_emitted_bytes` | `VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES` | int | `10485760` (10 MiB) | Cap on preprocessor-emitted text |
| `html_strip` | `VAULTSPEC_RAG_HTML_STRIP` | bool | `True` | Strip HTML before chunking `.html` |
| **`stdio_watchdog`** (not a config field; env-only kill switch) | `VAULTSPEC_RAG_STDIO_WATCHDOG` | bool | on | **NEW.** `0/false/off/no` disables the stdio shim's ancestor-death backstop |

**Internal-only, not operator-facing (skip in user docs):** `VAULTSPEC_RAG_ROOT`
(`RAG_ROOT`), `VAULTSPEC_RAG_SERVICE_DAEMON` (`SERVICE_DAEMON`) — set only in
the detached HTTP daemon's own environment so in-process code can
distinguish itself from an interactive CLI invocation, independent of
backend.

Third-party env vars referenced via the enum: `HF_ENDPOINT`, `HF_HOME`,
`HF_HUB_OFFLINE`, `HF_HUB_DOWNLOAD_TIMEOUT`, `TRANSFORMERS_OFFLINE`,
`DISABLE_SAFETENSORS_CONVERSION`. Also referenced as bare strings (not
re-verified this pass, carried from the prior version):
`VAULTSPEC_RAG_SEARCH_TIMEOUT` (confirmed still current — see Section 8),
`HF_HUB_DISABLE_PROGRESS_BARS`, `TRANSFORMERS_NO_ADVISORY_WARNINGS`,
`TRANSFORMERS_VERBOSITY`.

---

## 11. JSON envelope and error codes

### Envelope (live-verified, `cli/_render.py::_emit_json`)

`_emit_json(ok, command, *, data, error, message, **extra)` writes one
envelope-wrapped JSON document, bypassing Rich:
```json
{"ok": <bool>, "command": "<str>", "data"?: <obj>, "error"?: "<code>",
 "message"?: "<str>", ...extra}
```

### `server start --json` outcomes (live-verified, `cli/_service_start.py`)

- Success (`_start_success`, exit 0), `data.status` one of: `already_running`,
  `already_starting`, `started`.
- Failure (`_fail_start`, exit 1): `error` codes include `service_env_no_gpu`
  (daemon interpreter lacks GPU torch) among the existing port-in-use /
  qdrant-binary-missing paths.

### `server stop --json` outcomes (live-verified, `cli/_service_stop.py`)

- Success (`_stop_success`, exit 0), `data.status` one of: `already_stopped`,
  `stopped`, `reclaimed`, `cleaned`.
- Failure (`_fail_stop`): `error="identity_unconfirmed"` — and this exits 1
  in **BOTH** json and human mode, because a stop that leaves the service
  running is never a success (broker-facing outcome contract).

### `server status --json` exit codes (live-verified) — **5 states, was 3**

- **0** — `running`.
- **3** — `stopped` (no `service.json`).
- **4** — `crashed_pid_dead` / `crashed_pid_reused` / `crashed_port_silent` /
  `crashed_heartbeat_stale`.
- **5** — **NEW.** `warming` — a live daemon holding the machine lock but not
  yet ready to serve (models loading). The prior version of this file only
  documented 0/3/4.

### Other exit codes (from the prior version of this file, not re-verified
this pass but no evidence of removal)

- **1** — generic failure (GPU/torch errors, local index busy, unreachable
  port without `--allow-fallback`, service delegation error, qdrant
  install/clean failure, project unload busy, install failure).
- **2** — invalid usage/arguments.

---

## 12. `server status` + `server doctor` semantics

`server status` now surfaces the 5-state machine in Section 11
(0/3/4/**5-warming**). Human/verbose rendering shape not re-verified this
pass. `server doctor` now covers the live-service axis too (Section 5) —
document it as "readiness across dependencies AND live service health", not
dependency-only as the prior version of this file had it.

---

## 13. `server updates` (formerly watcher)

Not re-verified this pass beyond the command list (Section 2, unchanged).
The knobs/defaults table is superseded by Section 10's full env-var table
(`watch_enabled`/`watch_debounce_ms`/`watch_cooldown_s` unchanged; the NEW
`watch_retry_*`/`watch_circuit_failure_threshold` knobs are additional
watcher-resilience policy, not exposed as `server updates timing` flags).

---

## 14. MCP tools

**Refresh notes — major reduction, not an expansion.** The MCP surface
SHRANK from the prior version's list. Verified by grepping every
`@mcp.tool`/`@mcp.resource`/`@mcp.prompt` decorator site in
`src/vaultspec_rag/mcp/*.py`: there are now exactly **12 tools**, 1 resource,
1 prompt — and NOTHING else. `mcp/_admin_tools.py`'s tools (`list_projects`,
`evict_project`, `get_watcher_state`, `start_watcher`, `stop_watcher`,
`reconfigure_watcher`, `get_service_state`, `get_logs`, `get_jobs`,
`benchmark`, `quality`) are **GONE** — that module no longer registers any
MCP tool. Admin/watcher/jobs/logs control is CLI/HTTP-route-only now. If
`docs/mcp.md` still lists any of those 11 old names as callable MCP tools,
that is a broken doc (tells users to call tools that no longer exist).

### Current tool list (12, live-verified against `mcp/_tools.py`)

| Tool | Key params | Purpose |
|---|---|---|
| `search_vault` | query, top_k=5, doc_type?, feature?, date?, tag?, intent?, like_ids?, unlike_ids?, project_root? | Search vault docs. `intent`: `orientation` (default) / `debugging`. |
| `search_codebase` | query, top_k=5, language?, path?, node_type?, function_name?, class_name?, include_paths?, exclude_paths?, dedup_locales?, prefer?, exclude_domains?, only_domains?, include_domains?, like_ids?, unlike_ids?, project_root? | Search source code; noise-domain filters as direct params (CLI uses inline tokens instead). |
| `search_documents` | query, top_k=5, source_path?, extractor_id?, extractor_version?, locator_kind?, project_root? | **NEW.** Search independently indexed extracted-document content. |
| `search_combined` | union of all filters above | **NEW.** Search vault+code+document, partial outcomes preserved. |
| `get_code_file` | path, project_root? | Retrieve full content of a source file. |
| `reindex_vault` | project_root? | Incremental vault reindex. |
| `reindex_codebase` | project_root? | Incremental codebase reindex. |
| `reindex_documents` | project_root? | **NEW.** Incremental document reindex. |
| `reindex_all` | project_root? | **NEW.** Incremental reindex of vault+code+document. |
| `get_index_status` | project_root? | Count/policy/generation/degraded-state service details. |
| `clean_documents` | project_root? | **NEW.** Delete only extracted-document content. |
| `clean_all` | project_root? | **NEW.** Delete vault+code+document, per-domain outcomes. |

MCP still uses `node_type` (not the CLI's `--structure` flag name) on
`search_codebase`/`search_combined` — unchanged from the prior version.

### Resource and prompt (`mcp/_resources.py`, unchanged)

- Resource `vault://{doc_id}` → full document content by stem id.
- Prompt `analyze_feature(feature_name)` → structured analysis prompt.

**There is still NO `get_readiness` MCP tool** — readiness is CLI `server
doctor` + the `/readiness` HTTP route only (carried from the prior version,
not re-verified but no evidence of a new MCP readiness tool).

---

## 15. Data / status directory layout

Not re-verified this pass. Prior version's layout (`~/.vaultspec-rag/`
service runtime dir with `service.json`/`service.log`/`local-only.json`/
`bin/qdrant/{version}/`/`qdrant.log`/`qdrant-server/storage/`) is consistent
with everything seen this pass (the `server storage` group and
`qdrant_storage_dir` default confirm the storage path is unchanged). The
read-only HTTP route list was not re-verified and may be missing routes for
the new `server job`/`server storage`/`server reconcile` surfaces — check
`server/_routes.py` before documenting the HTTP route list as complete.

---

## 16. Removed / renamed summary

Do NOT reintroduce these stale names in docs. Combines the prior version's
table (still valid — the "server service" flatten predates both this and
the prior refresh) with this pass's findings.

| Old | New | Status |
|---|---|---|
| `server service *` | `server *` (flattened) | renamed, see prior entries below |
| `search --node-type` | `search --structure` | CLI flag renamed (API/MCP keep `node_type`) |
| `search --no-truncate` | (removed) | rendering no longer truncates |
| `--watch/--no-watch` (start) | `--updates/--no-updates` | renamed |
| **`benchmark` (top-level command)** | **(removed)** | **NEW THIS PASS.** No `@app.command` registers it; the MCP `benchmark()` tool is also gone |
| **`quality` (top-level command)** | **(removed)** | **NEW THIS PASS.** Same as above; MCP `quality()` tool also gone |
| **MCP `list_projects`/`evict_project`/`get_watcher_state`/`start_watcher`/`stop_watcher`/`reconfigure_watcher`/`get_service_state`/`get_logs`/`get_jobs`** | **(removed from MCP; CLI/HTTP-route equivalents still exist)** | **NEW THIS PASS.** `mcp/_admin_tools.py` registers zero MCP tools now |
| `install`: `[mcp]` extra "deprecated no-op, mcp is core dep" | `install --mcp/--no-mcp` (optional again) | **REVERSED THIS PASS** |
| `search`/`index`/`clean --type {vault,code}` | `{vault,code,document,combined}` (+ `docs`/`codebase`/`all` aliases) | **EXPANDED THIS PASS** — new `document` domain |
| (no per-job control) | `server job {show,pause,resume,stop,retry,delete}` | **NEW THIS PASS** |
| (no storage lifecycle CLI) | `server storage {survey,delete,prune,reconcile,migrate}` | **NEW THIS PASS** |
| (no discovery-wait verb) | `server reconcile` | **NEW THIS PASS** |
| `server qdrant {install,status,clean}` | adds `quarantine` | **NEW THIS PASS** |
| `preprocess {list,check,run-one}` | adds `status` | **NEW THIS PASS** |
| `server status` exit codes 0/3/4 | adds 5 (`warming`) | **NEW THIS PASS** |
| `server start`/`stop` (no `--json`) | both gain `--json` with broker-facing outcome envelopes | **NEW THIS PASS** |

MCP-surface note: the MCP tool names `evict_project`/`reconfigure_watcher`
that the prior version flagged as "not renamed even though the CLI verb
was" are now moot — those tools do not exist at all anymore (see Section 14).

### New in this branch since the 2026-06-13 / v0.2.20 version of this file

`server job` group, `server storage` group, `server reconcile`,
`preprocess status`, `server qdrant quarantine`, the extracted-document index
domain (`document`/`combined` everywhere: `search`/`index`/`clean` +
`search_documents`/`reindex_documents`/`clean_documents`/`search_combined`/
`reindex_all`/`clean_all` MCP tools), storage autoprune + geometry-reconcile
(whole env-var families), index resource ceilings, job/store write-retry
timeouts, watcher retry/circuit-breaker policy, intent-aware vault ranking,
code-search noise-domain filtering, `install --mode`/`--torch-group`/
`--mcp`/`--no-mcp`, `server start --no-preprocess`/`--json`, `server stop
--json`, `server status` exit-5 warming state, `server jobs --watch`,
`server logs --source`.

### Removed since the 2026-06-13 / v0.2.20 version of this file

Top-level `benchmark`/`quality` commands; the entire MCP admin/watcher/
jobs/logs/benchmark/quality tool set (11 tools, `mcp/_admin_tools.py`).

## Ground truth provenance

This file supersedes its own 2026-06-13/v0.2.20 version. Re-verify the
sections marked "not re-verified this pass" before treating them as current
if a future refresh is not imminent.
