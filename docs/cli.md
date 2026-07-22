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
- [server storage survey](#server-storage-survey)
- [server storage prune](#server-storage-prune)
- [server storage reconcile](#server-storage-reconcile)
- [server storage delete](#server-storage-delete)
- [preprocess list](#preprocess-list)
- [preprocess check](#preprocess-check)
- [preprocess run-one](#preprocess-run-one)
- [preprocess status](#preprocess-status)
- [Get help](#get-help)

## Conventions

Run the CLI as `vaultspec-rag <command>` when the package is on your `PATH`. In uv-managed projects, run `uv run vaultspec-rag <command>`. The same binary also runs as `python -m vaultspec_rag`.

Most commands accept `--json` for scripting. `test` and `server warmup` produce human-readable output only. When `--json` is set, the command writes one JSON envelope to stdout shaped `{"ok": bool, "command": str, ...}`. The payload appears under `data` on success, and under `error` and `message` on failure. The full envelope contract lives in the [scripting and automation guide](automation.md).

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

| Code | Meaning                                                                                                                                                                     |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0`  | Success.                                                                                                                                                                    |
| `1`  | A generic failure such as a GPU or torch error, a busy local index, an unreachable `--port` without `--allow-fallback`, a service-reported error, or a failed install step. |
| `2`  | A usage error such as an invalid argument, filter, or flag combination.                                                                                                     |
| `3`  | Service stopped. No `service.json` was found for the targeted service.                                                                                                      |
| `4`  | Service crashed or divergent. `service.json` is present but a signal contradicts it (dead PID, reused PID, silent port, or stale heartbeat).                                |

Per-command exit lines below note the codes each command can return.

## index

`vaultspec-rag index`

Build or update the vault, code, and extracted-document search indexes.

Arguments: none.

Options:

| Flag               | Type               | Default | Description                                                                                                                                                                |
| ------------------ | ------------------ | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--type`           | `vault\|code\|document\|combined` | `all`   | What to index: vault documentation, source code, extracted documents, or all three with `combined`. Aliases: `docs`→`vault`, `codebase`→`code`, `all`→`combined`. `--rebuild` scopes to this type. |
| `--rebuild`        | flag               | off     | Delete the selected index data before rebuilding. Requires an explicit `--type`; a bare `index --rebuild` is rejected.                                                     |
| `--dry-run`        | flag               | off     | List the files that would be indexed without indexing them. Available for `--type code`, `--type document`, and `--type combined`; rejected for `--type vault`.            |
| `--dry-run-limit`  | integer            | `50`    | Maximum file paths shown in human dry-run output. JSON output always lists all paths. Negative values are rejected.                                                        |
| `--model`          | text               | unset   | Override the embedding model name.                                                                                                                                         |
| `--exclude`        | text               | unset   | Ad-hoc exclusion pattern in gitignore syntax. Repeatable. Ignored when delegating to the service.                                                                          |
| `--port`           | integer            | unset   | Delegate to a running service on this port.                                                                                                                                |
| `--allow-fallback` | flag               | off     | Index in-process when the targeted service is unreachable instead of failing.                                                                                              |
| `--no-preprocess`  | flag               | off     | For an in-process run, load no preprocess rules (`VAULTSPEC_RAG_PREPROCESS=off`). No effect when delegating to a running service, which uses the mode it was started with. |
| `--verbose`        | flag               | off     | Show model-loading and progress output for in-process indexing.                                                                                                            |
| `--json`           | flag               | off     | Emit one JSON envelope to stdout.                                                                                                                                          |

With `--port` unset, the command auto-detects a running service and delegates with fallback. Service delegation queues an async reindex job and prints `Check progress with: vaultspec-rag server jobs`. In-process indexing is incremental unless `--rebuild` is set.

Exit/JSON: `0` on success; `1` on GPU error, a busy index, a service-reported reindex error, or an unreachable `--port` without `--allow-fallback`; `2` for `rebuild_requires_explicit_type`, `dry_run_requires_supported_type`, `invalid_dry_run_limit`, or `preprocess_flags_conflict`. With `--json`, the result is one envelope on stdout.

## clean

`vaultspec-rag clean <vault|code|document|combined>`

Delete index data without rebuilding it. Does not load models or touch the GPU; it drops and re-creates the selected collections and removes their metadata sidecars.

Arguments:

| Name         | Required | Description                                   |
| ------------ | -------- | --------------------------------------------- |
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

| Flag                       | Type                               | Default | Description                                                                     |
| -------------------------- | ---------------------------------- | ------- | ------------------------------------------------------------------------------- |
| `--type`                   | `vault\|code\|document\|combined`  | `vault` | Search source: vault documentation, source code, extracted documents, or all three with `combined`. Aliases: `docs`→`vault`, `codebase`→`code`, `all`→`combined`. |
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

| Flag                                   | Type                    | Default                   | Description                                                                                                                                                                                                                                                                                                                                                                                                                                |
| -------------------------------------- | ----------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--target`, `-t`                       | path                    | current working directory | Workspace path.                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `--upgrade`                            | flag                    | off                       | Refresh the bundled rules and integration files even if they are present.                                                                                                                                                                                                                                                                                                                                                                  |
| `--dry-run`                            | flag                    | off                       | Preview changes without writing.                                                                                                                                                                                                                                                                                                                                                                                                           |
| `--force`                              | flag                    | off                       | Override existing files. Also bypasses the torch-config prompt (implies `--yes` for that step); `--no-torch-config` still wins.                                                                                                                                                                                                                                                                                                            |
| `--skip`                               | text                    | unset                     | Skip an enrollment component by token. Repeatable.                                                                                                                                                                                                                                                                                                                                                                                         |
| `--mode`                               | `tool\|dependency\|dev` | auto-detected             | Provisioning mode. `tool` (launched via uvx), `dependency` (a runtime project dependency resolved through the project's own venv; ships in built distributions), or `dev` (the default dev dependency group; renders like `dependency` but does not ship in built distributions). Auto-detected from `pyproject.toml` when omitted.                                                                                                        |
| `--torch-config` / `--no-torch-config` | flag                    | `--torch-config`          | Configure the cu130 PyTorch source in `pyproject.toml`. `--no-torch-config` takes precedence over `--force` and `--yes`.                                                                                                                                                                                                                                                                                                                   |
| `--torch-group`                        | text                    | unset                     | Place the managed cu130 torch direct dependency under the PEP 735 `[dependency-groups].NAME` surface instead of `[project].dependencies`, so a dev-only consumer does not leak torch into its published requirements. Defaults the group name to `dev` when passed without a value. Omit the flag to keep the `[project].dependencies` placement. The group must be enabled for the resolve (`uv sync --group NAME`) for the pin to apply. |
| `--yes`, `-y`                          | flag                    | off                       | Skip the PyTorch config prompt. Required for non-interactive installs unless `--no-torch-config` is set.                                                                                                                                                                                                                                                                                                                                   |
| `--sync`                               | flag                    | off                       | Run `uv sync --reinstall-package torch` after the torch source is configured.                                                                                                                                                                                                                                                                                                                                                              |
| `--provision` / `--no-provision`       | flag                    | `--provision`             | Provision external dependencies after enrollment. `--no-provision` sets up the workspace only.                                                                                                                                                                                                                                                                                                                                             |
| `--local-only`                         | flag                    | off                       | Use the on-disk store: skips the Qdrant binary download and persists the local backend so a later `server start` honors it.                                                                                                                                                                                                                                                                                                                |
| `--skip-torch`                         | flag                    | off                       | Skip the PyTorch provisioning step.                                                                                                                                                                                                                                                                                                                                                                                                        |
| `--skip-models`                        | flag                    | off                       | Skip the model provisioning step.                                                                                                                                                                                                                                                                                                                                                                                                          |
| `--skip-qdrant`                        | flag                    | off                       | Skip the Qdrant binary provisioning step.                                                                                                                                                                                                                                                                                                                                                                                                  |
| `--json`                               | flag                    | off                       | Emit a JSON report instead of human text.                                                                                                                                                                                                                                                                                                                                                                                                  |

Torch provisioning runs in two phases. Install configures the source in `pyproject.toml` and reports it as `configured, sync pending`. The GPU build lands only after a follow-up `uv sync` or `--sync`. Provisioning reports through the shared sync vocabulary, namely `created`, `updated`, `unchanged`, `skipped`, and `failed`.

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

Start the background search service as a detached process. The service spawns the daemon on the given port, polls `/health` until it reports `ready`, and records how the CLI can reach it. Server mode is the default. The daemon supervises the managed Qdrant child. If the Qdrant binary is missing, `start` prints the install command.

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

Exit/JSON: `0` once the service is ready; `1` on a failure to start or a health-check timeout. A missing Qdrant binary fails with remediation that names `server qdrant install`, `--qdrant-auto-provision`, and `--local-only`. When a target root defines preprocess rules, the command prints a notice stating whether they will run or be skipped (mode is `off`).

## server stop

`vaultspec-rag server stop`

Stop the running background search service. The command reads the status file, verifies the PID is alive and belongs to a vaultspec-rag process, signals it, waits briefly, and force-kills it if graceful shutdown fails. When no status file exists, a live machine-singleton lock holder is reclaimed (terminated) as the resident service. Every termination writes a shutdown audit line carrying the initiating process's PID, command line, and working directory, and the terminating `--json` envelopes carry the same attribution fields.

Arguments: none.

Options:

| Flag     | Type    | Default | Description                                                                                                                                                    |
| -------- | ------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--port` | integer | unset   | Stop the service answering on this port, resolving its identity from `/health` instead of the status file (for a non-default port or a divergent status file). |
| `--json` | flag    | off     | Emit one machine-readable outcome envelope per exit path.                                                                                                      |

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

Exit/JSON: `0` when `running` (all signals green); `3` when `stopped` (no `service.json`); `4` when crashed or divergent (`crashed_pid_dead`, `crashed_pid_reused`, `crashed_port_silent`, or `crashed_heartbeat_stale`). With `--json`, the result is one envelope on stdout.

## server doctor

`vaultspec-rag server doctor`

Report a read-only readiness snapshot for every external dependency server mode needs. The command provisions nothing. It reports the backend in use, torch CUDA availability, model-snapshot presence, the Qdrant binary's resolution source, and the supervised server's liveness. The same snapshot is served over HTTP at the token-gated `GET /readiness` route.

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

Show recent raw records from the resident service, supervised Qdrant, or both. The command uses the live service when available and reads retained local files after the service stops.

Arguments: none.

Options:

| Flag         | Type                       | Default                           | Description                                                  |
| ------------ | -------------------------- | --------------------------------- | ------------------------------------------------------------ |
| `--source`   | `service\|qdrant\|all`    | `all`                             | Select one managed source or keep both source groups.        |
| `--limit`    | integer                    | `200`                             | Maximum lines returned per selected source.                  |
| `--job-id`   | text                       | unset                             | Keep lines containing this job ID.                           |
| `--contains` | text                       | unset                             | Keep lines containing this text.                             |
| `--port`     | integer                    | running service, then local files | Target a port before using the local retained logs.          |
| `--json`     | flag                       | off                               | Emit one JSON envelope to stdout.                            |

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

| Flag        | Type | Default | Description                                                                            |
| ----------- | ---- | ------- | -------------------------------------------------------------------------------------- |
| `--dry-run` | flag | off     | Preview the exact target namespaces without deleting anything.                         |
| `--yes`     | flag | off     | Apply the prune. Without it the command prints the preview.                            |
| `--json`    | flag | off     | Emit one JSON envelope to stdout. Requires `--yes` (no prompt may corrupt the stream). |

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

Human output lists the `mode` (`default` or `off`), whether a config is present and valid, the rule count, and an `Effect` line summarising whether hooks will run. The `--json` envelope carries `mode`, `root`, `config_present`, `config_valid`, `rule_count`, and `would_run`.

Exit/JSON: `0` on success. With `--json`, the result is one envelope on stdout.

## Get help

See the [Support](../README.md#support-and-help) section of the repo README.
