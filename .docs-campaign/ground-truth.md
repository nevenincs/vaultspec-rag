# vaultspec-rag ground truth (server-first-default branch)

Authoritative, CODE-VERIFIED current state for the documentation rewrite. Every
claim is cited to `src/...:line` in this worktree
(`feature/server-supervision`). Where something is scaffolded-but-not-fully-wired
it is flagged explicitly. Do not carry over old behavior; trust this file.

Verified against the working tree on 2026-06-13. CLI help was NOT executed
(avoiding side effects); all facts are read from the Typer source.

---

## 1. Package version and entry points

- **Version: `0.2.20`** — `pyproject.toml:54` (`version = "0.2.20"`).
- Build backend: hatchling. Python `>=3.13` (`requires-python = ">=3.13"`).
  Runtime is locked to CPython **3.13.x**; 3.14+ is rejected at import
  (`store.py:170-211`, `_interpreter_is_supported`).
- Console scripts (`pyproject.toml:57-59`):
  - `vaultspec-rag = "vaultspec_rag.__main__:main"` — the Typer CLI.
  - `vaultspec-search-mcp = "vaultspec_rag.server:main"` — the MCP/HTTP daemon
    entry (`server/_main.py:27`).
- `python -m vaultspec_rag` also runs the CLI (`__main__.py:8-16`).
- `python -m vaultspec_rag.server --port N` runs the HTTP daemon; bare (no
  `--port`) runs stdio MCP (`server/_main.py:27-160`).
- Key runtime deps (`pyproject.toml:18-37`): `sentence-transformers>=5.0`,
  `torch>=2.4`, `transformers>=4.51`, `qdrant-client>=1.16.0`, `pydantic`,
  `rich`, `vaultspec-core>=0.1.27`, `mcp>=1.26.0`, `typer>=0.12.0`, `click`,
  `tree-sitter`, `watchfiles`, `psutil`, `tomlkit`, `packaging`.
- The `[mcp]` extra is a deprecated no-op alias (mcp is now a core dep)
  (`pyproject.toml`).

---

## 2. Complete CLI command tree

Root app: `app` in `cli/_app.py:36`. Help: "VaultSpec RAG: search project
documentation and source code." `rich_markup_mode=None`,
`pretty_exceptions_enable=False`.

**Group nesting (`cli/_app.py:71-75`):**
- `app` → `server` (`server_root_app`, alias `server_app`)
- `server` → `projects` (`server_projects_app`)
- `server` → `updates` (`server_watcher_app`) — NOTE: command path is
  `server updates`, but the Typer object is still named `server_watcher_app`.
- `server` → `qdrant` (`server_qdrant_app`)
- `app` → `preprocess` (`preprocess_app`)

There is **NO `server service` layer**. The old `server service ...` prefix is
gone; lifecycle/jobs/logs verbs live directly under `server`.

### Root callback global options (`cli/_app.py:154-261`)

Applied before any subcommand:
- `--target, -t PATH` — directory containing `.vault` and `.vaultspec`
  (resolve_path, dir only).
- `--verbose, -v` — INFO logging.
- `--debug, -d` — DEBUG logging.
- `--data-dir TEXT` — index data dir (default `.vault/data/search-data`).
- `--storage-dir TEXT` — index data subdir relative to `--data-dir` (maps to
  config `qdrant_dir`).
- `--status-dir TEXT` — service runtime dir (default `~/.vaultspec-rag`).
- `--log-file TEXT` — service log filename inside `--status-dir`.
- `--version, -V` — print version and exit (`cli/_app.py:141-151`).

`test`, `quality`, `server`, `install`, `uninstall` short-circuit workspace
resolution (`cli/_app.py:237-254`); all other subcommands resolve a workspace.

### Top-level commands

| Command | Purpose | Source |
|---|---|---|
| `index` | Build/update vault + code index | `cli/_index.py:357` |
| `clean <vault\|code\|all>` | Delete index data without rebuilding | `cli/_index.py:578` |
| `search <query>` | Hybrid search vault docs or code | `cli/_search.py:522` |
| `status` | Project index counts, data location, compute device | `cli/_status.py:143` |
| `install` | Enroll workspace + provision deps | `cli/_install.py:14` |
| `uninstall` | Remove enrollment | `cli/_install.py:240` |
| `test [PYTEST_ARGS...]` | Run pytest over the test tree | `cli/_test.py:12` |
| `quality` | Needle-precision probes on synthetic vault | `cli/_quality.py:13` |
| `benchmark` | Local search-latency percentiles | `cli/_benchmark.py:17` |

### `server` group lifecycle / observability

| Command | Purpose | Source |
|---|---|---|
| `server start` | Start the background search service | `cli/_service_lifecycle.py:158` |
| `server stop` | Stop the background search service | `cli/_service_lifecycle.py:326` |
| `server status` | Operator status summary | `cli/_service_lifecycle.py:1256` |
| `server warmup` | Pre-download GPU model files | `cli/_service_lifecycle.py:1424` |
| `server doctor` | Dependency readiness report | `cli/_service_doctor.py:23` |
| `server jobs` | List recent index/reindex activity | `cli/_service_jobs.py:1020` |
| `server logs` | Recent service activity feed | `cli/_service_logs.py:471` |

### `server projects`

| Command | Purpose | Source |
|---|---|---|
| `server projects list` | List loaded project slots | `cli/_service_projects.py:155` |
| `server projects unload <project>` | Unload a project slot | `cli/_service_projects.py:282` |

(`unload` replaces the old `evict`.)

### `server updates` (formerly `watcher`)

| Command | Purpose | Source |
|---|---|---|
| `server updates status` | Show auto-update settings + watched projects | `cli/_service_watcher.py:185` |
| `server updates start <project>` | Start auto index updates for a project | `cli/_service_watcher.py:240` |
| `server updates stop <project>` | Stop auto index updates for a project | `cli/_service_watcher.py:300` |
| `server updates timing <project>` | Change auto-update timing (was `reconfigure`) | `cli/_service_watcher.py:355` |

### `server qdrant`

| Command | Purpose | Source |
|---|---|---|
| `server qdrant install` | Download + verify the managed Qdrant server | `cli/_service_qdrant.py:73` |
| `server qdrant status` | Executable/address/connection/process | `cli/_service_qdrant.py:230` |
| `server qdrant clean` | Delete managed Qdrant installs | `cli/_service_qdrant.py:263` |

### `preprocess`

| Command | Purpose | Source |
|---|---|---|
| `preprocess list` | Show resolved preprocess rules | `cli/_preprocess.py:66` |
| `preprocess check` | Validate `.vaultragpreprocess.toml` | `cli/_preprocess.py:111` |
| `preprocess run-one <path>` | Trial-run the matching rule on one file | `cli/_preprocess.py:151` |

### Removed/renamed vs the old "server service" CLI — see Section 16.

---

## 3. Server-first default model

### config.py defaults (`config.py:259-401`)

- `qdrant_server`: **`True`** (`config.py:277`). The supervised Qdrant server is
  the assumed backend.
- `local_only`: **`False`** (`config.py:285`). First-class opt-out.
- `qdrant_port`: `8765` (`config.py:286`) — the managed server's HTTP port,
  default one below the service port 8766. The gRPC listener binds one below
  that (8764) (`qdrant_runtime/_supervise.py:167` — `grpc_port = http_port - 1`).
- `qdrant_binary`: `None` (`config.py:287`) — operator override path
  (air-gapped escape hatch).
- `qdrant_storage_dir`: `"~/.vaultspec-rag/qdrant-server/storage"`
  (`config.py:288`). Shared multi-root storage under the managed service dir.
- `qdrant_url`: `None` (`config.py:260`) — set to point at a *remote* server.

### Effective server mode resolution (`config.py:456-472`)

`effective_server_mode()` returns `bool(qdrant_server) and not bool(local_only)`.
**local-only always wins** over the server default. Callers selecting the backend
MUST consult this rather than reading `qdrant_server`. Used by the daemon lifespan
(`server/_lifespan.py:82`) and the readiness reporter (`_readiness.py:169`).

### Env vars

- `VAULTSPEC_RAG_LOCAL_ONLY` (`EnvVar.LOCAL_ONLY`, `config.py:86`). Truthy values:
  `1/true/yes` (bool coercion, `config.py:434-435`). Selects the on-disk store.
- `VAULTSPEC_RAG_QDRANT_SERVER` (`EnvVar.QDRANT_SERVER`, `config.py:80`) — the
  redundant server-mode env knob.
- Resolution precedence for `local_only` (`config.py:414-454`): base config / CLI
  override → env var → **persisted runtime marker** → module default. The
  persisted marker is `local-only.json` under the status dir
  (`config.py:157`, `persist_local_only`/`read_persisted_local_only`,
  `config.py:184-237`); `install --local-only` writes it so a later
  `server start` with no flag/env still selects local.

### Persisted local-only marker

- File: `{status_dir}/local-only.json`, content `{"local_only": bool}`, atomic
  write via `.tmp` + `os.replace` (`config.py:184-209`). `status_dir` default
  `~/.vaultspec-rag`, override `VAULTSPEC_RAG_STATUS_DIR` (`config.py:163-176`).

### `server start` flags (`cli/_service_lifecycle.py:166-235`)

- `--port INT` (default 8766, envvar `VAULTSPEC_RAG_PORT`).
- `--updates / --no-updates` (tri-state `bool|None`, default unset) — enable/
  disable automatic index updates.
- `--update-delay-ms INT` — debounce before indexing a change burst.
- `--repeat-update-delay-s FLOAT` — min wait before re-updating a project
  (the watcher cooldown; recently renamed — see Section 13).
- `--local-only` — use the on-disk store, skip the Qdrant child.
- `--qdrant / --no-qdrant` (tri-state) — explicit server-mode opt in/out;
  `--qdrant` is redundant (default), unset leaves the current setting alone.
- `--qdrant-auto-provision` — download the managed Qdrant if missing instead of
  printing the install command.

### What a bare `server start` does

With no flags (`cli/_service_lifecycle.py:236-323`):
1. Port-availability guard (port 8766) — fails with next-actions if in use
   (`:238-249`).
2. Because `not local_only and qdrant is not False`, it runs
   `_ensure_qdrant_binary(auto_provision=False)` (`:255-256`) — fails fast if the
   binary is missing (see remediation below).
3. Spawns the detached daemon (`_spawn_service`), which on startup spawns the
   supervised Qdrant child before loading models (`server/_lifespan.py:82-125`).
4. Polls `/health` until `status == "ready"` (deadline 300s, exp backoff)
   (`:274-314`).

`--local-only` (or `--no-qdrant`) skips the binary guard and the daemon selects
the per-project on-disk store via `effective_server_mode()` returning False
(`server/_lifespan.py:82`; flags forwarded as env in
`cli/_process.py:310-356`).

### Loud/actionable failure contract

**CLI pre-flight guard** (binary missing, `cli/_service_lifecycle.py:46-82`):
```
Service start failed
Qdrant server mode needs the managed Qdrant server, which is not installed.
Run: vaultspec-rag server qdrant install
(or re-run with --qdrant-auto-provision to consent to the download)
Local-only option: vaultspec-rag server start --local-only
```
Exit 1.

**Daemon-side guard** (server fails to start, `server/_lifespan.py:108-115`):
```
qdrant server mode (the default backend) failed to start: <exc>
Provision the server binary with: vaultspec-rag server qdrant install
Or run the service in local-only mode (on-disk store, no server) with:
vaultspec-rag server start --local-only
```
This `RuntimeError` aborts startup (never silently falls back to local). The
supervisor's own failure message also names the install command and `--local-only`
(`qdrant_runtime/_supervise.py:408-439`).

---

## 4. `install` provisioning front door

`cli/_install.py:14-237` → `commands.install_run` → provisioning via
`commands/_provision.py:provision_dependencies`.

### What install does now

Workspace enrollment (seed bundled rules/MCP, core sync) PLUS, by default,
provisioning of three external dependencies through one front door
(`commands/_provision.py:180-242`):
1. **torch** — configure the cu130 PyTorch package source in `pyproject.toml`
   (two-phase: patch + follow-up `uv sync`).
2. **models** — ensure dense/sparse/reranker HF repos are cached (reuses warmup's
   snapshot-download path; no GPU load) (`_provision.py:353-444`).
3. **qdrant** — download + verify the pinned Qdrant server binary
   (`_provision.py:447-480`).

### install flags (`cli/_install.py:16-138`)

- `--target, -t PATH` (default cwd).
- `--upgrade` — refresh bundled rules/integration even if present.
- `--dry-run` — preview without writing.
- `--force` — override existing files; bypasses torch-config prompt (implies
  `--yes` for that step); `--no-torch-config` still wins.
- `--skip TEXT` (repeatable) — skip a component (enrollment component tokens).
- `--torch-config / --no-torch-config` (default on) — configure cu130 torch
  source in pyproject.
- `--yes, -y` — skip the PyTorch config prompt (required for non-interactive
  installs unless `--no-torch-config`).
- `--sync` — run `uv sync --reinstall-package torch` after torch config.
- `--provision / --no-provision` (default on) — provision external deps after
  enrollment.
- `--local-only` — on-disk store: **skips the Qdrant binary download** and
  persists the local backend so `server start` honors it.
- `--skip-torch` — skip the torch provisioning step (finer than `--local-only`).
- `--skip-models` — skip model provisioning.
- `--skip-qdrant` — skip the Qdrant binary provisioning step.
- `--json` — JSON report.

Per-dependency skip flags map onto the front door's skip token set
(`cli/_install.py:181-187`; tokens `torch`/`models`/`qdrant`,
`commands/_provision.py:55-65`). `--local-only` already drops qdrant in the front
door; `--skip-qdrant` is the redundant explicit control (both unioned).

### Install report fields & vocabulary

`InstallReport` (`commands/_models.py:39-91`): `action`
(`install`/`upgrade`/`dry_run`), `target`, `created_dirs`, `seeded`,
`sync_results`, `warnings`, `torch_config_action`, `torch_config_conflicts`,
`torch_direct_dep_action`, `torch_direct_dep_location`, `torch_sync_action`,
`provision_outcome`. `to_dict()` adds `sync_added/updated/pruned` and a
`provisioning` block.

Provisioning vocabulary (`commands/_provision.py:67-92` `ProvisionAction`):
`created` / `updated` / `unchanged` / `skipped` / `failed` / `dry_run`. Aggregate
`ProvisionOutcome.status` collapses to `failed` if any failed, `mixed` if steps
disagree, else the common action; `unchanged` when empty
(`_provision.py:147-157`).

Human render labels (`cli/_render.py:553-565`): step labels `torch`→"PyTorch",
`models`→"Models", `qdrant`→"Qdrant binary"; action labels
`created`→"downloaded", `updated`→"updated", `unchanged`→"already present",
`skipped`→"skipped", `failed`→"failed", `dry_run`→"preview only".

**Torch "configured, sync pending"**: a `created`/`updated` torch step with
`sync_pending=True` renders as `configured, sync pending` (distinct from a
binary's terminal "downloaded") (`cli/_render.py:573-584`,
`commands/_provision.py:297-322`).

Install exits non-zero (code 2) when `configure_torch=True` ended in
`ERROR`/`SKIPPED_EOF`/`SKIPPED_NON_TTY` (`cli/_install.py:230-237`).

### Wiring status

Fully wired: enrollment, torch config, model ensure, Qdrant binary provision,
all skip flags, dry-run, JSON. This is the `2026-06-13-provisioning-setup-adr`
work (`commands/_provision.py:27`, `_readiness.py:34-36`). No scaffolded-only
stubs observed in this path.

---

## 5. `server doctor` readiness verb

`cli/_service_doctor.py:23-69` → `api.get_readiness()` →
`_readiness.compute_readiness()`. Read-only; provisions/mutates nothing.

### Dimensions (`_readiness.py:155-375`)

- **torch** (`_torch_readiness`, `:181-242`): reads `torch.version.cuda` +
  `torch.cuda.is_available()`, classifies via `diagnose_torch`. READY when
  WORKING (CUDA available, names the device); NOT_READY for CPU-only build or
  cu130-without-device. info: `installed`, `cuda_build`, `cuda_available`,
  `diagnosis`, `device_name`.
- **models** (`_models_readiness`, `:245-298`): probes the HF cache via
  `try_to_load_from_cache(repo, "config.json")` for dense/sparse/reranker. READY
  when all present; NOT_READY lists missing repos; UNKNOWN if `huggingface_hub`
  not importable. info: `repos` dict.
- **qdrant** (`_qdrant_readiness`, `:300-375`): reads binary resolution source
  (`env`/`provisioned`/`path`/`absent`) + live `runtime_state()`. In local-only
  mode an absent binary is READY (no server needed). In server mode: NOT_READY
  if no binary resolves; NOT_READY if a supervised child is tracked and dead;
  READY otherwise. info: `binary_source`, `binary_path`, `server_mode`,
  `runtime`.

### Output

Human (`cli/_service_doctor.py:47-69`):
```
Service readiness
Backend: server | local-only
Readiness: ready for requests | not ready
  <name>: <status> - <detail>
```
JSON (`--json`): `_emit_json(ready_bool, "server doctor", data=report)` where
report = `ReadinessReport.to_dict()` = `{ready, server_mode, dependencies:[{name,
status, detail, info}]}` (`_readiness.py:146-152`).

Registered and callable (`cli/__init__.py:103,203`). Also backs the `/readiness`
loopback route (`server/_routes.py:900-907,1059`, token-gated).

---

## 6. `server qdrant` group

Pinned constants (`qdrant_runtime/_constants.py`):
- **`QDRANT_SERVER_VERSION = "1.18.2"`** (`:27`) — same minor line as the locked
  qdrant-client (1.18.x).
- `QDRANT_RELEASE_BASE_URL = "https://github.com/qdrant/qdrant/releases/download"`
  (`:31`). Effective URL: `{base}/v{version}/{asset}`.
- `ALLOWED_DOWNLOAD_HOSTS` (`:40`): `github.com`,
  `objects.githubusercontent.com`, `release-assets.githubusercontent.com`.
- `QDRANT_ASSET_SHA256` (`:52-71`): committed digests for 6 per-platform assets
  (aarch64/x86_64 darwin, aarch64/x86_64 linux musl, x86_64 linux gnu, x86_64
  windows-msvc zip). Verified BEFORE extraction.

### `server qdrant install` (`cli/_service_qdrant.py:73-131`)

Flags: `--upgrade`, `--dry-run`, `--binary PATH` (register operator-supplied
executable instead of downloading), `--json`. Delegates to
`qdrant_runtime.provision(upgrade, dry_run, binary)`. Human report shows Action /
Version / Release package / Download / Install / SHA256 / Detail
(`:58-70`). Exit 1 on `FAILED`.

### `server qdrant status` (`cli/_service_qdrant.py:230-260`)

Flags: `--port INT (1-65535)`, `--json`. Payload (`_qdrant_status_payload`,
`:146-174`): `pinned_version`, `server_mode_default` (`cfg.qdrant_server`),
`port`, `ready` (`/readyz` probe), `active_binary` ({path, source, version}),
`provisioned` (list), `service` (recorded child: `qdrant_pid`/`qdrant_alive`/
`qdrant_port` from service.json). Human render shows Managed version, Executable,
Address, Connection, Process, Available installs.

### `server qdrant clean` (`cli/_service_qdrant.py:263-337`)

Flags: `--keep-current` (preserve pinned version), `--yes` (required to delete),
`--dry-run`, `--json`. Help: "Index data is never touched." Without `--yes` (or
with `--dry-run`) prints a preview; preview without `--yes` and with targets
exits 1 (`:336-337`). Calls `clean_provisioned(keep_current=...)`
(`qdrant_runtime/_provision.py:504-524`) which `rmtree`s version dirs.

### On-disk layout & verification

- Managed install dir: `{status_dir}/bin/qdrant/{version}/` (`qdrant_bin_dir`,
  `_resolve.py:103-111`). Binary `qdrant.exe` (win) / `qdrant` (`:97-100`).
  Manifest `manifest.json` next to it (`_constants.py:74`).
- Resolution order (`_resolve.py:178-205`): `VAULTSPEC_RAG_QDRANT_BINARY` (env,
  trusted as-is) → provisioned managed dir (manifest must match pin) → `qdrant`
  on PATH.
- **Verify-before-execute** (`pinned-binaries-verify-before-execute` rule):
  download is HTTPS host-pinned with scheme re-checked across redirects
  (`_provision.py:89-146`); SHA256 verified BEFORE extraction, mismatch deletes
  the partial and raises `ChecksumMismatchError` (`:187-218`); extraction
  flattens the single binary member by basename — no `extractall`, no path
  traversal (`:149-184`); the provisioned binary is **re-hashed against its
  manifest digest immediately before spawn** (`_supervise.py:414-421`).
- Download cap 256 MiB, timeout 120s (`_provision.py:56-61`).
- **Air-gapped/operator escape hatch**: `--binary PATH` to `qdrant install`
  registers an operator binary (no checksum pin applies; recorded as
  `source: operator` in the manifest, logged as a warning)
  (`_provision.py:265-311`); or set `VAULTSPEC_RAG_QDRANT_BINARY` to bypass the
  managed dir entirely (`_resolve.py:135-147`).

---

## 7. Managed Qdrant server vs local mode (store layer)

### Server provisioning & supervision (`qdrant_runtime/_supervise.py`)

- The daemon spawns exactly one loopback-bound qdrant child via
  `start_supervised_from_config()` (`:383-441`) during the lifespan
  (`server/_lifespan.py:90-125`), BEFORE model load.
- The child is configured entirely through `QDRANT__*` env vars
  (`_supervise.py:190-204`): `QDRANT__SERVICE__HOST=127.0.0.1`,
  `QDRANT__SERVICE__HTTP_PORT`, `QDRANT__SERVICE__GRPC_PORT`,
  `QDRANT__STORAGE__STORAGE_PATH`, `QDRANT__STORAGE__SNAPSHOTS_PATH` (sibling
  `snapshots/` dir), `QDRANT__TELEMETRY_DISABLED=true`.
- Default address: `http://127.0.0.1:8765` (HTTP), gRPC 8764 (`http_port - 1`,
  `:167`). The supervisor publishes its URL into `VAULTSPEC_RAG_QDRANT_URL` for
  the daemon's lifetime so every config read (registry stores, watcher) sees
  server mode (`server/_lifespan.py:116-119`); undone on shutdown (`:189`).
- Readiness: polls `/readyz` with backoff, 60s timeout (`:42,270-303`).
- Windows orphan guard: child assigned to a kill-on-close Job Object so a hard
  daemon death tears the child down (`:56-141,177-178,238-241`).
- Heartbeat does one bounded auto-restart of a dead child per daemon lifetime
  (`server/_lifecycle.py:162-204`, restart cap 1).
- Shutdown order (`server/_lifespan.py:165-189`): watchers → stores → qdrant
  child LAST.

### Per-root namespacing

One shared server hosts every root's data; each root's collections are namespaced
by `root_collection_prefix()` = `r{12-hex blake2b of normcased resolved path}_`
(`store.py:129-150`). Applied only in server mode (`store.py:408`).

### Local mode

`store.py:374-456`. Server mode is selected by `self._server_mode =
bool(cfg.qdrant_url)` (`store.py:403`). When `qdrant_url` is set the store
connects to the server; otherwise it opens an embedded on-disk Qdrant at
`{root}/{data_dir}/{qdrant_dir}/` = default `.vault/data/search-data/qdrant/`
(`store.py:442-455`), guarded by a `FileLock` (`exclusive.lock`) — a busy index
raises `VaultStoreLockedError`. NOTE: the store keys off `qdrant_url`, not
`effective_server_mode()` directly; the daemon bridges the two by exporting the
supervised child's URL into `VAULTSPEC_RAG_QDRANT_URL` (Section 3 wiring).

### Backend-aware locking (`storage-locks-are-backend-aware` rule)

`store.py:421-426,500-531`:
- Local mode: one reentrant `RLock` per collection (`vault_docs`,
  `codebase_docs`) plus a lifecycle `RLock` for open/close + collection
  create/drop. `_point_lock(collection)` returns the collection's own RLock.
- Server mode: `_point_lock` returns a `nullcontext()` — no point-operation locks
  (the remote server is concurrency-safe).
- `close()` takes the lifecycle lock then every collection lock in fixed order.

---

## 8. Search output and flags

### Current rendering (readable records, NOT a Rich table)

`cli/_render.py:240-355` `_display_search_results`. Each result is a record:
```
<rank>. <location>[ (score 0.1234)]
   <text line 1>
   <text line 2>
   ...
```
- **Location** (`_search_result_location`, `:327-355`): the best stable locator
  on the result — `anchor` if present; else `path`/`source_path`/`doc_id`/`id`
  with `:line_start[:column]` appended when present; else `path (locator)`.
- **Text body** (`_search_result_text_lines`, `:282-291`): the result's
  `rerank_text` (full content) if non-empty; else the actual source lines read
  from disk for the `line_start..line_end` range (`_source_line_text_lines`,
  `:294-314`); else the `snippet`.
- Scores are shown **only with `--scores`** (`:266-268`).
- **There is NO truncation knob and NO `--no-truncate` flag** — the renderer
  prints full record text. `--no-truncate` was REMOVED.

### search flags (`cli/_search.py:530-699`)

Shared:
- `--type docs|vault|code` (default `vault`). `docs` is an accepted alias for
  `vault` (`_validate_search_type` allows `vault|docs|code`,
  `_canonical_search_type` maps `docs`→`vault`, `:423-445`).
- `--max-results, --limit INT` (default **10**).
- `--scores` (default off) — show numeric relevance scores.
- `--port INT` — use the service on this port.
- `--allow-fallback` (default off) — run locally if the service is unreachable.
- `--verbose` — show model-loading/progress for local search.
- `--json` — JSON envelope.
- `--timeout FLOAT` — connection+read budget for service-handled searches
  (default 300; env `VAULTSPEC_RAG_SEARCH_TIMEOUT`) (`:689-699`). NEW.

Code filters:
- `--language TEXT`, `--path TEXT` (exact project-relative path),
  `--include-path TEXT` (repeatable glob), `--exclude-path TEXT` (repeatable
  glob), `--dedup-locales` (default off), `--prefer production|tests|documentation`,
  `--structure TEXT` (maps to `node_type` internally — this is the renamed
  `--node-type`; `:605-611,714`), `--function-name TEXT`, `--class-name TEXT`.

Vault filters:
- `--doc-type TEXT`, `--feature TEXT`, `--date TEXT` (yyyy-mm-dd), `--tag TEXT`
  (without `#`).

### Added/removed/renamed vs old docs

- ADDED: `--scores`, `--limit` alias, `--timeout`, `docs` type alias.
- RENAMED: `--node-type` → `--structure` (CLI flag; internal/API/MCP still
  `node_type`).
- REMOVED: `--no-truncate` (rendering no longer truncates).
- Default `--max-results` is 10 (unchanged from recent).
- `--prefer` accepts the long words `production`/`tests`/`documentation` (mapped
  to `prod`/`tests`/`docs`, `:397-420`).

### Routing

If `--port` is unset, the CLI auto-detects a running service via
`service.json` and, if found, sets `--port` and `--allow-fallback` automatically
(`cli/_search.py:729-733`). Result tables/records carry a `via` label
(`service` / `in-process`). Unreachable `--port` without `--allow-fallback` →
exit 1 with remediation (`_display_port_unreachable_error`,
`cli/_render.py:384-431`).

---

## 9. `index` command flags and behavior

`cli/_index.py:357-473`.
- `--type vault|code|all` (default **`all`**). `--rebuild --type` is scoped to the
  given type.
- `--model TEXT` — override embedding model name.
- `--rebuild` (default off) — delete the selected index data before rebuilding.
  **Requires an explicit `--type`** when set (`_validate_rebuild`,
  `:187-217`): a bare `index --rebuild` errors out (code 2, error
  `rebuild_requires_explicit_type`) so it can't silently inherit `all`.
- `--port INT` — delegate to a running service.
- `--dry-run` (default off) — list source-code files that would be indexed
  WITHOUT indexing. **Only valid for `--type code` or the default `--type all`**;
  any other type errors out (code 2, `dry_run_requires_code`, `:106-127`). Dry
  run is code-only (`scan_codebase_files`).
- `--dry-run-limit INT` (default 50) — max file paths shown in human dry-run
  output (JSON always shows all). Negative is rejected (code 2,
  `invalid_dry_run_limit`).
- `--exclude TEXT` (repeatable, gitignore syntax) — ad-hoc exclusions (ignored
  when delegating to the service, `:229-232`).
- `--allow-fallback`, `--verbose`, `--json`.

Behavior: if `--port` unset, auto-detect a running service and delegate with
fallback (`:462-471`). Service delegation queues async reindex jobs and prints
`Check progress with: vaultspec-rag server jobs` (`:279-307`). In-process
indexing is incremental unless `--rebuild` (clean=rebuild). In-process code
results also carry `preprocess_skipped`/`preprocess_failures` counts
(`:560-564`).

### `clean` command (`cli/_index.py:578-683`)

- Positional `clean_type vault|code|all` — **required** (no default; nothing
  deleted by accident).
- `--yes, -y` — confirm without prompting.
- `--json` — requires `--yes` (else error `json_requires_yes`, code 2).
- Does not load models / touch GPU. Calls `api.clean()` which drops + recreates
  the selected collections and removes the metadata sidecars
  (`api.py:427-478`).

---

## 10. Full config / env var inventory

From `EnvVar` enum (`config.py:26-92`) and `_RAG_DEFAULTS` (`config.py:259-401`).
Env override map at `config.py:96-146`. All env vars are `VAULTSPEC_RAG_*` except
the three third-party ones at the end. Bool coercion: `1/true/yes`; int/float
coerced from string (`config.py:434-440`).

| Config key | Env var | Type | Default | Controls / CLI flag |
|---|---|---|---|---|
| `qdrant_url` | `VAULTSPEC_RAG_QDRANT_URL` | str\|None | `None` | Remote/managed server URL; selects server mode in store |
| `qdrant_api_key` | `VAULTSPEC_RAG_QDRANT_API_KEY` | str\|None | `None` | Remote server API key |
| `qdrant_quantization` | `VAULTSPEC_RAG_QDRANT_QUANTIZATION` | str\|None | `None` | Vector quantization |
| `qdrant_server` | `VAULTSPEC_RAG_QDRANT_SERVER` | bool | **`True`** | Server-first default; `--qdrant/--no-qdrant` |
| `local_only` | `VAULTSPEC_RAG_LOCAL_ONLY` | bool | `False` | On-disk store opt-out; `--local-only` |
| `qdrant_port` | `VAULTSPEC_RAG_QDRANT_PORT` | int | `8765` | Managed server HTTP port (gRPC = port-1) |
| `qdrant_binary` | `VAULTSPEC_RAG_QDRANT_BINARY` | str\|None | `None` | Operator-supplied binary path |
| `qdrant_storage_dir` | `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` | str | `~/.vaultspec-rag/qdrant-server/storage` | Shared multi-root server storage |
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
| `service_log_max_bytes` | `VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES` | int | `10485760` | Log rotation size |
| `service_log_backup_count` | `VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT` | int | `5` | Log rotation backups |
| `embedding_batch_size` | `VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE` | int | `64` | Outer embed batch |
| `embedding_encode_batch_size` | `VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE` | int | `32` | Vault inner encode sub-batch |
| `embedding_max_seq_length` | `VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH` | int | `2048` | Hard seq-length cap |
| `max_embed_chars` | `VAULTSPEC_RAG_MAX_EMBED_CHARS` | int | `8000` | Char truncation before encode |
| `index_chunk_workers` | `VAULTSPEC_RAG_INDEX_CHUNK_WORKERS` | int | `0` (auto) | Code-chunk process-pool size |
| `embedding_code_encode_batch_size` | `VAULTSPEC_RAG_EMBEDDING_CODE_ENCODE_BATCH_SIZE` | int | `32` | Code inner encode sub-batch |
| `index_cache_flush_slices` | `VAULTSPEC_RAG_INDEX_CACHE_FLUSH_SLICES` | int | `8` | CUDA allocator flush cadence |
| `index_parallel_min_bytes` | `VAULTSPEC_RAG_INDEX_PARALLEL_MIN_BYTES` | int | `8388608` (8 MiB) | Auto-parallel threshold |
| `dense_backend` | `VAULTSPEC_RAG_DENSE_BACKEND` | str | `torch` | Dense encoder backend (onnx experimental) |
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
| `search_concurrency` | `VAULTSPEC_RAG_SEARCH_CONCURRENCY` | int | `16` | Search worker limiter |
| `index_job_concurrency` | `VAULTSPEC_RAG_INDEX_JOB_CONCURRENCY` | int | `4` | Index job limiter |
| `watch_enabled` | `VAULTSPEC_RAG_WATCH_ENABLED` | bool | `True` | Auto-reindex on/off; `--updates/--no-updates` |
| `watch_debounce_ms` | `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS` | int | `2000` | Debounce; `--update-delay-ms` |
| `watch_cooldown_s` | `VAULTSPEC_RAG_WATCH_COOLDOWN_S` | float | `30.0` | Per-source re-index cooldown; `--repeat-update-delay-s` |
| `preprocess_max_emitted_bytes` | `VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES` | int | `10485760` (10 MiB) | Cap on preprocessor-emitted text |
| `html_strip` | `VAULTSPEC_RAG_HTML_STRIP` | bool | `True` | Strip HTML before chunking `.html` |

Third-party env vars referenced via the enum (`config.py:90-92`): `HF_HOME`,
`HF_HUB_DOWNLOAD_TIMEOUT`, `DISABLE_SAFETENSORS_CONVERSION`. Also referenced as
bare strings: `VAULTSPEC_RAG_SEARCH_TIMEOUT` (search/MCP daemon timeout, default
300s — `mcp/_tools.py:29`, `cli/_search.py:695`), `HF_HUB_DISABLE_PROGRESS_BARS`,
`TRANSFORMERS_NO_ADVISORY_WARNINGS`, `TRANSFORMERS_VERBOSITY`
(`cli/_search.py:43-45`).

**Stale vars** (NOT in this code, drop from old docs): there is no separate
"watch reconfigure" env; tuning is via the three `VAULTSPEC_RAG_WATCH*` vars.

---

## 11. JSON envelope and error codes

### Envelope (`cli/_render.py:37-63`)

`_emit_json(ok, command, *, data, error, message, **extra)` writes one document:
```json
{"ok": <bool>, "command": "<str>", "data"?: <obj>, "error"?: "<code>",
 "message"?: "<str>", ...extra}
```
Written directly to stdout (one line + newline), bypassing Rich. Error helper
`_emit_json_error_and_exit(command, error, message, code, **extra)`
(`:66-87`) emits `{"ok": false, ...}` and raises `typer.Exit(code)`.

### Exit codes (verified across handlers)

- **0** — success.
- **1** — generic failure: GPU/torch errors, local index busy
  (`VaultStoreLockedError`), unreachable `--port` without `--allow-fallback`,
  service reported error during delegation, qdrant install FAILED, qdrant clean
  preview blocked on missing `--yes`, project unload busy/unconfirmed, install
  failed.
- **2** — invalid usage/arguments: invalid `--type`/`--prefer`/filter,
  `rebuild_requires_explicit_type`, `dry_run_requires_code`,
  `invalid_dry_run_limit`, `json_requires_yes`, invalid jobs filter
  (`invalid_filter`, `--state`/`--index`/`--started-by` values, `invalid_watch`),
  unexpected search extra args, benchmark query count < 1, project unload
  `not_found`, install torch-config ERROR/SKIPPED.
- **3** — service stopped / not running (no `service.json`): `server status`,
  `server jobs`, `server logs`, `server projects list/unload`, `server updates *`.
- **4** — service crashed/divergent (`service.json` present but a signal
  contradicts): `crashed_pid_dead`, `crashed_pid_reused`, `crashed_port_silent`,
  `crashed_heartbeat_stale`; `unreachable` for an explicit port that listens but
  is not ready (`cli/_service_lifecycle.py:399-422,1080`).

### Notable error codes (string `error` field)

`local_store_locked`, `index_locked`, `rebuild_locked`, `clean_locked`,
`status_locked`, `port_unreachable`, `service_not_running`,
`invalid_search_type`, `invalid_prefer_value`,
`invalid_filter_for_search_type`, `rebuild_requires_explicit_type`,
`dry_run_requires_code`, `invalid_dry_run_limit`, `json_requires_yes`,
`invalid_filter`, `invalid_watch`, `clean_failed`, `invalid-config`,
`preprocess-abort`, plus the service-state machine states (`stopped`,
`unreachable`, `crashed_*`). Qdrant install/clean errors surface the
`QdrantProvisionAction` (`failed`) as the `error` (`cli/_service_qdrant.py:124`).

---

## 12. `server status` + `server doctor` semantics

### `server status` (`cli/_service_lifecycle.py:1256-1421`)

Flags: `--port INT` (defaults to running service), `--json`, `--verbose`.

Four signals gathered (`_evaluate_service_signals`, `:425-468`): `service.json`
present, PID alive, port listening, heartbeat fresh — plus a derived `Server`
row and a token-match check. Derived state machine (`_compute_state`,
`:399-422`):
- `running` → exit **0** (all green).
- `stopped` (no `service.json`) → exit **3**.
- `crashed_pid_dead` / `crashed_pid_reused` / `crashed_port_silent` /
  `crashed_heartbeat_stale` → exit **4**.

Heartbeat: daemon writes `last_heartbeat` every **15s**
(`_HEARTBEAT_INTERVAL_SECONDS = 15`, `server/_state.py:83`); stale threshold
**60s** (`_HEARTBEAT_STALENESS_SECONDS = 60`, `server/_state.py:84`; mirrored in
`cli/_process.py:229`).

Human summary rows (`_render_status_summary`, `:996-1022`): `Server`,
`Requests`, `Busy`, `Address`, `Uptime`, `Queue`, `Processed jobs`, current-job
detail, and a `Next action`. `--verbose` adds Process/Heartbeat/Identity/Model/
Compute detail rows (`_render_status_detail`, `:1025-1062`). The daemon `/health`
payload feeds the Compute/Search-models/Reranking/Uptime rows.

No `service.json` with no `--port` → exit 3 (does NOT probe the port, to avoid a
multi-project false positive on the shared default port, `:1313-1343`).

### How old `info` maps now

The old consolidated `server service info` view (the `get_service_state` read) no
longer has a dedicated CLI verb. Its data is reachable through: `server status`
(operational rollup), `status` (per-project index counts via `get_service_state`,
`cli/_status.py:126-140`), `server projects list`, `server updates status`, and
the MCP `get_service_state` tool / `/service-state` route
(`api.get_service_state`, `api.py:755-838`, returns `{index, projects, watcher,
qdrant}`).

### `server doctor` — see Section 5.

---

## 13. `server updates` (formerly watcher)

Commands renamed from `watcher` to `updates` (`cli/_service_watcher.py`):
- `server updates status` (`:185`) — was `watcher status`. Shows
  "Automatic index updates: enabled/disabled", timing, and watched projects via
  the `get_watcher_state` admin call.
- `server updates start <project>` (`:240`) — was `watcher start`.
- `server updates stop <project>` (`:300`) — was `watcher stop`.
- `server updates timing <project>` (`:355`) — **was `watcher reconfigure`**.
  Calls the `reconfigure_watcher` admin endpoint with new debounce/cooldown.

### `server updates timing` flags (`:356-382`)

- positional `<project>`.
- `--update-delay-ms INT` → admin `debounce_ms` (the watch debounce knob).
- `--repeat-update-delay-s FLOAT` → admin `cooldown_s` (the per-source re-index
  cooldown). **This is the recently-renamed "repeat update delay" option** —
  current flag is `--repeat-update-delay-s` (commit "Rename repeat update delay
  option"). Same flag on `server start` (`cli/_service_lifecycle.py:192-201`).
- `--port`, `--json`.

### Knobs and defaults

- Enable/disable: `watch_enabled` (default `True`, env
  `VAULTSPEC_RAG_WATCH_ENABLED`); the sole disable. `server start --no-updates`
  sets it off for the daemon (`cli/_process.py:346-347`).
- Debounce: `watch_debounce_ms` default `2000` (env `..._WATCH_DEBOUNCE_MS`,
  flag `--update-delay-ms`).
- Cooldown: `watch_cooldown_s` default `30.0` (env `..._WATCH_COOLDOWN_S`, flag
  `--repeat-update-delay-s`). `0` on either means "no delay", not "disabled".

---

## 14. MCP tools

Server: `vaultspec-search-mcp` (stdio binary) / `server/_main.py:main`. The same
MCP app is mounted on the HTTP daemon at **`/mcp/`** (with a no-redirect wrapper
rewriting `/mcp`→`/mcp/`, `server/_main.py:109-135`). `/health` is ungated; the
read-only HTTP routes are token-gated (Section 11/15).

### Tool list (current)

Search/index tools (`mcp/_tools.py`):
- `search_vault(query, top_k=5, doc_type?, feature?, date?, tag?, like_ids?,
  unlike_ids?, project_root?)` (`:94`).
- `search_codebase(query, top_k=5, language?, path?, node_type?, function_name?,
  class_name?, include_paths?, exclude_paths?, dedup_locales=False, prefer?,
  like_ids?, unlike_ids?, project_root?)` (`:124`). NOTE: MCP still uses
  `node_type` (not `structure`).
- `get_index_status(project_root?)` (`:164`).
- `get_code_file(path, project_root?)` (`:177`).
- `reindex_vault(clean=False, project_root?)` (`:194`).
- `reindex_codebase(clean=False, project_root?)` (`:211`).

Admin/watcher tools (`mcp/_admin_tools.py`):
- `list_projects()` (`:21`).
- `evict_project(root)` (`:27`) — MCP keeps the name `evict_project` (the CLI
  verb renamed to `unload`, the MCP tool did NOT).
- `get_watcher_state(project_root?)` (`:33`).
- `start_watcher(root)` (`:44`).
- `stop_watcher(root)` (`:50`).
- `reconfigure_watcher(root, debounce_ms?, cooldown_s?)` (`:121`) — MCP keeps
  `reconfigure_watcher` (CLI verb renamed to `timing`).
- `get_service_state(project_root?)` (`:56`).
- `get_logs(lines=200, job_id?, contains?)` (`:67`).
- `get_jobs(limit?, phase?, source?, trigger?, query?, failed=False, job_id?,
  since?)` (`:84`).
- `benchmark(project_root?, n_queries=20)` (`:136`).
- `quality()` (`:148`).

**There is NO `get_readiness` MCP tool.** Readiness is exposed via the CLI
`server doctor` and the `/readiness` HTTP route only.

### Resource and prompt (`mcp/_resources.py`)

- Resource `vault://{doc_id}` → full document content by stem id (`:15`).
- Prompt `analyze_feature(feature_name)` → structured analysis prompt (`:42`).

### Renames in the MCP surface

CLI `projects unload` ↔ MCP `evict_project`; CLI `updates timing` ↔ MCP
`reconfigure_watcher`. The MCP names were NOT changed.

---

## 15. Data / status directory layout

- **Index data (local mode)**: `{root}/.vault/data/search-data/qdrant/`
  (`config.py:289-291`, `store.py:442-443`). Gitignored. Sidecars
  `index_meta.json` / `code_index_meta.json` under `.vault/data/search-data/`.
- **Service runtime dir (status_dir)**: `~/.vaultspec-rag/` (override
  `VAULTSPEC_RAG_STATUS_DIR`). Contains:
  - `service.json` — daemon status file (pid, port, started_at, service_token,
    last_heartbeat, qdrant_pid/alive/port, etc.) (`cli/_service_status.py:53-59`).
  - `service.log` — rotating service log (`cli/_service_status.py:62-73`).
  - `local-only.json` — persisted backend marker (`config.py:157`).
  - `bin/qdrant/{version}/` — managed Qdrant binary + `manifest.json`
    (`qdrant_runtime/_resolve.py:103-111`).
  - `qdrant.log` — supervised Qdrant child log (`qdrant_runtime/_supervise.py:424`).
  - `qdrant-server/storage/` (+ sibling `snapshots/`) — shared multi-root server
    storage (`config.py:288`, `_supervise.py:197-200`).
- **HTTP service**: loopback `http://127.0.0.1:8766` (default). MCP at `/mcp/`,
  `/health` ungated, read-only routes token-gated (Section 11).
- Read-only HTTP routes (`server/_routes.py:1055-1072`): `/logs`, `/logs/json`,
  `/jobs`, `/metrics`, `/readiness`, `/search`, `/reindex`, `/projects`,
  `/projects/evict`, `/watcher`, `/watcher/start`, `/watcher/stop`,
  `/watcher/reconfigure`, `/service-state`, `/code-file`, `/vault-document`,
  `/benchmark`, `/quality`. (`/health` registered separately, ungated.)

---

## 16. Removed / renamed summary (old "server service" CLI → new)

Do NOT reintroduce these stale names in docs.

| Old | New | Status |
|---|---|---|
| `server service start` | `server start` | renamed (flattened) |
| `server service stop` | `server stop` | renamed |
| `server service status` | `server status` | renamed |
| `server service warmup` | `server warmup` | renamed |
| `server service info` | (removed) | use `server status` / `status` / MCP `get_service_state` |
| `server service jobs` | `server jobs` | renamed |
| `server service logs` | `server logs` | renamed |
| `server service projects list` | `server projects list` | renamed |
| `server service projects evict` | `server projects unload` | renamed (verb changed) |
| `server service watcher status` | `server updates status` | renamed (group `watcher`→`updates`) |
| `server service watcher start <root>` | `server updates start <project>` | renamed |
| `server service watcher stop <root>` | `server updates stop <project>` | renamed |
| `server service watcher reconfigure <root>` | `server updates timing <project>` | renamed (verb changed) |
| `server mcp start/stop/status` | (NOT present in this CLI) | the `server` group has no `mcp` sub-app here; the MCP/stdio server is `vaultspec-search-mcp` / `python -m vaultspec_rag.server` |
| `search --no-truncate` | (removed) | rendering no longer truncates |
| `search --node-type` | `search --structure` | CLI flag renamed (API/MCP keep `node_type`) |
| `--watch-debounce-ms` (start) | `--update-delay-ms` | renamed |
| `--watch-cooldown-s` (start) | `--repeat-update-delay-s` | renamed |
| `--watch/--no-watch` (start) | `--updates/--no-updates` | renamed |

MCP-surface note: the MCP tool names `evict_project` and `reconfigure_watcher`
were NOT renamed even though the matching CLI verbs were (`unload`, `timing`).

### New in this branch
- `server doctor`, `server qdrant {install,status,clean}`, the whole
  `qdrant_runtime` package, the supervised Qdrant child, `install` provisioning
  front door (`--provision`, `--local-only`, `--skip-torch/-models/-qdrant`),
  `--local-only`/`--qdrant`/`--qdrant-auto-provision` on `server start`, the
  `/readiness` route, `search --scores`/`--limit`/`--timeout`/`docs` alias, and
  the server-first config defaults (`qdrant_server=True`, `local_only=False`).
