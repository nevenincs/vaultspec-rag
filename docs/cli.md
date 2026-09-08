# vaultspec-rag CLI reference

Generated from the live command surface. Run `python -m dev.generate_cli_reference` after changing a command, argument, option, default, or help string.

## Global options

| Name | Default | Description |
| --- | --- | --- |
| `--target`, `-t` | - | Directory containing .vault and .vaultspec |
| `--verbose`, `-v` | off | Enable INFO logging |
| `--debug`, `-d` | off | Enable DEBUG logging |
| `--data-dir` | - | Index data directory (default: .vault/data/search-data) |
| `--storage-dir` | - | Index data subdirectory relative to --data-dir |
| `--status-dir` | - | Directory for service runtime files (default: ~/.vaultspec-rag) |
| `--log-file` | - | Service log filename inside --status-dir |
| `--version`, `-V` | off | Show version |
| `--install-completion` | - | Install completion for the current shell. |
| `--show-completion` | - | Show completion for the current shell, to copy it or customize the installation. |

## Commands

- [search](#search)
- [index](#index)
- [clean](#clean)
- [install](#install)
- [uninstall](#uninstall)
- [status](#status)
- [server doctor](#server-doctor)
- [server warmup](#server-warmup)
- [server jobs](#server-jobs)
- [server logs](#server-logs)
- [server preflight](#server-preflight)
- [server pause](#server-pause)
- [server resume](#server-resume)
- [server status](#server-status)
- [server reconcile](#server-reconcile)
- [server start](#server-start)
- [server stop](#server-stop)
- [server job show](#server-job-show)
- [server job pause](#server-job-pause)
- [server job resume](#server-job-resume)
- [server job stop](#server-job-stop)
- [server job retry](#server-job-retry)
- [server job delete](#server-job-delete)
- [server projects list](#server-projects-list)
- [server projects unload](#server-projects-unload)
- [server updates status](#server-updates-status)
- [server updates start](#server-updates-start)
- [server updates stop](#server-updates-stop)
- [server updates timing](#server-updates-timing)
- [server qdrant install](#server-qdrant-install)
- [server qdrant status](#server-qdrant-status)
- [server qdrant clean](#server-qdrant-clean)
- [server qdrant quarantine](#server-qdrant-quarantine)
- [server storage survey](#server-storage-survey)
- [server storage delete](#server-storage-delete)
- [server storage prune](#server-storage-prune)
- [server storage reconcile](#server-storage-reconcile)
- [server storage migrate](#server-storage-migrate)
- [server storage restore](#server-storage-restore)
- [preprocess list](#preprocess-list)
- [preprocess check](#preprocess-check)
- [preprocess run-one](#preprocess-run-one)
- [preprocess status](#preprocess-status)

## search

Search project documents or source code by meaning. Uses the running service when available. Local search runs only with an explicit mandate (--allow-fallback or configured local-only mode).

`vaultspec-rag search`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `query` | required | The search query text. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--type` | vault | Search area: vault documentation, source code, extracted documents, or all three with combined. Aliases: docs, codebase, all. |
| `--max-results`, `--limit` | 10 | Maximum number of results to show. Default 10 keeps the output focused. |
| `--language` | - | Only show code results in this programming language. |
| `--path` | - | Only show code results from this one exact project-relative path. Use --include-path to select a subtree or a glob. |
| `--include-path` | - | Only show code results whose project-relative path matches this pattern. A plain pattern matches that path and everything under it; globs are accepted. Repeatable. |
| `--exclude-path` | - | Hide code results whose project-relative path matches this pattern. A plain pattern matches that path and everything under it; globs are accepted. Repeatable. |
| `--dedup-locales`, `--no-dedup-locales` | - | Collapse matching locale files into one representative result. Defaults to the configured value (on) when not specified. |
| `--prefer` | - | Prefer one kind of code result: production, tests, or documentation. |
| `--structure` | - | Only show code results for this source-code structure. |
| `--function-name` | - | Only show code results from this function or method. |
| `--class-name` | - | Only show code results from this class or struct. |
| `--doc-type` | - | Only show document results with this type, such as 'adr' or 'plan'. |
| `--feature` | - | Only show document results for this feature tag. |
| `--date` | - | Only show document results from this date (yyyy-mm-dd). |
| `--tag` | - | Only show document results with this tag, without '#'. |
| `--source-path` | - | Only show extracted-document results from this source path. |
| `--extractor-id` | - | Only show document results emitted by this extractor. |
| `--extractor-version` | - | Only show document results from this extractor version. |
| `--locator-kind` | - | Only show document results with this locator kind. |
| `--scores` | off | Show numeric relevance scores in human search output. |
| `--port` | - | Service port (defaults to running service). |
| `--allow-fallback` | off | If the selected service is not reachable, run the search locally instead of stopping with an error. |
| `--verbose` | off | Show model loading and progress messages during local search. |
| `--json` | off | Emit JSON for scripts instead of human text. |
| `--timeout` | - | Connection and read timeout budget in seconds for searches handled by the service (default 300 seconds; override with VAULTSPEC_RAG_SEARCH_TIMEOUT). |

## index

Build or update the vault, code, and extracted-document search indexes. Uses the running service, or --borrow-gpu for explicit local GPU work.

`vaultspec-rag index`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--type` | all | What to index: vault, code, document, or combined. Aliases: docs, codebase, all. |
| `--model` | - | Override the embedding model name. |
| `--rebuild` | off | Delete the selected index data before rebuilding it. |
| `--port` | - | Service port (defaults to running service). |
| `--dry-run` | off | Show the resolved code/document admission summary without indexing. Use with --type code, document, combined, or the default all alias. |
| `--dry-run-limit` | 50 | Maximum source-code file paths to show in human dry-run output. JSON output still includes every path. |
| `--exclude` | - | Ad-hoc exclusion pattern (repeatable, gitignore syntax). |
| `--borrow-gpu` | off | Acquire a borrower lease, pause a compatible running service, then run this index command locally before resuming it. |
| `--no-preprocess` | off | Load no document-preprocessing rules for this in-process index run (VAULTSPEC_RAG_PREPROCESS=off). Applies to in-process indexing only; a running service uses the preprocess mode it was started with. |
| `--verbose` | off | Show model loading and indexing progress messages. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## clean

Delete selected index data without rebuilding it. Does not load models or use the GPU.

`vaultspec-rag clean`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `clean_type` | required | What to delete: vault, code, document, or combined/all. Required so nothing is deleted by accident. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--yes`, `-y` | off | Confirm the destructive wipe without prompting. |
| `--json` | off | Emit JSON for scripts instead of human text. Requires --yes so no prompt interrupts the JSON output. |

## install

Set up vaultspec-rag in a workspace. Creates the required workspace folders, installs bundled rules and integration files, and syncs the files used by supported tools. By default, install also provisions the external dependencies the server-first default needs - the embedding/reranker models and the pinned Qdrant server binary - and ensures the optional MCP extra so the agent-facing MCP search surface can run, and asks before changing PyTorch package configuration. Use --local-only for the minimal local backend (skips the binary), the finer --skip-torch/--skip-models/--skip-qdrant flags for partial opt-out, --no-mcp for a CLI-only workspace without the mcp dependency, and --no-provision to set up the workspace only; use --yes or --no-torch-config for non-interactive runs.

`vaultspec-rag install`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--target`, `-t` | - | Workspace path (default: current working directory). |
| `--upgrade` | off | Refresh bundled rules and integration files even if present. |
| `--dry-run` | off | Preview changes without writing. |
| `--force` | off | Override existing files. Also bypasses the torch-config confirmation prompt (implies --yes for that step). --no-torch-config still wins. |
| `--skip` | () | Skip a component (repeatable). |
| `--mode` | - | Provisioning mode: 'tool' (default, launched via uvx), 'dependency' (a runtime project dependency resolved through the project's own venv, ships in built distributions), or 'dev' (the default dev dependency group; renders like dependency but does not ship in built distributions). Auto-detected from pyproject.toml when omitted. |
| `--torch-config`, `--no-torch-config` | on | Configure the CUDA PyTorch package source in pyproject.toml. --no-torch-config takes precedence over --force / --yes. |
| `--tool-repair`, `--no-tool-repair` | on | Check whether a persistent uv tool environment holds a processor-only torch build, and report the command that repairs it. Nothing is installed or replaced by this check. --no-tool-repair skips it entirely. |
| `--torch-group` | - | Place the managed CUDA torch direct-dependency under the PEP 735 [dependency-groups].NAME surface instead of [project].dependencies, so a dev-only consumer does not leak torch into its published requirements. Defaults the group name to 'dev' when passed without a value. Omit the flag entirely to keep the historic [project].dependencies placement. The group must be enabled for the resolve (`uv sync --group NAME`) for the cu130 pin to apply. |
| `--yes`, `-y` | off | Skip the PyTorch configuration prompt. Required for non-interactive installs unless --no-torch-config is used. |
| `--sync` | off | Run `uv sync --reinstall-package torch` after PyTorch configuration changes are applied. |
| `--provision`, `--no-provision` | on | Provision external dependencies (models and the Qdrant server binary) after enrollment. On by default; --no-provision sets up the workspace only. |
| `--mcp`, `--no-mcp` | on | Enroll the agent-facing MCP search surface and reconcile its optional dependency at RAG's existing project placement. On by default; --no-mcp sets up a CLI-only workspace without the mcp dependency (and, on Windows, without pywin32). |
| `--local-only` | off | Use the on-disk store instead of the supervised Qdrant server: skips the Qdrant binary download and persists the local backend so `server start` honours it. The minimal / CI / air-gapped alternative to the server-first default. |
| `--skip-torch` | off | Skip the PyTorch provisioning step (finer than --local-only). |
| `--skip-models` | off | Skip the embedding/reranker model provisioning step. |
| `--skip-qdrant` | off | Skip the Qdrant server binary provisioning step. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## uninstall

Remove vaultspec-rag setup from a workspace. Without --force, this only previews what would be removed.

`vaultspec-rag uninstall`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--target`, `-t` | - | Workspace path (default: current working directory). |
| `--remove-data` | off | Also remove index data under .vault/data/. |
| `--dry-run` | off | Preview changes without removing. |
| `--force` | off | Required to execute. Uninstall is destructive. |
| `--skip` | () | Skip a component (repeatable). |
| `--yes`, `-y` | off | Skip confirmation prompts. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## status

Show project index counts, index data location, and compute device.

`vaultspec-rag status`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server doctor

Report readiness across two axes: installed dependencies (torch, models, qdrant binary) and the live service (a running daemon's health). A dead daemon is reported as not ready.

`vaultspec-rag server doctor`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--json` | off | Emit one structured JSON outcome. It is the readiness snapshot. |

## server warmup

Download GPU model files before they are needed. Run once before the first index to avoid model download latency at search time.

`vaultspec-rag server warmup`

### Arguments

None.

### Options

None.

## server jobs

Show recent index update activity from the running service.

`vaultspec-rag server jobs`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--limit` | 20 | Maximum number of matching jobs to show. |
| `--state` | - | Filter by job state: active, waiting, finished, failed, or cancelled. |
| `--index` | - | Filter by index type: vault or code. |
| `--started-by` | - | Filter by who started the job: manual requests or automatic updates. |
| `--query`, `-q` | - | Filter by text in job id, outcome, or progress. |
| `--failed` | off | Show only failed jobs. |
| `--job-id` | - | Show details for a job id or prefix. |
| `--since` | - | Show jobs updated within the last N seconds. |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. Always use this for scripted waits: the human summary line unconditionally contains the words 'active' and 'waiting'. |
| `--watch` | off | Open the interactive jobs interface with per-job controls. |
| `--interval` | 2.0 | Seconds between refreshes in the interactive interface. |

## server logs

Show grouped raw service and Qdrant logs live or offline.

`vaultspec-rag server logs`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--limit` | 200 | Maximum recent lines returned per selected source. |
| `--source` | all | Managed log source: service, qdrant, or all. |
| `--job-id` | - | Keep lines containing this job ID. |
| `--contains` | - | Keep lines containing this text. |
| `--port` | - | Use this live service port before reading retained local logs. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server preflight

Observe service quiescence and device capacity without authorizing GPU work.

`vaultspec-rag server preflight`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server pause

Hold the running service at safe checkpoints.

`vaultspec-rag server pause`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server resume

Release a paused service.

`vaultspec-rag server resume`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server status

Show the human operator summary for server readiness, work, and next checks.

`vaultspec-rag server status`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. Preserves exit codes 0 (running), 3 (stopped), 4 (crashed or divergent), and 5 (warming: models loading, not yet serving). |
| `--verbose` | off | Show process, heartbeat, service identity, model, and extra diagnostic details in the human output. |

## server reconcile

Wait for the running service to republish its discovery records. Non-destructive: nothing is written, deleted, stopped, or restarted. Exits 0 once discovery agrees, 1 if it does not converge in time.

`vaultspec-rag server reconcile`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--timeout` | 35.0 | Seconds to wait for convergence before reporting unresolved. |
| `--json` | off | Emit JSON for scripts instead of human text. Preserves exit codes 0 (converged) and 1 (not converged). |

## server start

Start the background search service. Defaults to the managed Qdrant server backend (server mode); pass --local-only for the on-disk store. Waits until it is ready and records how the CLI can reach it.

`vaultspec-rag server start`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | 8766 | Port for the background search service. |
| `--updates`, `--no-updates` | - | Enable or disable automatic index updates when files change (default: enabled). |
| `--update-delay-ms` | - | Delay before indexing a burst of file changes, in milliseconds. |
| `--repeat-update-delay-s` | - | Minimum wait before automatically updating a project again, in seconds. |
| `--local-only` | off | Use the on-disk local store instead of the default managed Qdrant server. This is the first-class opt-out for CI, offline, and small-project hosts. |
| `--qdrant`, `--no-qdrant` | - | Explicitly opt in to (or out of) the managed Qdrant server. Server mode is already the default, so --qdrant is redundant; use --local-only to select the on-disk store. Unset leaves the current Qdrant setting unchanged. |
| `--qdrant-auto-provision` | off | Download the managed Qdrant server if it is missing. Without this flag, start prints the install command. |
| `--no-preprocess` | off | Kill switch: the service loads no document-preprocessing rules for any root (forwards VAULTSPEC_RAG_PREPROCESS=off). |
| `--json` | off | Emit one structured JSON outcome. An already-running owned service is the success `already_running` (exit 0), so a supervising broker can attach rather than treating it as a fault. |

## server stop

Stop the background search service.

`vaultspec-rag server stop`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Stop the service answering on this port, resolving its identity from /health rather than the status file. Use when the service runs on a non-default port or the status file diverges from the running instance. |
| `--json` | off | Emit one structured JSON outcome. An already-stopped service is the success `already_stopped` (exit 0); a stop that leaves the service running (unconfirmed identity) is `identity_unconfirmed` (exit 1) in both output modes. |
| `--orphans` | off | Reap surplus vaultspec-rag daemons that lost the machine-singleton race and linger holding no port, lock, or discovery pointer, invisible to a normal stop. Confirm-then-reap, scoped to this singleton's port; the live singleton, isolated-config, and foreign-worktree daemons are always spared. |

## server job show

Show one exact job resource; human output accepts a unique prefix.

`vaultspec-rag server job show`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `job_id` | required | Exact job id or human-mode prefix. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit one structured JSON outcome. |

## server job pause

Request a cooperative pause for one job.

`vaultspec-rag server job pause`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `job_id` | required | Exact job id or human-mode prefix. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit one structured JSON outcome. |

## server job resume

Resume one paused job through reconciliation.

`vaultspec-rag server job resume`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `job_id` | required | Exact job id or human-mode prefix. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit one structured JSON outcome. |

## server job stop

Request cancellation without disabling automatic updates.

`vaultspec-rag server job stop`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `job_id` | required | Exact job id or human-mode prefix. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit one structured JSON outcome. |
| `--force` | off | Request force termination; currently rejected when unsupported. |

## server job retry

Create a linked retry for one retryable terminal job.

`vaultspec-rag server job retry`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `job_id` | required | Exact job id or human-mode prefix. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit one structured JSON outcome. |

## server job delete

Delete one terminal job from retained history.

`vaultspec-rag server job delete`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `job_id` | required | Exact job id or human-mode prefix. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit one structured JSON outcome. |

## server projects list

List projects currently loaded by the running search service.

`vaultspec-rag server projects list`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server projects unload

Unload a project from the running search service.

`vaultspec-rag server projects unload`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `project` | required | Project to unload. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server updates status

Show automatic index update settings and projects.

`vaultspec-rag server updates status`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server updates start

Start automatic index updates for a project.

`vaultspec-rag server updates start`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `project` | required | Project to keep indexed. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server updates stop

Stop automatic index updates for a project.

`vaultspec-rag server updates stop`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `project` | required | Project to stop updating automatically. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server updates timing

Change automatic index update timing.

`vaultspec-rag server updates timing`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `project` | required | Project to update timing for. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--update-delay-ms` | - | Delay before indexing a burst of file changes, in milliseconds. |
| `--repeat-update-delay-s` | - | Minimum wait before automatically updating a project again, in seconds. |
| `--port` | - | Service port (defaults to running service). |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server qdrant install

Download and verify the managed Qdrant server. If the requested version is already installed, nothing is downloaded.

`vaultspec-rag server qdrant install`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--upgrade` | off | Replace an installed Qdrant server when the managed version changed. |
| `--dry-run` | off | Preview the version, release package, download, install path, and digest without downloading or writing anything. |
| `--binary` | - | Register an operator-supplied Qdrant executable instead of downloading the managed release. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server qdrant status

Show the managed Qdrant executable, address, connection, and process.

`vaultspec-rag server qdrant status`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--port` | - | Qdrant HTTP port to check. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server qdrant clean

Delete managed Qdrant server installs. Destructive: requires --yes. --keep-current preserves the current managed version. Index data is never touched.

`vaultspec-rag server qdrant clean`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--keep-current` | off | Preserve the current managed Qdrant version. |
| `--yes` | off | Confirm deletion of managed Qdrant installs. |
| `--dry-run` | off | Preview what would be removed. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server qdrant quarantine

Move a corrupt collection out of the shared store so the server can start again. Run with no name to list collections; name one to quarantine it (requires --yes). The quarantined collection re-indexes on its next use; nothing is deleted.

`vaultspec-rag server qdrant quarantine`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `collection` | - | Collection to quarantine; omit to list the store. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--yes` | off | Confirm moving the named collection aside. |
| `--dry-run` | off | Preview the move without touching the store. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server storage survey

List stored RAG namespaces classified as live, orphaned, or unknown; --root looks up one root's collection prefix and namespace.

`vaultspec-rag server storage survey`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--json` | off | Emit JSON for scripts instead of human text. |
| `--orphaned` | off | Show only orphaned namespaces (prune candidates). |
| `--unknown` | off | Show only unattributable (unknown) namespaces. |
| `--root` | - | Narrow to one root's namespace and report its authoritative collection prefix (works even for a root not yet indexed). |
| `--fresh` | off | Force the service to recompute the survey instead of answering from its cached snapshot (slower; walks every namespace). |

## server storage delete

Delete one named RAG namespace, addressed by its r{hash}_ prefix or by --root (the sanctioned per-root teardown for harnesses).

`vaultspec-rag server storage delete`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `prefix` | - | The namespace prefix to delete (r{hash}_). |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--root` | - | Address the namespace by its source root path instead of the prefix; an already-absent namespace is a success (exit 0). |
| `--yes`, `-y` | off | Apply the deletion. |
| `--dry-run` | off | Preview without deleting. |
| `--json` | off | Emit JSON for scripts instead of human text. |
| `--allow-unknown` | off | Permit deleting a prefix the manifest cannot attribute (dangerous). |

## server storage prune

Reclaim every orphaned RAG namespace (source root gone).

`vaultspec-rag server storage prune`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--yes`, `-y` | off | Apply the prune. |
| `--dry-run` | off | Preview without deleting. |
| `--debris` | off | Also remove config-less collection dirs left behind by crashes (unloadable by the server; filesystem delete). |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server storage reconcile

Shrink existing collections to the bounded segment geometry.

`vaultspec-rag server storage reconcile`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--yes`, `-y` | off | Apply the reconcile. |
| `--dry-run` | off | Preview without changing. |
| `--limit` | 0 | Max collections to reconcile (0 = every drifted collection). |
| `--wait`, `--no-wait` | on | Wait for the optimizer to converge before reporting. With --no-wait the updates are issued and reclamation is reported by a later run, since mid-flight sizes are meaningless. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server storage migrate

Migrate a root's index between local and server backends.

`vaultspec-rag server storage migrate`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `root` | required | The workspace root whose index to migrate. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--to` | required | Target backend: 'server' or 'local'. |
| `--yes`, `-y` | off | Apply the migration. |
| `--dry-run` | off | Preview without copying. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## server storage restore

Restore an archived namespace into a named destination root. The destination must hold no collections; there is no override.

`vaultspec-rag server storage restore`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `archive` | required | Path to the archive directory holding the snapshot manifest. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--root` | required | Destination root path the restored namespace is keyed to. |
| `--yes`, `-y` | off | Apply the restore. |
| `--dry-run` | off | Preview the destination collections without writing. |
| `--json` | off | Emit JSON for scripts instead of human text. |

## preprocess list

List resolved preprocess rules for the project.

`vaultspec-rag preprocess list`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--json` | off | Emit JSON for scripts instead of human text. |

## preprocess check

Validate .vaultragpreprocess.toml and report configuration problems.

`vaultspec-rag preprocess check`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--json` | off | Emit JSON for scripts instead of human text. |

## preprocess run-one

Run the matching rule against one file (no indexing).

`vaultspec-rag preprocess run-one`

### Arguments

| Name | Default | Description |
| --- | --- | --- |
| `path` | required | Source file to preprocess. |

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--json` | off | Emit JSON for scripts instead of human text. |

## preprocess status

Report the preprocess mode, config presence, and rule count.

`vaultspec-rag preprocess status`

### Arguments

None.

### Options

| Name | Default | Description |
| --- | --- | --- |
| `--json` | off | Emit JSON for scripts instead of human text. |
