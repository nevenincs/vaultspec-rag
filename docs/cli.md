# CLI reference

Complete reference for the `vaultspec-rag` command line. For task-oriented walkthroughs, see the guides listed under Related documents below.

## Related documents

- The [configuration reference](configuration.md) covers the environment variables and defaults referenced by the flags here.
- The [scripting and automation guide](automation.md) covers the JSON envelope contract and error codes returned when `--json` is set.
- The [architecture overview](architecture.md) explains the concepts named in flag descriptions, including project roots, semantic search, and server mode.

## Contents

- [Conventions](#conventions)
- [Global options](#global-options)
- [Exit codes](#exit-codes)
- [index](#index)
- [clean](#clean)
- [search](#search)
- [status](#status)
- [install](#install)
- [uninstall](#uninstall)
- [server start](#server-start)
- [server stop](#server-stop)
- [server status](#server-status)
- [server doctor](#server-doctor)
- [server warmup](#server-warmup)
- [server pause](#server-pause)
- [server resume](#server-resume)
- [server preflight](#server-preflight)
- [server reconcile](#server-reconcile)
- [server jobs](#server-jobs)
- [server job](#server-job)
- [server logs](#server-logs)
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
- [server storage prune](#server-storage-prune)
- [server storage reconcile](#server-storage-reconcile)
- [server storage delete](#server-storage-delete)
- [server storage migrate](#server-storage-migrate)
- [server storage restore](#server-storage-restore)
- [preprocess list](#preprocess-list)
- [preprocess check](#preprocess-check)
- [preprocess run-one](#preprocess-run-one)
- [preprocess status](#preprocess-status)
- [Get help](#get-help)

## Conventions

Run the CLI as `vaultspec-rag <command>` when the package is on your `PATH`. In uv-managed projects, run `uv run vaultspec-rag <command>`. The same binary also runs as `python -m vaultspec_rag`.

Most commands accept `--json` for scripting. `server warmup` produces human-readable output only. When `--json` is set, the command writes one JSON envelope to stdout shaped `{"ok": bool, "command": str, ...}`. The payload appears under `data` on success, and under `error` and `message` on failure. The full envelope contract lives in the [scripting and automation guide](automation.md).

RAG behavior is also configurable through `VAULTSPEC_RAG_*` environment variables. See the [configuration reference](configuration.md) for the complete inventory and defaults.

## Global options

Pass these before the subcommand. They apply to every invocation.

| Flag              | Type | Default                   | Description                                                                        |
| ----------------- | ---- | ------------------------- | ---------------------------------------------------------------------------------- |
| `--target`, `-t`  | path | current working directory | Directory containing `.vault` and `.vaultspec`.                                    |
| `--verbose`, `-v` | flag | off                       | Enable INFO logging.                                                               |
| `--debug`, `-d`   | flag | off                       | Enable DEBUG logging.                                                              |
| `--data-dir`      | text | `.vault/data/search-data` | Index data directory.                                                              |
| `--storage-dir`   | text | `qdrant`                  | Index data subdirectory relative to `--data-dir` (the local on-disk store subdir). |
| `--status-dir`    | text | `~/.vaultspec-rag`        | Service runtime directory.                                                         |
| `--log-file`      | text | `service.log`             | Service log filename inside `--status-dir`.                                        |
| `--version`, `-V` | flag | off                       | Print the version and exit.                                                        |

The `server`, `install`, and `uninstall` commands skip workspace resolution; every other command resolves a workspace from `--target`.

## Exit codes

The table lists common exit-code meanings. [install](#install),
[uninstall](#uninstall), and [server doctor](#server-doctor) have command-specific meanings.

| Code | Meaning                                                                                                                                                                     |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0`  | Success.                                                                                                                                                                    |
| `1`  | A generic failure such as a GPU or torch error, a busy local index, an unreachable `--port` without `--allow-fallback`, a service-reported error, or a failed install step. |
| `2`  | A usage error such as an invalid argument, filter, or flag combination.                                                                                                     |
| `3`  | Service stopped. No `service.json` was found for the targeted service.                                                                                                      |
| `4`  | Service crashed or divergent. `service.json` is present but a signal contradicts it (dead PID, reused PID, silent port, or stale heartbeat).                                |
| `5`  | Service warming. The daemon holds the machine lock and is loading models but is not yet serving; retry shortly.                                                             |

Per-command exit lines below note the codes each command can return.

## index

`vaultspec-rag index`

Build or update the vault, code, and extracted-document search indexes.

Arguments: none.

Options:

| Flag              | Type                              | Default | Description                                                                                                                                                                                        |
| ----------------- | --------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--type`          | `vault\|code\|document\|combined` | `all`   | What to index: vault documentation, source code, extracted documents, or all three with `combined`. Aliases: `docs`→`vault`, `codebase`→`code`, `all`→`combined`. `--rebuild` scopes to this type. |
| `--rebuild`       | flag                              | off     | Delete the selected index data before rebuilding. Requires an explicit `--type`; a bare `index --rebuild` is rejected.                                                                             |
| `--dry-run`       | flag                              | off     | List the files that would be indexed without indexing them. Available for `--type code`, `--type document`, and `--type combined`; rejected for `--type vault`.                                    |
| `--dry-run-limit` | integer                           | `50`    | Maximum file paths shown in human dry-run output. JSON output always lists all paths. Negative values are rejected.                                                                                |
| `--model`         | text                              | unset   | Override the embedding model name.                                                                                                                                                                 |
| `--exclude`       | text                              | unset   | Ad-hoc exclusion pattern in gitignore syntax. Repeatable. Ignored when delegating to the service.                                                                                                  |
| `--port`          | integer                           | unset   | Delegate to a running service on this port.                                                                                                                                                        |
| `--borrow-gpu`    | flag                              | off     | Acquire a borrower lease, pause a compatible running service, run this index locally, then resume the service.                                                                                     |
| `--no-preprocess` | flag                              | off     | For an in-process run, load no preprocess rules (`VAULTSPEC_RAG_PREPROCESS=off`). No effect when delegating to a running service, which uses the mode it was started with.                         |
| `--verbose`       | flag                              | off     | Show model-loading and progress output for in-process indexing.                                                                                                                                    |
| `--json`          | flag                              | off     | Emit one JSON envelope to stdout.                                                                                                                                                                  |

With `--port` unset, the command auto-detects a running service and delegates with fallback. Service delegation queues an async reindex job and prints `Check progress with: vaultspec-rag server jobs`. In-process indexing is incremental unless `--rebuild` is set.

Exit/JSON: `0` on success; `1` on GPU error, a busy index, a service-reported reindex error, or an unreachable service (`port_unreachable`; `index` has no in-process fallback flag); `2` for `rebuild_requires_explicit_type`, `dry_run_requires_supported_type`, `invalid_dry_run_limit`, or `preprocess_flags_conflict`. With `--json`, the result is one envelope on stdout.

## clean

`vaultspec-rag clean <vault|code|document|combined>`

Delete index data without rebuilding it. Does not load models or touch the GPU; it drops and re-creates the selected collections and removes their metadata sidecars.

Arguments:

| Name         | Required | Description                                                                                                                                                     |
| ------------ | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `clean_type` | yes      | One of `vault`, `code`, `document`, or `combined`. Aliases: `docs`→`vault`, `codebase`→`code`, `all`→`combined`. No default, so nothing is deleted by accident. |

Options:

| Flag          | Type | Default | Description                                         |
| ------------- | ---- | ------- | --------------------------------------------------- |
| `--yes`, `-y` | flag | off     | Confirm the deletion without prompting.             |
| `--json`      | flag | off     | Emit one JSON envelope to stdout. Requires `--yes`. |

Exit/JSON: `0` on success; `1` on a clean failure or a busy index; `2` when `--json` is set without `--yes` (`json_requires_yes`). With `--json`, the result is one envelope on stdout.

## search

`vaultspec-rag search <query>`

Run a hybrid search over vault documents, source code, or extracted documents.

Arguments:

| Name    | Required | Description            |
| ------- | -------- | ---------------------- |
| `query` | yes      | The search query text. |

Options:

| Flag                                    | Type                               | Default               | Description                                                                                                                                                       |
| --------------------------------------- | ---------------------------------- | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--type`                                | `vault\|code\|document\|combined`  | `vault`               | Search source: vault documentation, source code, extracted documents, or all three with `combined`. Aliases: `docs`→`vault`, `codebase`→`code`, `all`→`combined`. |
| `--max-results`, `--limit`              | integer                            | `10`                  | Maximum number of results to return.                                                                                                                              |
| `--scores`                              | flag                               | off                   | Show numeric relevance scores on each result.                                                                                                                     |
| `--language`                            | text                               | unset                 | Code filter: programming language.                                                                                                                                |
| `--path`                                | text                               | unset                 | Code filter: exact project-relative file path.                                                                                                                    |
| `--include-path`                        | text                               | unset                 | Code filter: path pattern to keep matching results; a plain pattern matches that path and everything under it. Repeatable.                                        |
| `--exclude-path`                        | text                               | unset                 | Code filter: path pattern to drop matching results; a plain pattern matches that path and everything under it. Repeatable.                                        |
| `--structure`                           | text                               | unset                 | Code filter: parse-tree node type, for example `function_definition`.                                                                                             |
| `--function-name`                       | text                               | unset                 | Code filter: function or method name.                                                                                                                             |
| `--class-name`                          | text                               | unset                 | Code filter: class or struct name.                                                                                                                                |
| `--dedup-locales`, `--no-dedup-locales` | flag                               | configured value (on) | Code post-process: collapse matching locale files into one representative result. Pass `--no-dedup-locales` to keep them all.                                     |
| `--prefer`                              | `production\|tests\|documentation` | unset                 | Code post-process: nudge matching results up after reranking.                                                                                                     |
| `--doc-type`                            | text                               | unset                 | Vault filter: document type, for example `adr` or `plan`.                                                                                                         |
| `--feature`                             | text                               | unset                 | Vault filter: feature tag in kebab-case.                                                                                                                          |
| `--date`                                | text                               | unset                 | Vault filter: exact ISO date (`yyyy-mm-dd`).                                                                                                                      |
| `--tag`                                 | text                               | unset                 | Vault filter: tag without the leading `#`.                                                                                                                        |
| `--source-path`                         | text                               | unset                 | Document filter: only extracted-document results from this source path.                                                                                           |
| `--extractor-id`                        | text                               | unset                 | Document filter: only results emitted by this extractor.                                                                                                          |
| `--extractor-version`                   | text                               | unset                 | Document filter: only results from this extractor version.                                                                                                        |
| `--locator-kind`                        | text                               | unset                 | Document filter: only results with this locator kind.                                                                                                             |
| `--port`                                | integer                            | unset                 | Search through the service on this port.                                                                                                                          |
| `--allow-fallback`                      | flag                               | off                   | Search in-process when the targeted service is unreachable instead of failing.                                                                                    |
| `--timeout`                             | float                              | `300`                 | Connection and read budget for service-handled searches, in seconds.                                                                                              |
| `--verbose`                             | flag                               | off                   | Show model-loading and progress output for in-process search.                                                                                                     |
| `--json`                                | flag                               | off                   | Emit one JSON envelope to stdout.                                                                                                                                 |

Output is a list of readable records, each showing a rank, a location, and the matched text. Scores appear only with `--scores`. With `--port` unset, the command auto-detects a running service and routes to it with fallback; each result carries a `via` label of `service` or `in-process`.

Exit/JSON: `0` on success; `1` on accelerator error, a service-reported search error, a local store already open in this run (`local_store_locked`), or an unreachable `--port` without `--allow-fallback` (`port_unreachable`); `2` for an invalid `--type`, `--prefer`, or filter (`invalid_search_type`, `invalid_prefer_value`, `invalid_filter_for_search_type`). With `--json`, the result is one envelope on stdout.

## status

`vaultspec-rag status`

Show the project's index counts, data location, and compute device.

Arguments: none.

Options:

| Flag     | Type | Default | Description                       |
| -------- | ---- | ------- | --------------------------------- |
| `--json` | flag | off     | Emit one JSON envelope to stdout. |

Exit/JSON: `0` on success; `1` when no supported accelerator is available. With `--json`, the result is one envelope on stdout. CUDA reports discrete VRAM; MPS reports unified-memory evidence and never fabricates a zero-VRAM value.

## install

`vaultspec-rag install`

Enroll a workspace and provision its external dependencies. Enrollment seeds the bundled rules and MCP integration and runs the vaultspec-core sync. By default, install then provisions the Linux/Windows cu130 PyTorch source, the dense, sparse, and reranker model snapshots, and the pinned Qdrant server binary. The source is platform-marked and inactive on macOS, where the standard PyTorch wheel supplies MPS.

Arguments: none.

Options:

| Flag                                   | Type                    | Default                   | Description                                                                                                                                                                                                                                                                                                                                                                                                                                |
| -------------------------------------- | ----------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--target`, `-t`                       | path                    | current working directory | Workspace path.                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `--upgrade`                            | flag                    | off                       | Refresh the bundled rules and integration files even if they are present.                                                                                                                                                                                                                                                                                                                                                                  |
| `--dry-run`                            | flag                    | off                       | Preview enrollment and provisioning; existing PyTorch configuration can still change.                                                                                                                                                                                                                                                                                                                                                      |
| `--force`                              | flag                    | off                       | Override existing files. Also bypasses the torch-config prompt (implies `--yes` for that step); `--no-torch-config` still wins.                                                                                                                                                                                                                                                                                                            |
| `--skip`                               | text                    | unset                     | Skip an enrollment component by token. Repeatable.                                                                                                                                                                                                                                                                                                                                                                                         |
| `--mode`                               | `tool\|dependency\|dev` | auto-detected             | Provisioning mode. `tool` (launched via uvx), `dependency` (a runtime project dependency resolved through the project's own venv; ships in built distributions), or `dev` (the default dev dependency group; renders like `dependency` but does not ship in built distributions). Auto-detected from `pyproject.toml` when omitted.                                                                                                        |
| `--torch-config` / `--no-torch-config` | flag                    | `--torch-config`          | Configure the Linux/Windows cu130 PyTorch source in `pyproject.toml`. It does not replace the standard MPS wheel on macOS. `--no-torch-config` takes precedence over `--force` and `--yes`.                                                                                                                                                                                                                                                |
| `--torch-group`                        | text                    | unset                     | Place the managed cu130 torch direct dependency under the PEP 735 `[dependency-groups].NAME` surface instead of `[project].dependencies`, so a dev-only consumer does not leak torch into its published requirements. Defaults the group name to `dev` when passed without a value. Omit the flag to keep the `[project].dependencies` placement. The group must be enabled for the resolve (`uv sync --group NAME`) for the pin to apply. |
| `--yes`, `-y`                          | flag                    | off                       | Skip the PyTorch config prompt. Required for non-interactive installs unless `--no-torch-config` is set.                                                                                                                                                                                                                                                                                                                                   |
| `--sync`                               | flag                    | off                       | Run `uv sync --reinstall-package torch` after the torch source is configured.                                                                                                                                                                                                                                                                                                                                                              |
| `--provision` / `--no-provision`       | flag                    | `--provision`             | Provision external dependencies after enrollment. `--no-provision` sets up the workspace only.                                                                                                                                                                                                                                                                                                                                             |
| `--mcp` / `--no-mcp`                   | flag                    | `--mcp`                   | Enroll the agent-facing MCP search surface and reconcile its optional dependency. `--no-mcp` sets up a CLI-only workspace without the `mcp` dependency, and on Windows without `pywin32`.                                                                                                                                                                                                                                                  |
| `--local-only`                         | flag                    | off                       | Use the on-disk store: skips the Qdrant binary download and persists the local backend so a later `server start` honors it.                                                                                                                                                                                                                                                                                                                |
| `--skip-torch`                         | flag                    | off                       | Skip the PyTorch provisioning step.                                                                                                                                                                                                                                                                                                                                                                                                        |
| `--skip-models`                        | flag                    | off                       | Skip the model provisioning step.                                                                                                                                                                                                                                                                                                                                                                                                          |
| `--skip-qdrant`                        | flag                    | off                       | Skip the Qdrant binary provisioning step.                                                                                                                                                                                                                                                                                                                                                                                                  |
| `--json`                               | flag                    | off                       | Emit a JSON report instead of human text.                                                                                                                                                                                                                                                                                                                                                                                                  |

Torch provisioning runs in two phases. Install configures the platform-marked source in `pyproject.toml` and reports it as `configured, sync pending`. A follow-up `uv sync` or `--sync` installs cu130 on Linux/Windows and the standard MPS-capable wheel on macOS. Provisioning reports through the shared sync vocabulary, namely `created`, `updated`, `unchanged`, `skipped`, and `failed`.

With existing canonical PyTorch configuration, `--dry-run` can still add a missing
direct `torch` dependency; adding `--sync` can also synchronize the project.
Use `--dry-run --no-torch-config` for a preview that leaves project configuration unchanged.

Exit codes:

- `0`: Success, including the torch-config states `declined`, `conflict`, `absent`, and `disabled`.
- `1`: Install failure.
- `2`: MCP setup failed or tool-environment PyTorch repair blocked installation.
  Also returned when requested torch configuration ends in `error`, `skipped-eof`, or `skipped-non-tty`.

With `--json`, the result is one report on stdout.

## uninstall

`vaultspec-rag uninstall`

Remove vaultspec-rag enrollment from a workspace. This removes the bundled rule and MCP source files and runs the vaultspec-core sync. Vault documents are preserved, as is index data by default.

Arguments: none.

Options:

| Flag             | Type | Default                   | Description                                                                                 |
| ---------------- | ---- | ------------------------- | ------------------------------------------------------------------------------------------- |
| `--target`, `-t` | path | current working directory | Workspace path.                                                                             |
| `--remove-data`  | flag | off                       | Delete all of `.vault/data/`, including the default local index and other components' data. |
| `--dry-run`      | flag | off                       | Preview the removal without writing.                                                        |
| `--force`        | flag | off                       | Execute the removal. Without it, the command previews only.                                 |
| `--skip`         | text | unset                     | Skip a component by token. Repeatable.                                                      |
| `--yes`, `-y`    | flag | off                       | Accepted but has no effect. Use `--force` to apply removal.                                 |
| `--json`         | flag | off                       | Emit one JSON envelope to stdout.                                                           |

Exit/JSON: `0` on success; `1` on uninstall failure; `2` on MCP cleanup failure.
With `--json`, the result is one envelope on stdout.

## server start

`vaultspec-rag server start`

Start the background search service as a detached process. The service spawns the daemon on the given port, polls `/health` until the daemon can serve, and records how the CLI can reach it. Server mode is the default. The daemon supervises the managed Qdrant child. If the Qdrant binary is missing, `start` prints the install command.

"Can serve" means the embedding models are resident and the configured vector backend is live - not that `/health` reports the literal status `ready`. The daemon also reports `degraded` for job history, such as an indexing job that failed, which says nothing about its ability to answer a search; waiting for the strict word would let a stale job failure hold the command open until the deadline. A start that completes against a degraded daemon is a success, prints the daemon's degradation reasons, and carries `health` and `degraded_reasons` in the `--json` envelope.

Progress is reported continuously while the command runs. On a terminal the current stage is shown live - the pre-flight checks, then the daemon's own cold-start phases, including a determinate model-load count - with elapsed time that advances even when the stage does not. Off a terminal the same stages are written to stderr as plain, rate-limited lines, so stdout stays the parseable result channel. `--json` suppresses progress on both streams so exactly one envelope reaches stdout.

Arguments: none.

Options:

| Flag                         | Type    | Default                           | Description                                                                                                                                                                                                |
| ---------------------------- | ------- | --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--port`                     | integer | `8766` (env `VAULTSPEC_RAG_PORT`) | TCP port for the HTTP service.                                                                                                                                                                             |
| `--updates` / `--no-updates` | flag    | unset                             | Enable or disable automatic index updates when files change. Unset leaves the current setting unchanged.                                                                                                   |
| `--update-delay-ms`          | integer | unset (`2000`)                    | Debounce before indexing a burst of file changes, in milliseconds.                                                                                                                                         |
| `--repeat-update-delay-s`    | float   | unset (`30`)                      | Minimum wait before automatically updating a project again, in seconds.                                                                                                                                    |
| `--local-only`               | flag    | off                               | Use the on-disk store and skip the Qdrant child.                                                                                                                                                           |
| `--qdrant` / `--no-qdrant`   | flag    | unset                             | Opt in to or out of the managed Qdrant server. Server mode is the default, so `--qdrant` on its own has no effect. Unset leaves the current setting unchanged.                                             |
| `--qdrant-auto-provision`    | flag    | off                               | Download the managed Qdrant server if it is missing instead of printing the install command.                                                                                                               |
| `--no-preprocess`            | flag    | off                               | Kill switch: the daemon loads no preprocess rules for any root (`VAULTSPEC_RAG_PREPROCESS=off`).                                                                                                           |
| `--json`                     | flag    | off                               | Emit one machine-readable outcome envelope per exit path. An already-running owned service is the success `already_running` (exit `0`) so a supervising broker attaches instead of treating it as a fault. |

The daemon inherits configuration only through the environment, so each set flag is translated to its `VAULTSPEC_RAG_*` variable on the child process before spawn.

Exit/JSON: `0` once the service can serve, including when it is serving but degraded; `1` on a failure to start or a health-check timeout, whose message names the last startup phase the daemon published. A missing Qdrant binary fails with remediation that names `server qdrant install`, `--qdrant-auto-provision`, and `--local-only`. When a target root defines preprocess rules, the command prints a notice stating whether they will run or be skipped (mode is `off`).

## server stop

`vaultspec-rag server stop`

Stop the running background search service. The command reads the status file, verifies the PID is alive and belongs to a vaultspec-rag process, signals it, waits briefly, and force-kills it if graceful shutdown fails. When no status file exists, a live machine-singleton lock holder is reclaimed (terminated) as the resident service. Every termination writes a shutdown audit line carrying the initiating process's PID, command line, and working directory, and the terminating `--json` envelopes carry the same attribution fields.

Arguments: none.

Options:

| Flag        | Type    | Default | Description                                                                                                                                                                                                                                                                                 |
| ----------- | ------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--port`    | integer | unset   | Stop the service answering on this port, resolving its identity from `/health` instead of the status file (for a non-default port or a divergent status file).                                                                                                                              |
| `--orphans` | flag    | off     | Also reap surplus daemons that lost the machine-singleton race and linger holding no port, lock, or discovery pointer, invisible to a normal stop. Confirm-then-reap, scoped to this singleton's port; the live singleton, isolated-config, and foreign-worktree daemons are always spared. |
| `--json`    | flag    | off     | Emit one machine-readable outcome envelope per exit path.                                                                                                                                                                                                                                   |

Exit/JSON: `0` for every satisfied outcome - `stopped`, `already_stopped` (nothing to stop; the idempotent success), `cleaned` (a stale status file for a confirmed-dead PID was removed), and `reclaimed` (a lock holder without a status file was terminated); `1` for `identity_unconfirmed`, the one failure - a live recorded process whose identity could not be confirmed is left running, in both output modes.

## server status

`vaultspec-rag server status`

Show an operator status summary for the background service. The command gathers four signals (`service.json` present, PID alive, port listening, and heartbeat fresh) and derives a single state. The daemon writes its heartbeat every 15 seconds; a heartbeat older than 60 seconds is stale.

Arguments: none.

Options:

| Flag        | Type    | Default              | Description                                                       |
| ----------- | ------- | -------------------- | ----------------------------------------------------------------- |
| `--port`    | integer | running service port | Target a specific service port.                                   |
| `--verbose` | flag    | off                  | Add process, heartbeat, identity, model, and compute detail rows. |
| `--json`    | flag    | off                  | Emit one JSON envelope to stdout. Preserves exit codes.           |

When no `service.json` exists and no `--port` is given, the command returns exit `3` without probing the default port.

Exit/JSON: `0` when `running` (all signals green); `3` when `stopped` (no `service.json`); `4` when crashed or divergent (`crashed_pid_dead`, `crashed_pid_reused`, `crashed_port_silent`, or `crashed_heartbeat_stale`); `5` when `warming` (the daemon holds the machine lock and is loading models but is not yet serving; retry shortly). With `--json`, the result is one envelope on stdout.

## server doctor

`vaultspec-rag server doctor`

Report a read-only readiness snapshot for every external dependency server mode needs. The command provisions nothing. It reports the storage backend, torch availability, the resolved compute backend (`cuda`, `mps`, or unavailable), model-snapshot presence, the Qdrant binary's resolution source, and the supervised server's liveness. It also reports a provisioning axis for the `vaultspec-rag` package itself - its declared install mode, any declared-versus-observed mode mismatch, and whether the running package meets its declared version floor. The same snapshot is served over HTTP at the token-gated `GET /readiness` route.

Arguments: none.

Options:

| Flag     | Type | Default | Description                                     |
| -------- | ---- | ------- | ----------------------------------------------- |
| `--json` | flag | off     | Emit the readiness snapshot as a JSON envelope. |

Exit/JSON: `0` when everything actionable is in order; `1` for a warning (a daemon is expected but not live, or the declared install mode does not match what is observed); `2` for an error (the running `vaultspec-rag` is below its declared version floor). The highest severity wins, and a pre-install run with no committed rag declaration stays exit `0` even when dependencies are not yet ready. The report's `ready` field carries the overall verdict and each dependency carries its own status. With `--json`, the result is one envelope whose `data` holds `{ready, status, server_mode, dependencies_ready, dependencies, service, mode}` - note `dependencies_ready` (not `ready`) is the installed-dependency flag, while `ready` is the overall verdict.

## server warmup

`vaultspec-rag server warmup`

Pre-download the accelerator model files to the HuggingFace cache without serving requests. The command requires CUDA or MPS, then downloads the dense, sparse, and reranker repositories if they are not already cached.

Arguments: none.

Options: none.

Exit: `0` on success; `1` when no supported accelerator is available, MPS CPU fallback is enabled, or `huggingface_hub` is not installed.

## server jobs

`vaultspec-rag server jobs`

List recent and in-flight index and reindex activity from the service's in-flight registry. Output is bounded and filterable so running, failed, or related work surfaces above stale history.

Arguments: none.

Options:

| Flag            | Type    | Default              | Description                                                                        |
| --------------- | ------- | -------------------- | ---------------------------------------------------------------------------------- |
| `--limit`       | integer | `20`                 | Maximum number of jobs to return.                                                  |
| `--state`       | text    | unset                | Filter by state: one of `active`, `waiting`, `finished`, `failed`, or `cancelled`. |
| `--index`       | text    | unset                | Filter by index source: `vault` or `code`.                                         |
| `--started-by`  | text    | unset                | Filter by trigger: `manual` or `automatic`.                                        |
| `--query`, `-q` | text    | unset                | Match against job id, outcome, or progress.                                        |
| `--failed`      | flag    | off                  | Show only failed jobs.                                                             |
| `--job-id`      | text    | unset                | Filter to one job id.                                                              |
| `--since`       | float   | unset                | Show jobs updated within the last N seconds.                                       |
| `--port`        | integer | running service port | Target a specific service port.                                                    |
| `--json`        | flag    | off                  | Emit one JSON envelope to stdout.                                                  |
| `--watch`       | flag    | off                  | Open the interactive interface. Cannot combine with `--json`.                      |
| `--interval`    | float   | `2.0`                | Seconds between refreshes in the interactive interface.                            |

Exit/JSON: `0` on success, including leaving the interactive interface - by `q` or by Ctrl+C, which report alike; `2` on an invalid filter value (`invalid_filter`); `3` when the service is not running. With `--json`, the result is one envelope on stdout.

### The interactive interface

`--watch` opens a full-screen interface rather than reprinting the feed. Each job
occupies one row carrying its state, operation, full project path, current step and
progress, elapsed time, and - where the service can estimate it honestly - the time
remaining. A moving indicator distinguishes a live view from a frozen one, and the
header stamps the last successful refresh so stale data is visible as stale.

Row controls act on the selected job:

| Key | Action                                      |
| --- | ------------------------------------------- |
| `p` | Pause                                       |
| `u` | Resume                                      |
| `k` | Kill (request cancellation)                 |
| `y` | Retry a terminal job                        |
| `d` | Delete a terminal job from retained history |
| `l` | Show or hide the log for the selected job   |
| `r` | Refresh now                                 |
| `q` | Quit                                        |

Each control is offered only where the selected job's own published capabilities
permit it; a control the service would refuse appears greyed rather than hidden, and
pressing it sends nothing. A control that has been requested but not yet acknowledged
renders as requested - pause and cancellation are cooperative, so the view never shows
a desired state as though it had already taken effect.

The layout follows the terminal. A wide terminal places the log beside the table; a
narrow one shows one at a time, with `l` switching between them. Column widths are
divided from the reported width, and a project path too long for its column keeps its
tail, which is the part that distinguishes one checkout from another.

The interface only reads until you press a control key: refreshes are plain reads of
the job registry, so leaving at any moment changes no job, lock, or service state.

Ctrl+C leaves the view exactly as `q` does; on an owned screen it is a way out, not an
abort of work in progress. However you leave, the interface hands the terminal back -
the alternate screen and the cursor are restored before the process ends - so the shell
you return to is the one you left.

A time estimate is shown only while a job is doing countable work and the service has
measured a steady enough rate to derive one. Queued, waiting, paused and finished jobs
show none, and an unknown estimate renders as unknown rather than as zero.

## server job

`vaultspec-rag server job <subcommand> <job-id>`

Act on one job by id - the singular `job`, distinct from the plural `server jobs` list view. Every subcommand resolves the job on the running service; human output accepts a unique id prefix, while `--json` requires an exact id. Each subcommand takes the same two options: `--port` (target a specific service port; defaults to the running service) and `--json` (emit one structured outcome).

| Subcommand        | Extra options | Description                                                                                                                                |
| ----------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `show <job-id>`   |               | Show one job's full detail.                                                                                                                |
| `pause <job-id>`  |               | Request a cooperative pause.                                                                                                               |
| `resume <job-id>` |               | Resume a paused job through reconciliation.                                                                                                |
| `stop <job-id>`   | `--force`     | Request cancellation without disabling automatic updates. `--force` requests force termination and is currently rejected when unsupported. |
| `retry <job-id>`  |               | Create a linked retry for one retryable terminal job.                                                                                      |
| `delete <job-id>` |               | Delete one terminal job from retained history.                                                                                             |

Exit/JSON: `0` on success; non-zero when the target job id is unknown or ambiguous, or the service is not running. With `--json`, each subcommand emits one envelope on stdout.

## server pause

`vaultspec-rag server pause`

Hold the running service at safe checkpoints without stopping it. In-flight work
reaches a checkpoint and waits there, so nothing races a maintenance operation.
Use it before maintenance that must not overlap indexing.

Arguments: none.

Options:

| Flag     | Type    | Default | Description                       |
| -------- | ------- | ------- | --------------------------------- |
| `--port` | integer | unset   | Target a specific service port.   |
| `--json` | flag    | off     | Emit one JSON envelope to stdout. |

Exit/JSON: `0` on success; non-zero when the service is not running. Release the
hold with [`server resume`](#server-resume).

## server resume

`vaultspec-rag server resume`

Release a service paused by [`server pause`](#server-pause) and let checkpointed
work continue.

Arguments: none.

Options:

| Flag     | Type    | Default | Description                       |
| -------- | ------- | ------- | --------------------------------- |
| `--port` | integer | unset   | Target a specific service port.   |
| `--json` | flag    | off     | Emit one JSON envelope to stdout. |

Exit/JSON: `0` on success; non-zero when the service is not running.

## server preflight

`vaultspec-rag server preflight`

Report whether the service is quiet and what capacity the device has, without
authorizing any GPU work. Reading it changes nothing, which is what separates it
from the commands that acquire a lease.

Arguments: none.

Options:

| Flag     | Type    | Default | Description                       |
| -------- | ------- | ------- | --------------------------------- |
| `--port` | integer | unset   | Target a specific service port.   |
| `--json` | flag    | off     | Emit one JSON envelope to stdout. |

Exit/JSON: `0` on success; non-zero when the service is not running.

## server reconcile

`vaultspec-rag server reconcile`

Wait for the running service to republish its discovery records. Nothing is
written, deleted, stopped, or restarted, so it is safe to run against a live
service. Reach for it when discovery looks stale and you want to know whether it
settles on its own before intervening.

Arguments: none.

Options:

| Flag        | Type  | Default | Description                                                              |
| ----------- | ----- | ------- | ------------------------------------------------------------------------ |
| `--timeout` | float | `35.0`  | Seconds to wait for convergence before reporting the records unresolved. |
| `--json`    | flag  | off     | Emit one JSON envelope to stdout. Exit codes are unchanged.              |

Exit/JSON: `0` once discovery agrees; `1` if it does not converge within the
timeout. See the [service discovery guide](service-discovery.md).

## server logs

`vaultspec-rag server logs`

Show recent raw records from the resident service, supervised Qdrant, or both. The command uses the live service when available and reads retained local files after the service stops.

Arguments: none.

Options:

| Flag         | Type                   | Default                           | Description                                           |
| ------------ | ---------------------- | --------------------------------- | ----------------------------------------------------- |
| `--source`   | `service\|qdrant\|all` | `all`                             | Select one managed source or keep both source groups. |
| `--limit`    | integer                | `200`                             | Maximum lines returned per selected source.           |
| `--job-id`   | text                   | unset                             | Keep lines containing this job ID.                    |
| `--contains` | text                   | unset                             | Keep lines containing this text.                      |
| `--port`     | integer                | running service, then local files | Target a port before using the local retained logs.   |
| `--json`     | flag                   | off                               | Emit one JSON envelope to stdout.                     |

Human output uses `[service]` and `[qdrant]` headings and preserves every returned line unchanged. With `--source all`, the service group appears first. This display order does not imply cross-source chronology.

The filters are case-insensitive and combine with AND. They search at most the latest 5,000 lines per source, then apply `--limit` to each filtered group.

With `--json`, `data` contains the selected source, the effective limit, the filters, and the source groups:

```json
{
  "ok": true,
  "command": "server.logs",
  "data": {
    "source": "all",
    "limit": 200,
    "groups": [
      {"source": "service", "lines": ["service record"]},
      {"source": "qdrant", "lines": ["qdrant record"]}
    ],
    "filters": {}
  }
}
```

`--raw` is no longer accepted because human output always preserves the original log lines.

Exit/JSON: `0` for live or local success; `1` for a live service error; `2` for an invalid option or source. Empty source groups are successful results.

## server projects list

`vaultspec-rag server projects list`

List the project slots loaded on a running service.

Arguments: none.

Options:

| Flag     | Type    | Default              | Description                       |
| -------- | ------- | -------------------- | --------------------------------- |
| `--port` | integer | running service port | Target a specific service port.   |
| `--json` | flag    | off                  | Emit one JSON envelope to stdout. |

Output lists each slot's root, last access time, idle duration, and active reference count, plus the `max_projects` cap and the idle eviction threshold.

Exit/JSON: `0` on success; `3` when the service is not running. With `--json`, the result is one envelope on stdout.

## server projects unload

`vaultspec-rag server projects unload <project>`

Unload a project slot on a running service. This is the renamed `evict` verb. The service's own admin route keeps the older name, `evict_project`; it is an HTTP route this command calls, not a tool an MCP client can reach.

Arguments:

| Name      | Required | Description             |
| --------- | -------- | ----------------------- |
| `project` | yes      | Project root to unload. |

Options:

| Flag     | Type    | Default              | Description                       |
| -------- | ------- | -------------------- | --------------------------------- |
| `--port` | integer | running service port | Target a specific service port.   |
| `--json` | flag    | off                  | Emit one JSON envelope to stdout. |

Exit/JSON: `0` when unloaded or a no-op; `1` when the slot is busy; `2` when no slot matches the root (`not_found`); `3` when the service is not running. With `--json`, the result is one envelope on stdout.

## server updates status

`vaultspec-rag server updates status`

Show the automatic index-update settings and the projects under watch. This is the renamed `watcher status` verb.

Arguments: none.

Options:

| Flag     | Type    | Default              | Description                       |
| -------- | ------- | -------------------- | --------------------------------- |
| `--port` | integer | running service port | Target a specific service port.   |
| `--json` | flag    | off                  | Emit one JSON envelope to stdout. |

Output reports whether automatic updates are enabled, the timing knobs, and the watched projects.

Exit/JSON: `0` on success; `3` when the service is not running. With `--json`, the result is one envelope on stdout.

## server updates start

`vaultspec-rag server updates start <project>`

Start automatic index updates for a project. This is the renamed `watcher start` verb.

The verb reports the state the project is actually in, never the state the service intends to reach. A project already updating automatically is a success. A start the service recorded but has not yet honoured - because the previous watcher for the same project is still stopping, or another start is still finishing - is reported as not started, with the reason and a `server updates status` follow-up; the service completes it without a further request.

Arguments:

| Name      | Required | Description            |
| --------- | -------- | ---------------------- |
| `project` | yes      | Project root to watch. |

Options:

| Flag     | Type    | Default              | Description                       |
| -------- | ------- | -------------------- | --------------------------------- |
| `--port` | integer | running service port | Target a specific service port.   |
| `--json` | flag    | off                  | Emit one JSON envelope to stdout. |

Exit/JSON: `0` when the project is updating automatically on return, whether this call started it or it already was; `1` when it is not (`updates_pending` when the service still owes the start, `updates_disabled` when automatic updates are switched off for the service, `updates_not_started` otherwise); `3` when the service is not running. With `--json`, the result is one envelope on stdout, and `data.status` names the exact state.

## server updates stop

`vaultspec-rag server updates stop <project>`

Stop automatic index updates for a project, leaving it pull-only. This is the renamed `watcher stop` verb.

Arguments:

| Name      | Required | Description                    |
| --------- | -------- | ------------------------------ |
| `project` | yes      | Project root to stop watching. |

Options:

| Flag     | Type    | Default              | Description                       |
| -------- | ------- | -------------------- | --------------------------------- |
| `--port` | integer | running service port | Target a specific service port.   |
| `--json` | flag    | off                  | Emit one JSON envelope to stdout. |

Exit/JSON: `0` when the request is handled; `3` when the service is not running. With `--json`, the result is one envelope on stdout.

## server updates timing

`vaultspec-rag server updates timing <project>`

Change the automatic-update timing for a project. This is the renamed `watcher reconfigure` verb; it restarts the project's watcher with new debounce and cooldown values. The service's admin route keeps the older name, `reconfigure_watcher`, and like the one above it is reachable over the daemon's HTTP admin surface rather than over MCP.

Arguments:

| Name      | Required | Description             |
| --------- | -------- | ----------------------- |
| `project` | yes      | Project root to retune. |

Options:

| Flag                      | Type    | Default              | Description                                                                                               |
| ------------------------- | ------- | -------------------- | --------------------------------------------------------------------------------------------------------- |
| `--update-delay-ms`       | integer | config default       | New debounce window before indexing a change burst, in milliseconds.                                      |
| `--repeat-update-delay-s` | float   | config default       | New minimum wait before re-updating the project, in seconds. A value of `0` means no delay, not disabled. |
| `--port`                  | integer | running service port | Target a specific service port.                                                                           |
| `--json`                  | flag    | off                  | Emit one JSON envelope to stdout.                                                                         |

Exit/JSON: `0` when a watcher carrying the new timing is running on return; `1` when it is not, with the same error strings and `data.status` as [server updates start](#server-updates-start) - the new timing is retained and applied once the previous watcher finishes stopping; `3` when the service is not running. With `--json`, the result is one envelope on stdout.

## server qdrant install

`vaultspec-rag server qdrant install`

Download and verify the managed Qdrant server binary. The download is HTTPS host-pinned, the SHA256 is verified against a committed digest before extraction, and the binary is re-hashed against its manifest immediately before it runs.

Arguments: none.

Options:

| Flag        | Type | Default | Description                                                                                                                                                             |
| ----------- | ---- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--upgrade` | flag | off     | Refresh the install to the pinned version even if a binary is present.                                                                                                  |
| `--dry-run` | flag | off     | Preview the action without downloading.                                                                                                                                 |
| `--binary`  | path | unset   | Register an operator-supplied executable instead of downloading. The checksum pin does not apply; the binary is recorded as `source: operator` and logged as a warning. |
| `--json`    | flag | off     | Emit one JSON envelope to stdout.                                                                                                                                       |

The human report shows the action, version, release package, download, install location, SHA256, and detail.

Exit/JSON: `0` on success; `1` when provisioning fails (`failed`). With `--json`, the result is one envelope on stdout.

## server qdrant status

`vaultspec-rag server qdrant status`

Report the managed Qdrant version, executable, address, connection, and process.

Arguments: none.

Options:

| Flag     | Type              | Default | Description                       |
| -------- | ----------------- | ------- | --------------------------------- |
| `--port` | integer (1-65535) | unset   | Probe this port for readiness.    |
| `--json` | flag              | off     | Emit one JSON envelope to stdout. |

The payload reports the pinned version, the server-mode default, the probed port and readiness, the active binary and its source, the available installs, and the recorded supervised child.

Exit/JSON: `0` on success. With `--json`, the result is one envelope on stdout.

## server qdrant clean

`vaultspec-rag server qdrant clean`

Delete managed Qdrant installs. Index data is never touched.

Arguments: none.

Options:

| Flag             | Type | Default | Description                                                                   |
| ---------------- | ---- | ------- | ----------------------------------------------------------------------------- |
| `--keep-current` | flag | off     | Preserve the pinned version and remove the rest.                              |
| `--yes`          | flag | off     | Confirm deletion. Required to delete; otherwise the command prints a preview. |
| `--dry-run`      | flag | off     | Preview the deletion without removing anything.                               |
| `--json`         | flag | off     | Emit one JSON envelope to stdout.                                             |

Exit/JSON: `0` on success or an empty preview; `1` when a preview lists targets but `--yes` was not given. With `--json`, the result is one envelope on stdout.

## server qdrant quarantine

`vaultspec-rag server qdrant quarantine [collection]`

Move a corrupt collection out of the shared managed store so the server can start again. Run with no argument to list the store's collections; name one to quarantine it. The move is reversible - the files are preserved under `quarantine/`, and nothing is deleted - and the affected root re-indexes on its next use. This is the operator escape hatch for when a supervised start cannot identify a corrupt collection automatically.

Arguments:

| Argument     | Type   | Description                                       |
| ------------ | ------ | ------------------------------------------------- |
| `collection` | string | Collection to quarantine; omit to list the store. |

Options:

| Flag        | Type | Default | Description                                                                           |
| ----------- | ---- | ------- | ------------------------------------------------------------------------------------- |
| `--yes`     | flag | off     | Confirm moving the named collection aside. Required to quarantine; otherwise refused. |
| `--dry-run` | flag | off     | Preview the move without touching the store.                                          |
| `--json`    | flag | off     | Emit JSON for scripts instead of human text.                                          |

Exit/JSON: `0` on success, a listing, or a dry-run preview; non-zero when the named collection is unknown (`unknown_collection`), `--yes` was not given (`confirmation_required`), or the move failed because the running server holds the files (`quarantine_failed`). With `--json`, the result is one `server.qdrant.quarantine` envelope on stdout.

## server storage survey

`vaultspec-rag server storage survey`

List every namespace stored in the managed Qdrant server, classified as `live` (its source root exists), `orphaned` (its recorded root is gone), `unknown` (unattributable), or `unverifiable` (its volume or share is offline), with per-namespace point counts and on-disk footprint. Service-first: a running daemon answers from its `/storage/survey` route so the CLI, MCP, and operator see one classification; without a daemon the CLI opens its own client to the managed server. A running daemon answers from its cached survey snapshot (refreshed at startup and by every maintenance cycle), so the call is fast at any namespace count; the response's `computed_at` and `source` fields report the snapshot's age, and `--fresh` forces a recompute. See the [storage and maintenance guide](storage-maintenance.md) for the classification model.

Arguments: none.

Options:

| Flag         | Type | Default | Description                                                                                                                  |
| ------------ | ---- | ------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `--orphaned` | flag | off     | Show only orphaned namespaces (prune candidates).                                                                            |
| `--unknown`  | flag | off     | Show only unattributable namespaces.                                                                                         |
| `--root`     | text | unset   | Narrow to one root's namespace and report its authoritative collection prefix as `queried_root` (works for unindexed roots). |
| `--fresh`    | flag | off     | Force the daemon to recompute the survey instead of answering from its cached snapshot (slower; walks every namespace).      |
| `--json`     | flag | off     | Emit one JSON envelope to stdout.                                                                                            |

Exit/JSON: `0` on success; `2` when server mode is off (`server_mode_required`); `3` when neither a daemon nor the managed server answers (`service_not_running`).

## server storage prune

`vaultspec-rag server storage prune`

Reclaim every orphaned namespace immediately. Manual pruning is the human-in-the-loop path: the operator is the confirmation, so no grace window applies. `unknown` and `unverifiable` namespaces are never touched. The service also reclaims orphans automatically on a schedule with time-based safety gates - see the [storage and maintenance guide](storage-maintenance.md).

Arguments: none.

Options:

| Flag        | Type | Default | Description                                                                                                                                |
| ----------- | ---- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `--dry-run` | flag | off     | Preview the exact target namespaces without deleting anything.                                                                             |
| `--yes`     | flag | off     | Apply the prune. Without it the command prints the preview.                                                                                |
| `--debris`  | flag | off     | Also remove config-less collection directories left behind by crashes. These are unloadable by the server, so this is a filesystem delete. |
| `--json`    | flag | off     | Emit one JSON envelope to stdout. Requires `--yes` (no prompt may corrupt the stream).                                                     |

Exit/JSON: `0` on success; `2` when server mode is off or `--json` lacks `--yes`; `3` when the managed server is unreachable.

## server storage reconcile

`vaultspec-rag server storage reconcile`

Shrink existing collections onto the bounded segment geometry. A collection keeps the geometry it was created with, so collections predating the bound hold far more preallocated space than they need; reconcile converges them in place, reclaiming 63-84% of each. It is non-destructive - no point is moved or deleted and the collection stays searchable - and idempotent, so a converged backend reports `already_converged` and does nothing. The service also reconciles a few collections per maintenance cycle automatically; see the [storage and maintenance guide](storage-maintenance.md).

Merging happens in the background, and a collection transiently grows before it shrinks, so the command waits for each collection to stop changing before reporting a reclaimed figure. A run that does not wait reports none at all rather than an unreliable one.

Arguments: none.

Options:

| Flag                | Type    | Default  | Description                                                                                            |
| ------------------- | ------- | -------- | ------------------------------------------------------------------------------------------------------ |
| `--dry-run`         | flag    | off      | Preview which collections would be reconciled without changing anything.                               |
| `--yes`             | flag    | off      | Apply the reconcile. Without it the command prints the preview.                                        |
| `--limit`           | integer | `0`      | Maximum collections to reconcile; `0` means every drifted collection.                                  |
| `--wait\|--no-wait` | flag    | `--wait` | Wait for convergence before reporting. `--no-wait` returns immediately and reports no reclaimed bytes. |
| `--json`            | flag    | off      | Emit one JSON envelope to stdout. Requires `--yes` (no prompt may corrupt the stream).                 |

Exit/JSON: `0` on success, including a backend with nothing to do (`status: already_converged`); `1` when a preview lists targets but `--yes` was not given; `2` when server mode is off or `--json` lacks `--yes`; `3` when the managed server is unreachable.

## server storage delete

`vaultspec-rag server storage delete PREFIX` or `vaultspec-rag server storage delete --root PATH`

Delete one named namespace (every collection sharing its `r{hash}_` prefix) and forget its manifest entry. The namespace is addressed either by its prefix or by `--root`, which resolves the path and derives the prefix through the same normalization indexing uses - the sanctioned per-root teardown for test harnesses and consumers that never learned the hash. Only a canonical `r` + 12 hex + `_` prefix is ever accepted, and an unattributable (`unknown`) prefix is refused unless `--allow-unknown` is set.

Deletion is idempotent in both addressing forms: a namespace that does not exist reports `already_absent` and exits `0` in both human and `--json` modes, so a teardown script can run unconditionally. (Earlier development builds reported this case as `status: skipped` with `reason: no_such_namespace`; scripts should match `already_absent`.)

Arguments: `PREFIX` - the namespace prefix to delete. Exactly one of `PREFIX` or `--root` must be given.

Options:

| Flag              | Type | Default | Description                                                                                                                             |
| ----------------- | ---- | ------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `--root`          | text | unset   | Address the namespace by its source root path instead of the prefix; the resolved root and derived prefix are echoed as `queried_root`. |
| `--dry-run`       | flag | off     | Preview without deleting.                                                                                                               |
| `--yes`, `-y`     | flag | off     | Apply the deletion.                                                                                                                     |
| `--allow-unknown` | flag | off     | Permit deleting a prefix the manifest cannot attribute to a root (dangerous).                                                           |
| `--json`          | flag | off     | Emit one JSON envelope to stdout. Requires `--yes`.                                                                                     |

Exit/JSON: `0` on success, an `already_absent` no-op, or a skipped target; `1` when a non-dry-run preview finds a target but `--yes` was not given; `2` when server mode is off, both/neither of `PREFIX` and `--root` were given, or `--json` lacks `--yes`; `3` when the managed server is unreachable.

## server storage migrate

`vaultspec-rag server storage migrate <root> --to <backend>`

Move one root's index between the managed server and the local on-disk store.
Switching the backend selection does not move existing data; this is what
carries it across.

Arguments:

| Name   | Required | Description                                |
| ------ | -------- | ------------------------------------------ |
| `root` | yes      | The workspace root whose index to migrate. |

Options:

| Flag          | Type            | Default  | Description                                         |
| ------------- | --------------- | -------- | --------------------------------------------------- |
| `--to`        | `server\|local` | required | Target backend.                                     |
| `--yes`, `-y` | flag            | off      | Apply the migration. Without it, nothing is copied. |
| `--dry-run`   | flag            | off      | Preview without copying.                            |
| `--json`      | flag            | off      | Emit one JSON envelope to stdout.                   |

Migration copies rather than moves, so the source data survives the run. See the
[storage and maintenance guide](storage-maintenance.md).

Exit: `0` on success, including a preview and a run with nothing to move; `2` for
a usage error such as a `--to` value that is not `server` or `local`; `3` when
the managed server is unreachable.

## server storage restore

`vaultspec-rag server storage restore <archive> --root <path>`

Restore an archived namespace into a named destination root. The destination
must hold no collections, and there is no override, so a restore can never
overwrite a live index.

Arguments:

| Name      | Required | Description                                                  |
| --------- | -------- | ------------------------------------------------------------ |
| `archive` | yes      | Path to the archive directory holding the snapshot manifest. |

Options:

| Flag          | Type | Default  | Description                                               |
| ------------- | ---- | -------- | --------------------------------------------------------- |
| `--root`      | text | required | Destination root path the restored namespace is keyed to. |
| `--yes`, `-y` | flag | off      | Apply the restore.                                        |
| `--dry-run`   | flag | off      | Preview the destination collections without writing.      |
| `--json`      | flag | off      | Emit one JSON envelope to stdout.                         |

This is the counterpart to the archives that reclamation writes before deleting
a data-bearing namespace. See the
[storage and maintenance guide](storage-maintenance.md).

Exit: `0` on success, including a preview; `2` for a usage error, which is what a
path with no archive directory at it returns; `3` when the managed server is
unreachable.

## preprocess list

`vaultspec-rag preprocess list`

Show the resolved preprocess rules from `.vaultragpreprocess.toml`.

Arguments: none.

Options:

| Flag     | Type | Default | Description                       |
| -------- | ---- | ------- | --------------------------------- |
| `--json` | flag | off     | Emit one JSON envelope to stdout. |

Exit/JSON: `0` on success. With `--json`, the result is one envelope on stdout.

## preprocess check

`vaultspec-rag preprocess check`

Validate `.vaultragpreprocess.toml`. This is the only `preprocess` verb that fails on a bad config.

Arguments: none.

Options:

| Flag     | Type | Default | Description                       |
| -------- | ---- | ------- | --------------------------------- |
| `--json` | flag | off     | Emit one JSON envelope to stdout. |

Exit/JSON: `0` when the config is valid; non-zero with `invalid-config` when it is not. With `--json`, the result is one envelope on stdout.

## preprocess run-one

`vaultspec-rag preprocess run-one <path>`

Trial-run the matching preprocess rule on one file and show the emitted units.

Arguments:

| Name   | Required | Description                                      |
| ------ | -------- | ------------------------------------------------ |
| `path` | yes      | The file to trial-run the matching rule against. |

Options:

| Flag     | Type | Default | Description                       |
| -------- | ---- | ------- | --------------------------------- |
| `--json` | flag | off     | Emit one JSON envelope to stdout. |

Exit/JSON: `0` on success. With `--json`, the result is one envelope on stdout.

## preprocess status

`vaultspec-rag preprocess status`

Report the preprocess mode, config presence, and rule count for this root, plus whether hooks would run here. There is no trust state and no OS containment - a root's rules run directly, executing with your privileges, for any root except under the `off` kill switch.

Arguments: none.

Options:

| Flag     | Type | Default | Description                       |
| -------- | ---- | ------- | --------------------------------- |
| `--json` | flag | off     | Emit one JSON envelope to stdout. |

Human output lists the `mode` (`default` or `off`), whether a config is present and valid, the rule count, and an `Effect` line summarising whether hooks will run. The `--json` envelope carries twelve fields: `mode`, `root`, `config_present`, `config_valid`, `config_error_kind`, `config_error_message`, `rule_count`, `schema_version`, `targets`, `extractor_versions`, `path_independent_rules`, and `would_run`. On a root with no config the two error fields are `null`, `targets` and `extractor_versions` are empty, and `would_run` is `false`.

Exit/JSON: `0` on success. With `--json`, the result is one envelope on stdout.

## Get help

[Report a problem](../README.md#status-and-help).
