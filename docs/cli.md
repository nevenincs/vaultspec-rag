# CLI reference

Complete reference for the `vaultspec-rag` command line. For setup workflows see the [getting-started tutorial](getting-started.md); for search and indexing how-tos see the [search and index guide](search-and-index.md); for running the background service see the [background service guide](service-mode.md); for the storage backends see the [storage backends guide](backends.md).

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
- [test](#test)
- [server start](#server-start)
- [server stop](#server-stop)
- [server status](#server-status)
- [server doctor](#server-doctor)
- [server warmup](#server-warmup)
- [server jobs](#server-jobs)
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
- [preprocess list](#preprocess-list)
- [preprocess check](#preprocess-check)
- [preprocess run-one](#preprocess-run-one)
- [Get help](#get-help)

## Conventions

Run the CLI as `vaultspec-rag <command>` when the package is on your `PATH`. In uv-managed projects, run `uv run vaultspec-rag <command>`. The same binary also runs as `python -m vaultspec_rag`.

Most commands accept `--json` for scripting. `test`, `server stop`, and `server warmup` produce human-readable output only. When `--json` is set, the command writes one JSON envelope to stdout shaped `{"ok": bool, "command": str, ...}`: the payload appears under `data` on success and under `error` and `message` on failure. The full envelope contract lives in the [scripting and automation guide](automation.md).

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

The `test`, `server`, `install`, and `uninstall` commands skip workspace resolution; every other command resolves a workspace from `--target`.

## Exit codes

These codes are consistent across commands.

| Code | Meaning                                                                                                                                                                       |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0`  | Success.                                                                                                                                                                      |
| `1`  | Generic failure: GPU or torch error, a busy local index, an unreachable `--port` without `--allow-fallback`, a service-reported error, or a failed install or provision step. |
| `2`  | Usage error: an invalid argument, filter, or flag combination.                                                                                                                |
| `3`  | Service stopped: no `service.json` was found for the targeted service.                                                                                                        |
| `4`  | Service crashed or divergent: `service.json` is present but a signal contradicts it (dead PID, reused PID, silent port, or stale heartbeat).                                  |

Per-command exit lines below note the codes each command can return.

## index

`vaultspec-rag index`

Build or update the vault and code index.

Arguments: none.

Options:

| Flag               | Type               | Default | Description                                                                                                                        |
| ------------------ | ------------------ | ------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `--type`           | `vault\|code\|all` | `all`   | What to index. `--rebuild` scopes to this type.                                                                                    |
| `--rebuild`        | flag               | off     | Delete the selected index data before rebuilding. Requires an explicit `--type`; a bare `index --rebuild` is rejected.             |
| `--dry-run`        | flag               | off     | List the source-code files that would be indexed without indexing them. Valid only with `--type code` or the default `--type all`. |
| `--dry-run-limit`  | integer            | `50`    | Maximum file paths shown in human dry-run output. JSON output always lists all paths. Negative values are rejected.                |
| `--model`          | text               | unset   | Override the embedding model name.                                                                                                 |
| `--exclude`        | text               | unset   | Ad-hoc exclusion pattern in gitignore syntax. Repeatable. Ignored when delegating to the service.                                  |
| `--port`           | integer            | unset   | Delegate to a running service on this port.                                                                                        |
| `--allow-fallback` | flag               | off     | Index in-process when the targeted service is unreachable instead of failing.                                                      |
| `--verbose`        | flag               | off     | Show model-loading and progress output for in-process indexing.                                                                    |
| `--json`           | flag               | off     | Emit one JSON envelope to stdout.                                                                                                  |

With `--port` unset, the command auto-detects a running service and delegates with fallback. Service delegation queues an async reindex job and prints `Check progress with: vaultspec-rag server jobs`. In-process indexing is incremental unless `--rebuild` is set.

Exit/JSON: `0` on success; `1` on GPU error, a busy index, a service-reported reindex error, or an unreachable `--port` without `--allow-fallback`; `2` for `rebuild_requires_explicit_type`, `dry_run_requires_code`, or `invalid_dry_run_limit`. With `--json`, the result is one envelope on stdout.

## clean

`vaultspec-rag clean <vault|code|all>`

Delete index data without rebuilding it. Does not load models or touch the GPU; it drops and re-creates the selected collections and removes their metadata sidecars.

Arguments:

| Name         | Required | Description                                   |
| ------------ | -------- | --------------------------------------------- |
| `clean_type` | yes      | One of `vault`, `code`, or `all`. No default. |

Options:

| Flag          | Type | Default | Description                                         |
| ------------- | ---- | ------- | --------------------------------------------------- |
| `--yes`, `-y` | flag | off     | Confirm the deletion without prompting.             |
| `--json`      | flag | off     | Emit one JSON envelope to stdout. Requires `--yes`. |

Exit/JSON: `0` on success; `1` on a clean failure or a busy index; `2` when `--json` is set without `--yes` (`json_requires_yes`). With `--json`, the result is one envelope on stdout.

## search

`vaultspec-rag search <query>`

Run a hybrid search over vault documents or source code.

Arguments:

| Name    | Required | Description            |
| ------- | -------- | ---------------------- |
| `query` | yes      | The search query text. |

Options:

| Flag                       | Type                               | Default | Description                                                                     |
| -------------------------- | ---------------------------------- | ------- | ------------------------------------------------------------------------------- |
| `--type`                   | `vault\|code\|docs`                | `vault` | Search source. `docs` is an alias for `vault`.                                  |
| `--max-results`, `--limit` | integer                            | `10`    | Maximum number of results to return.                                            |
| `--scores`                 | flag                               | off     | Show numeric relevance scores on each result.                                   |
| `--language`               | text                               | unset   | Code filter: programming language.                                              |
| `--path`                   | text                               | unset   | Code filter: exact project-relative file path.                                  |
| `--include-path`           | text                               | unset   | Code filter: glob to keep matching results. Repeatable.                         |
| `--exclude-path`           | text                               | unset   | Code filter: glob to drop matching results. Repeatable.                         |
| `--structure`              | text                               | unset   | Code filter: parse-tree node type, for example `function_definition`.           |
| `--function-name`          | text                               | unset   | Code filter: function or method name.                                           |
| `--class-name`             | text                               | unset   | Code filter: class or struct name.                                              |
| `--dedup-locales`          | flag                               | off     | Code post-process: collapse near-tie locale variants into one canonical result. |
| `--prefer`                 | `production\|tests\|documentation` | unset   | Code post-process: nudge matching results up after reranking.                   |
| `--doc-type`               | text                               | unset   | Vault filter: document type, for example `adr` or `plan`.                       |
| `--feature`                | text                               | unset   | Vault filter: feature tag in kebab-case.                                        |
| `--date`                   | text                               | unset   | Vault filter: exact ISO date (`yyyy-mm-dd`).                                    |
| `--tag`                    | text                               | unset   | Vault filter: tag without the leading `#`.                                      |
| `--port`                   | integer                            | unset   | Search through the service on this port.                                        |
| `--allow-fallback`         | flag                               | off     | Search in-process when the targeted service is unreachable instead of failing.  |
| `--timeout`                | float                              | `300`   | Connection and read budget for service-handled searches, in seconds.            |
| `--verbose`                | flag                               | off     | Show model-loading and progress output for in-process search.                   |
| `--json`                   | flag                               | off     | Emit one JSON envelope to stdout.                                               |

Output is a list of readable records, each showing a rank, a location, and the matched text. Scores appear only with `--scores`. With `--port` unset, the command auto-detects a running service and routes to it with fallback; each result carries a `via` label of `service` or `in-process`.

Exit/JSON: `0` on success; `1` on GPU error, a service-reported search error, or an unreachable `--port` without `--allow-fallback`; `2` for an invalid `--type`, `--prefer`, or filter (`invalid_search_type`, `invalid_prefer_value`, `invalid_filter_for_search_type`). With `--json`, the result is one envelope on stdout.

## status

`vaultspec-rag status`

Show the project's index counts, data location, and compute device.

Arguments: none.

Options:

| Flag     | Type | Default | Description                       |
| -------- | ---- | ------- | --------------------------------- |
| `--json` | flag | off     | Emit one JSON envelope to stdout. |

Exit/JSON: `0` on success; `1` on missing GPU dependencies. With `--json`, the result is one envelope on stdout.

## install

`vaultspec-rag install`

Enroll a workspace and provision its external dependencies. Enrollment seeds the bundled rules and MCP integration and runs the vaultspec-core sync. By default, install then provisions the cu130 PyTorch source, the dense, sparse, and reranker model snapshots, and the pinned Qdrant server binary.

Arguments: none.

Options:

| Flag                                   | Type | Default                   | Description                                                                                                                     |
| -------------------------------------- | ---- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `--target`, `-t`                       | path | current working directory | Workspace path.                                                                                                                 |
| `--upgrade`                            | flag | off                       | Refresh the bundled rules and integration files even if they are present.                                                       |
| `--dry-run`                            | flag | off                       | Preview changes without writing.                                                                                                |
| `--force`                              | flag | off                       | Override existing files. Also bypasses the torch-config prompt (implies `--yes` for that step); `--no-torch-config` still wins. |
| `--skip`                               | text | unset                     | Skip an enrollment component by token. Repeatable.                                                                              |
| `--torch-config` / `--no-torch-config` | flag | `--torch-config`          | Configure the cu130 PyTorch source in `pyproject.toml`. `--no-torch-config` takes precedence over `--force` and `--yes`.        |
| `--yes`, `-y`                          | flag | off                       | Skip the PyTorch config prompt. Required for non-interactive installs unless `--no-torch-config` is set.                        |
| `--sync`                               | flag | off                       | Run `uv sync --reinstall-package torch` after the torch source is configured.                                                   |
| `--provision` / `--no-provision`       | flag | `--provision`             | Provision external dependencies after enrollment. `--no-provision` sets up the workspace only.                                  |
| `--local-only`                         | flag | off                       | Use the on-disk store: skips the Qdrant binary download and persists the local backend so a later `server start` honors it.     |
| `--skip-torch`                         | flag | off                       | Skip the PyTorch provisioning step.                                                                                             |
| `--skip-models`                        | flag | off                       | Skip the model provisioning step.                                                                                               |
| `--skip-qdrant`                        | flag | off                       | Skip the Qdrant binary provisioning step.                                                                                       |
| `--json`                               | flag | off                       | Emit a JSON report instead of human text.                                                                                       |

Torch provisioning is two-phase: install configures the source in `pyproject.toml` and reports it as `configured, sync pending`; the GPU build lands only after a follow-up `uv sync` or `--sync`. Provisioning reports through the shared sync vocabulary: `created`, `updated`, `unchanged`, `skipped`, and `failed`.

Exit/JSON: `0` on success, including the torch-config terminal states `declined`, `conflict`, `absent`, and `disabled`; `1` on install failure; `2` when torch config was requested and ended in `error`, `skipped-eof`, or `skipped-non-tty`. With `--json`, the result is one report on stdout.

## uninstall

`vaultspec-rag uninstall`

Remove vaultspec-rag enrollment from a workspace. This mirrors `install`: it removes the bundled rule and MCP source files and runs the vaultspec-core sync. Vault documents and index data are preserved unless `--remove-data` is passed.

Arguments: none.

Options:

| Flag             | Type | Default                   | Description                                                 |
| ---------------- | ---- | ------------------------- | ----------------------------------------------------------- |
| `--target`, `-t` | path | current working directory | Workspace path.                                             |
| `--remove-data`  | flag | off                       | Also remove index data under `.vault/data/`.                |
| `--dry-run`      | flag | off                       | Preview the removal without writing.                        |
| `--force`        | flag | off                       | Execute the removal. Without it, the command previews only. |
| `--skip`         | text | unset                     | Skip a component by token. Repeatable.                      |
| `--yes`, `-y`    | flag | off                       | Skip the confirmation prompt.                               |
| `--json`         | flag | off                       | Emit one JSON envelope to stdout.                           |

Exit/JSON: `0` on success; `1` on uninstall failure. With `--json`, the result is one envelope on stdout.

## test

`vaultspec-rag test [PYTEST_ARGS...]`

Run pytest over the test tree.

Arguments:

| Name          | Required | Description                                         |
| ------------- | -------- | --------------------------------------------------- |
| `pytest_args` | no       | Additional arguments forwarded to pytest unchanged. |

Options: run `vaultspec-rag test --help` for the full list. Most arguments pass straight through to pytest.

Exit/JSON: pytest's own exit code is propagated.

## server start

`vaultspec-rag server start`

Start the background search service as a detached process. The service spawns the daemon on the given port, polls `/health` until it reports `ready`, and records how the CLI can reach it. Server mode is the default: the daemon supervises the managed Qdrant child. If the Qdrant binary is missing, `start` prints the install command.

Arguments: none.

Options:

| Flag                         | Type    | Default                           | Description                                                                                                                                                    |
| ---------------------------- | ------- | --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--port`                     | integer | `8766` (env `VAULTSPEC_RAG_PORT`) | TCP port for the HTTP service.                                                                                                                                 |
| `--updates` / `--no-updates` | flag    | unset                             | Enable or disable automatic index updates when files change. Unset leaves the current setting unchanged.                                                       |
| `--update-delay-ms`          | integer | unset (`2000`)                    | Debounce before indexing a burst of file changes, in milliseconds.                                                                                             |
| `--repeat-update-delay-s`    | float   | unset (`30`)                      | Minimum wait before automatically updating a project again, in seconds.                                                                                        |
| `--local-only`               | flag    | off                               | Use the on-disk store and skip the Qdrant child.                                                                                                               |
| `--qdrant` / `--no-qdrant`   | flag    | unset                             | Opt in to or out of the managed Qdrant server. Server mode is the default, so `--qdrant` on its own has no effect. Unset leaves the current setting unchanged. |
| `--qdrant-auto-provision`    | flag    | off                               | Download the managed Qdrant server if it is missing instead of printing the install command.                                                                   |

The daemon inherits configuration only through the environment, so each set flag is translated to its `VAULTSPEC_RAG_*` variable on the child process before spawn.

Exit/JSON: `0` once the service is ready; `1` on a failure to start or a health-check timeout. A missing Qdrant binary fails with remediation that names `server qdrant install`, `--qdrant-auto-provision`, and `--local-only`.

## server stop

`vaultspec-rag server stop`

Stop the running background search service. The command reads the status file, verifies the PID is alive and belongs to a vaultspec-rag process, signals it, waits briefly, and force-kills it if graceful shutdown fails.

Arguments: none.

Options: none.

Exit: `0` when stopped or already absent; `1` on a failure to stop.

## server status

`vaultspec-rag server status`

Show an operator status summary for the background service. The command gathers four signals - `service.json` present, PID alive, port listening, and heartbeat fresh - and derives a single state. The daemon writes its heartbeat every 15 seconds; a heartbeat older than 60 seconds is stale.

Arguments: none.

Options:

| Flag        | Type    | Default              | Description                                                       |
| ----------- | ------- | -------------------- | ----------------------------------------------------------------- |
| `--port`    | integer | running service port | Target a specific service port.                                   |
| `--verbose` | flag    | off                  | Add process, heartbeat, identity, model, and compute detail rows. |
| `--json`    | flag    | off                  | Emit one JSON envelope to stdout. Preserves exit codes.           |

When no `service.json` exists and no `--port` is given, the command returns exit `3` without probing the default port.

Exit/JSON: `0` when `running` (all signals green); `3` when `stopped` (no `service.json`); `4` when crashed or divergent (`crashed_pid_dead`, `crashed_pid_reused`, `crashed_port_silent`, or `crashed_heartbeat_stale`). With `--json`, the result is one envelope on stdout.

## server doctor

`vaultspec-rag server doctor`

Report a read-only readiness snapshot for every external dependency the server-first backend needs. The command provisions nothing; it reports the backend in use plus torch CUDA availability, model-snapshot presence, and the Qdrant binary's resolution source and the supervised server's liveness. The same snapshot is served over HTTP at the token-gated `GET /readiness` route.

Arguments: none.

Options:

| Flag     | Type | Default | Description                                     |
| -------- | ---- | ------- | ----------------------------------------------- |
| `--json` | flag | off     | Emit the readiness snapshot as a JSON envelope. |

Exit/JSON: `0` when ready for requests; the report's `ready` field carries the overall verdict and each dependency carries its own status. With `--json`, the result is one envelope whose `data` holds `{ready, server_mode, dependencies}`.

## server warmup

`vaultspec-rag server warmup`

Pre-download the GPU model files to the HuggingFace cache without serving requests. The command checks CUDA availability, then downloads the dense, sparse, and reranker repositories if they are not already cached.

Arguments: none.

Options: none.

Exit: `0` on success; `1` when CUDA is unavailable or `huggingface_hub` is not installed.

## server jobs

`vaultspec-rag server jobs`

List recent and in-flight index and reindex activity from the service's in-flight registry. Output is bounded and filterable so running, failed, or related work surfaces above stale history.

Arguments: none.

Options:

| Flag              | Type    | Default              | Description                                                                        |
| ----------------- | ------- | -------------------- | ---------------------------------------------------------------------------------- |
| `--limit`         | integer | `20`                 | Maximum number of jobs to return.                                                  |
| `--state`         | text    | unset                | Filter by state: one of `active`, `waiting`, `finished`, `failed`, or `cancelled`. |
| `--index`         | text    | unset                | Filter by index source: `vault` or `code`.                                         |
| `--started-by`    | text    | unset                | Filter by trigger: `manual` or `automatic`.                                        |
| `--query`, `-q`   | text    | unset                | Match against job id, outcome, or progress.                                        |
| `--failed`        | flag    | off                  | Show only failed jobs.                                                             |
| `--job-id`        | text    | unset                | Filter to one job id.                                                              |
| `--since`         | float   | unset                | Show jobs updated within the last N seconds.                                       |
| `--port`          | integer | running service port | Target a specific service port.                                                    |
| `--json`          | flag    | off                  | Emit one JSON envelope to stdout.                                                  |
| `--watch`         | flag    | off                  | Refresh the table on an interval. Cannot combine with `--json`.                    |
| `--interval`      | float   | `2.0`                | Refresh interval for `--watch`, in seconds.                                        |
| `--refresh-count` | integer | unset                | Stop `--watch` after this many refreshes.                                          |

Exit/JSON: `0` on success; `2` on an invalid filter value (`invalid_filter`); `3` when the service is not running. With `--json`, the result is one envelope on stdout.

## server logs

`vaultspec-rag server logs`

Show a recent service activity feed. The reader spans the rotated log set (`service.log`, `service.log.1`, and so on) and tolerates mid-rollover races.

Arguments: none.

Options:

| Flag         | Type    | Default              | Description                                             |
| ------------ | ------- | -------------------- | ------------------------------------------------------- |
| `--limit`    | integer | `200`                | Number of log lines to show.                            |
| `--job-id`   | text    | unset                | Filter to lines for one job id.                         |
| `--contains` | text    | unset                | Filter to lines containing this substring.              |
| `--raw`      | flag    | off                  | Show the original log lines instead of the parsed feed. |
| `--port`     | integer | running service port | Target a specific service port.                         |
| `--json`     | flag    | off                  | Emit one JSON envelope to stdout.                       |

Exit/JSON: `0` on success; `3` when the service is not running. With `--json`, the result is one envelope on stdout.

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

Unload a project slot on a running service. This is the renamed `evict` verb. The matching MCP tool keeps the name `evict_project`.

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

Start automatic index updates for a project. This is the renamed `watcher start` verb. It is a no-op when automatic updates are disabled.

Arguments:

| Name      | Required | Description            |
| --------- | -------- | ---------------------- |
| `project` | yes      | Project root to watch. |

Options:

| Flag     | Type    | Default              | Description                       |
| -------- | ------- | -------------------- | --------------------------------- |
| `--port` | integer | running service port | Target a specific service port.   |
| `--json` | flag    | off                  | Emit one JSON envelope to stdout. |

Exit/JSON: `0` when the request is handled; `3` when the service is not running. With `--json`, the result is one envelope on stdout.

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

Change the automatic-update timing for a project. This is the renamed `watcher reconfigure` verb; it restarts the project's watcher with new debounce and cooldown values. The matching MCP tool keeps the name `reconfigure_watcher`.

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

Exit/JSON: `0` when the request is handled; `3` when the service is not running. With `--json`, the result is one envelope on stdout.

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

## Get help

See the [Support](../README.md#support-and-help) section of the repo README.
