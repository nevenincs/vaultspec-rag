# CLI reference

Complete reference for the `vaultspec-rag` command line; for setup see [installation.md](installation.md), for guided usage see [getting-started.md](getting-started.md) and the how-to pages.

## Related documents

- [configuration.md](configuration.md) for environment variable defaults and overrides referenced by flags below.
- [automation.md](automation.md) for the full JSON envelope contract and error codes returned when `--json` is set.
- [mcp.md](mcp.md) for stdio versus HTTP transport setup behind the MCP tools section.
- [architecture.md](architecture.md) for the concepts named in individual flag descriptions, including `project_root`, semantic search, and service mode.

Unfamiliar terms in flag descriptions are defined in the [glossary](glossary.md).

## Contents

- [Conventions](#conventions)
- [Global options](#global-options)
- [index](#index)
- [search](#search)
- [clean](#clean)
- [status](#status)
- [server mcp start](#server-mcp-start)
- [server doctor](#server-doctor)
- [server start](#server-start)
- [server service stop](#server-service-stop)
- [server service status](#server-service-status)
- [server service warmup](#server-service-warmup)
- [server service projects list](#server-service-projects-list)
- [server service projects evict](#server-service-projects-evict)
- [server service watcher status](#server-service-watcher-status)
- [server service watcher start](#server-service-watcher-start)
- [server service watcher stop](#server-service-watcher-stop)
- [server service watcher reconfigure](#server-service-watcher-reconfigure)
- [server service info](#server-service-info)
- [server service logs](#server-service-logs)
- [server service jobs](#server-service-jobs)
- [install](#install)
- [uninstall](#uninstall)
- [benchmark](#benchmark)
- [quality](#quality)
- [test](#test)
- [MCP tools](#mcp-tools)
- [Need help?](#need-help)

## Conventions

When `--json` is passed, every command writes one JSON envelope to stdout shaped `{"ok": bool, "command": str, ...}`. On success the payload appears under `data`; on failure under `error` and `message`. The full contract lives in [automation.md](automation.md).

Standard exit codes used across commands: `0` success; `1` runtime failure (GPU error, locked index, empty vault, install or uninstall failure, port unreachable without fallback); `2` invalid input or torch-config gating failure; `3` service stopped; `4` service in a `divergent` or `crashed-*` state.

## Global options

Options accepted before the subcommand on every invocation.

| Flag                   | Default                   | Description                                        |
| ---------------------- | ------------------------- | -------------------------------------------------- |
| `--target`, `-t`       | current working directory | Directory containing `.vault` and `.vaultspec`.    |
| `--verbose`, `-v`      | off                       | Enable INFO logging.                               |
| `--debug`, `-d`        | off                       | Enable DEBUG logging.                              |
| `--data-dir`           | `.vault/data/search-data` | RAG data root.                                     |
| `--qdrant-dir`         | unset                     | Qdrant storage directory relative to `--data-dir`. |
| `--index-meta`         | unset                     | Vault index metadata filename.                     |
| `--code-index-meta`    | unset                     | Code index metadata filename.                      |
| `--status-dir`         | `~/.vaultspec-rag`        | Service status directory.                          |
| `--log-file`           | unset                     | Service log filename relative to `--status-dir`.   |
| `--version`, `-V`      | off                       | Show version and exit.                             |
| `--install-completion` | off                       | Install completion for the current shell.          |
| `--show-completion`    | off                       | Show completion for the current shell.             |
| `--help`               | off                       | Show the help message and exit.                    |

## index

Index vault documents and/or codebase chunks. When `--port` is given, delegates to a running MCP server; on dead or unreachable port, hard-fails with remediation unless `--allow-fallback` is set.

| Flag               | Default | Description                                                                                           |
| ------------------ | ------- | ----------------------------------------------------------------------------------------------------- |
| `--type`           | `all`   | What to index: `vault`, `code`, or `all`.                                                             |
| `--model`          | unset   | Override the embedding model name.                                                                    |
| `--rebuild`        | off     | Drop the selected index collections before re-indexing.                                               |
| `--port`           | unset   | Port of a running MCP server for fast-path delegation.                                                |
| `--dry-run`        | off     | List files that would be indexed without indexing.                                                    |
| `--exclude`        | unset   | Ad-hoc exclusion pattern, gitignore syntax, repeatable.                                               |
| `--allow-fallback` | off     | When `--port` is given but unreachable, silently fall back to in-process indexing instead of failing. |
| `--verbose`        | off     | Re-enable HuggingFace tqdm progress bars.                                                             |
| `--json`           | off     | Emit one JSON envelope to stdout instead of a Rich table.                                             |
| `--help`           | off     | Show the help message and exit.                                                                       |

Exit codes: `0` success; `1` GPU error, locked index files, MCP-reported reindex error, or unreachable `--port` without `--allow-fallback`; `2` GPU initialization aborted by remediation path.

## search

Search for relevant context in documentation or code. When `--port` is given, delegates to a running MCP server; on dead or unreachable port, hard-fails with remediation unless `--allow-fallback` is set.

Positional argument: `QUERY` (required) - the search query text.

| Flag               | Default | Description                                                                                                         |
| ------------------ | ------- | ------------------------------------------------------------------------------------------------------------------- |
| `--type`           | `vault` | Search source: `vault` (docs) or `code` (source).                                                                   |
| `--max-results`    | `10`    | Maximum number of results to return.                                                                                |
| `--language`       | unset   | Code-search filter: programming language.                                                                           |
| `--path`           | unset   | Code-search filter: exact project-relative file path (KEYWORD match).                                               |
| `--include-path`   | unset   | Code-search filter: repeatable fnmatch glob; keep results whose project-relative path matches at least one pattern. |
| `--exclude-path`   | unset   | Code-search filter: repeatable fnmatch glob; drop results whose project-relative path matches any pattern.          |
| `--dedup-locales`  | off     | Code-search post-process: collapse near-tie locale variants into one canonical result.                              |
| `--prefer`         | unset   | Code-search post-process: nudge results matching `prod`, `tests`, or `docs` up after rerank.                        |
| `--node-type`      | unset   | Code-search filter: parse-tree node type (for example `function_definition`).                                       |
| `--function-name`  | unset   | Code-search filter: function or method name.                                                                        |
| `--class-name`     | unset   | Code-search filter: class or struct name.                                                                           |
| `--doc-type`       | unset   | Vault-search filter: vault doc type (for example `adr`, `plan`).                                                    |
| `--feature`        | unset   | Vault-search filter: feature tag in kebab-case.                                                                     |
| `--date`           | unset   | Vault-search filter: exact ISO date (`yyyy-mm-dd`).                                                                 |
| `--tag`            | unset   | Vault-search filter: free-form tag without `#`.                                                                     |
| `--no-truncate`    | off     | Disable the 120-character snippet truncation in the results table.                                                  |
| `--port`           | unset   | Port of a running MCP server for fast-path delegation.                                                              |
| `--allow-fallback` | off     | When `--port` is given but unreachable, silently fall back to in-process search instead of failing.                 |
| `--verbose`        | off     | Re-enable HuggingFace tqdm progress bars during in-process model load and encode.                                   |
| `--json`           | off     | Emit one JSON envelope to stdout instead of a Rich table.                                                           |
| `--help`           | off     | Show the help message and exit.                                                                                     |

Exit codes: `0` success; `1` GPU initialization error, MCP-reported search error, or unreachable `--port` without `--allow-fallback`; `2` filter or search-type mismatch.

## clean

Drop selected index collections without re-indexing. Does not load embedding models, walk the vault, scan the codebase, or touch GPUs. Drops and re-creates the selected Qdrant collections and clears the matching metadata sidecar files.

Positional argument: `CLEAN_TYPE` (required) - `vault`, `code`, or `all`. No default.

| Flag          | Default | Description                                                                 |
| ------------- | ------- | --------------------------------------------------------------------------- |
| `--yes`, `-y` | off     | Confirm the destructive wipe without prompting.                             |
| `--json`      | off     | Emit one JSON envelope to stdout instead of a Rich table. Requires `--yes`. |
| `--help`      | off     | Show the help message and exit.                                             |

Exit codes: `0` success; `1` user declined the interactive confirmation.

## status

Show RAG engine status, storage metrics, and GPU info.

| Flag     | Default | Description                                                                                            |
| -------- | ------- | ------------------------------------------------------------------------------------------------------ |
| `--json` | off     | Emit one JSON envelope to stdout instead of a Rich table. Mirrors the MCP `get_index_status` response. |
| `--help` | off     | Show the help message and exit.                                                                        |

Table output columns: `Vault documents`, `Code chunks`, `Storage path`, `Target directory`, `VRAM (GB)`, plus backend capability rows.

Exit codes: `0` success; `1` missing GPU dependencies.

## server mcp start

Start the MCP server in the foreground over stdio. Used by MCP clients that spawn the server as a subprocess.

| Flag     | Default | Description                     |
| -------- | ------- | ------------------------------- |
| `--help` | off     | Show the help message and exit. |

Exit codes: `0` clean shutdown; `1` startup failure.

## server doctor

Report a bounded, read-only readiness snapshot for every external dependency the server-first backend needs, so a user learns what is missing before a runtime failure. Reports, per dependency, the backend in use plus torch CUDA availability, model-snapshot presence, and the Qdrant binary's resolution source and the supervised server's liveness. The same snapshot is served over HTTP at the token-gated `GET /readiness` route.

| Flag     | Default | Description                                     |
| -------- | ------- | ----------------------------------------------- |
| `--json` | off     | Emit the readiness snapshot as a JSON envelope. |
| `--help` | off     | Show the help message and exit.                 |

Exit codes: `0` success.

## server start

Start the background RAG service as a detached process. Spawns the MCP server on the given port, polls `/health` until ready, and records how the CLI can reach it. Starts in **server mode** by default (supervising the managed Qdrant child); if the Qdrant binary is missing, `start` prints the install command rather than failing opaquely.

| Flag                      | Default                          | Description                                                                                                                                                                                                           |
| ------------------------- | -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--port`                  | `8766` (or `VAULTSPEC_RAG_PORT`) | TCP port for the HTTP service.                                                                                                                                                                                        |
| `--updates/--no-updates`  | `--updates`                      | Enable/disable automatic index updates when files change.                                                                                                                                                             |
| `--update-delay-ms`       | unset (`2000`)                   | Delay before indexing a burst of file changes, in milliseconds.                                                                                                                                                       |
| `--repeat-update-delay-s` | unset (`30`)                     | Minimum wait before automatically updating a project again, in seconds.                                                                                                                                               |
| `--local-only`            | off                              | Use the on-disk local store instead of the default managed Qdrant server. First-class opt-out for CI, offline, and small-project hosts.                                                                               |
| `--qdrant/--no-qdrant`    | unset                            | Explicitly opt in to or out of the managed Qdrant server. Server mode is already the default, so `--qdrant` is redundant; use `--local-only` to select the on-disk store. Unset leaves the current setting unchanged. |
| `--qdrant-auto-provision` | off                              | Download the managed Qdrant server if it is missing. Without this flag, `start` prints the install command.                                                                                                           |
| `--help`                  | off                              | Show the help message and exit.                                                                                                                                                                                       |

The daemon inherits configuration only through the environment, so each set
flag is translated to its `VAULTSPEC_RAG_*` variable on the child process
before spawn. See [automation.md](automation.md#automatic-re-indexing-the-filesystem-watcher).

Exit codes: `0` service ready; `1` failure to start or health-check timeout.

## server service stop

Stop the background RAG service. Reads the status file, verifies the PID is alive and belongs to a vaultspec-rag process, sends `SIGTERM` on Unix or `CTRL_BREAK_EVENT` on Windows, waits briefly, and force-kills if graceful shutdown fails.

| Flag     | Default | Description                     |
| -------- | ------- | ------------------------------- |
| `--help` | off     | Show the help message and exit. |

Exit codes: `0` stopped or already absent; `1` failure to stop.

## server service status

Display the current status of the background RAG service. Gathers four signals (`service.json` present, PID alive, port listening, heartbeat fresh) and surfaces each row plus a derived `State` row.

| Flag     | Default | Description                                                                     |
| -------- | ------- | ------------------------------------------------------------------------------- |
| `--json` | off     | Emit one JSON envelope to stdout instead of a Rich table. Preserves exit codes. |
| `--help` | off     | Show the help message and exit.                                                 |

Table output rows: `Service JSON`, `PID`, `Port`, `Started`, `PID Alive`, `PID Matches Service`, `Service Token Match`, `Port Listening`, `Heartbeat`, `State`, and (when reachable) `Health`, `CUDA`, `Models loaded`, `Projects`, `Uptime`, plus backend capability rows.

Exit codes: `0` `running` (all signals green); `3` `stopped` (no `service.json`); `4` `divergent` or `crashed-*` (file present but signals contradict).

## server service warmup

Pre-download GPU model files to the HuggingFace cache. Checks CUDA availability, then downloads each of the three model repositories (dense, sparse, reranker) if not already cached. Reports per-model status.

| Flag     | Default | Description                     |
| -------- | ------- | ------------------------------- |
| `--help` | off     | Show the help message and exit. |

Exit codes: `0` success; `1` CUDA unavailable or `huggingface_hub` not installed.

## server service projects list

List active project slots on a running RAG service.

| Flag     | Default              | Description                                               |
| -------- | -------------------- | --------------------------------------------------------- |
| `--port` | running service port | MCP port.                                                 |
| `--json` | off                  | Emit one JSON envelope to stdout instead of a Rich table. |
| `--help` | off                  | Show the help message and exit.                           |

Table output columns: `Root` (project path), `Last access` (ISO timestamp), `Idle for` (seconds since last use), `Refs` (active reference count). Top-level extras shown above the table: `max_projects` and `idle_ttl_seconds`.

Exit codes: `0` success; `1` service unreachable or query failure.

## server service projects evict

Evict a project slot on a running RAG service.

Positional argument: `ROOT` (required) - project root to evict.

| Flag     | Default              | Description                                        |
| -------- | -------------------- | -------------------------------------------------- |
| `--port` | running service port | MCP port.                                          |
| `--json` | off                  | Emit one JSON envelope to stdout instead of prose. |
| `--help` | off                  | Show the help message and exit.                    |

Exit codes: `0` evicted or no-op; `1` service unreachable or eviction failure.

## server service watcher status

Show the auto-reindex watcher's configuration and the roots it is currently watching.

| Flag     | Default              | Description                                               |
| -------- | -------------------- | --------------------------------------------------------- |
| `--port` | running service port | MCP port.                                                 |
| `--json` | off                  | Emit one JSON envelope to stdout instead of a Rich table. |
| `--help` | off                  | Show the help message and exit.                           |

Reports `watch_enabled`, `debounce_ms`, `cooldown_s`, and the watched roots. Exit codes: `0` success; `3` service not running.

## server service watcher start

Eagerly start the watcher for a project root. No-op (reports `started=false`) when auto-reindex is disabled.

Positional argument: `ROOT` (required) - project root to watch.

| Flag     | Default              | Description                                        |
| -------- | -------------------- | -------------------------------------------------- |
| `--port` | running service port | MCP port.                                          |
| `--json` | off                  | Emit one JSON envelope to stdout instead of prose. |
| `--help` | off                  | Show the help message and exit.                    |

Exit codes: `0` request handled; `3` service not running.

## server service watcher stop

Stop the watcher for a project root, leaving it pull-only.

Positional argument: `ROOT` (required) - project root to stop watching.

| Flag     | Default              | Description                                        |
| -------- | -------------------- | -------------------------------------------------- |
| `--port` | running service port | MCP port.                                          |
| `--json` | off                  | Emit one JSON envelope to stdout instead of prose. |
| `--help` | off                  | Show the help message and exit.                    |

Exit codes: `0` request handled; `3` service not running.

## server service watcher reconfigure

Restart a root's watcher with new tuning values (debounce is fixed at watch construction, so reconfiguration is a stop-then-restart).

Positional argument: `ROOT` (required) - project root to reconfigure.

| Flag            | Default              | Description                                        |
| --------------- | -------------------- | -------------------------------------------------- |
| `--debounce-ms` | config default       | New debounce window in milliseconds.               |
| `--cooldown-s`  | config default       | New per-source cooldown in seconds.                |
| `--port`        | running service port | MCP port.                                          |
| `--json`        | off                  | Emit one JSON envelope to stdout instead of prose. |
| `--help`        | off                  | Show the help message and exit.                    |

Exit codes: `0` request handled; `3` service not running.

## server service info

Consolidated read-only state of the running service: per-source index counts, GPU/device, active project slots, and a watcher rollup (parity with the `get_service_state` MCP tool).

| Flag     | Default              | Description                                               |
| -------- | -------------------- | --------------------------------------------------------- |
| `--port` | running service port | MCP port.                                                 |
| `--json` | off                  | Emit one JSON envelope to stdout instead of a Rich table. |
| `--help` | off                  | Show the help message and exit.                           |

Exit codes: `0` success; `3` service not running.

## server service logs

Tail the service log. The reader spans the rotated set (`service.log`, `service.log.1`, …) and is tolerant of mid-rollover races. Parity with the `get_logs` MCP tool and the read-only `GET /logs` HTTP route.

| Flag      | Default              | Description                                        |
| --------- | -------------------- | -------------------------------------------------- |
| `--lines` | `200`                | Number of trailing lines to return.                |
| `--port`  | running service port | MCP port.                                          |
| `--json`  | off                  | Emit one JSON envelope to stdout instead of prose. |
| `--help`  | off                  | Show the help message and exit.                    |

Exit codes: `0` success; `3` service not running.

## server service jobs

Show recent and in-flight index/reindex activity from the service's in-flight registry (source, trigger, phase, timestamps). Parity with the `get_jobs` MCP tool and the read-only `GET /jobs` HTTP route.

| Flag      | Default              | Description                                          |
| --------- | -------------------- | ---------------------------------------------------- |
| `--limit` | all                  | Cap the number of (newest-first) records returned.   |
| `--port`  | running service port | MCP port.                                            |
| `--json`  | off                  | Emit one JSON envelope to stdout instead of a table. |
| `--help`  | off                  | Show the help message and exit.                      |

Exit codes: `0` success; `3` service not running.

## HTTP monitoring routes

The running service exposes read-only HTTP routes on its loopback port. `GET /health` is ungated. `GET /logs?lines=N` (text), `GET /jobs` (JSON), and `GET /metrics` (Prometheus text) require the `service_token` as a bearer (`Authorization: Bearer <token>`); the token is in `service.json` and `/health`. These are monitoring surfaces, not an authentication boundary — keep the service loopback-bound.

## install

Set up vaultspec-rag in a workspace. Creates the required workspace folders, seeds rag's bundled rules and integration files, invokes vaultspec-core's sync, and — by **default** — provisions the external dependencies the server-first backend needs: the CUDA `torch` configuration, the embedding/reranker models, and the pinned Qdrant server binary. Provisioning is opt-out and reports through the shared sync vocabulary (`created` / `updated` / `unchanged` / `skipped` / `failed`). The distribution wheel stays pure-Python; the Qdrant binary is fetched at runtime (digest-verified before extraction and execution, HTTPS host-pinned), never bundled.

| Flag                                   | Default                   | Description                                                                                                                                                                                                                         |
| -------------------------------------- | ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--target`, `-t`                       | current working directory | Workspace path.                                                                                                                                                                                                                     |
| `--upgrade`                            | off                       | Refresh bundled rules and integration files even if present.                                                                                                                                                                        |
| `--dry-run`                            | off                       | Preview changes without writing.                                                                                                                                                                                                    |
| `--force`                              | off                       | Override existing files. Also bypasses the torch-config confirmation prompt (implies `--yes` for that step). `--no-torch-config` still wins.                                                                                        |
| `--skip`                               | unset                     | Skip a component, repeatable.                                                                                                                                                                                                       |
| `--torch-config` / `--no-torch-config` | `--torch-config`          | Configure the cu130 CUDA PyTorch source in `pyproject.toml`. `--no-torch-config` takes precedence over `--force` and `--yes`.                                                                                                       |
| `--yes`, `-y`                          | off                       | Skip the torch-config confirmation prompt (required on non-TTY runs).                                                                                                                                                               |
| `--sync`                               | off                       | Run `uv sync --reinstall-package torch` after the torch configuration lands. No-ops when the patch step did not apply.                                                                                                              |
| `--provision` / `--no-provision`       | `--provision`             | Provision models and the Qdrant server binary after enrollment. `--no-provision` sets up the workspace only.                                                                                                                        |
| `--local-only`                         | off                       | Use the on-disk store instead of the supervised Qdrant server: skips the Qdrant binary download and persists the local backend so `server start` honours it. The minimal / CI / air-gapped alternative to the server-first default. |
| `--skip-torch`                         | off                       | Skip the PyTorch provisioning step (finer than `--local-only`).                                                                                                                                                                     |
| `--skip-models`                        | off                       | Skip the embedding/reranker model provisioning step.                                                                                                                                                                                |
| `--skip-qdrant`                        | off                       | Skip the Qdrant server binary provisioning step.                                                                                                                                                                                    |
| `--json`                               | off                       | Emit JSON for scripts instead of human text.                                                                                                                                                                                        |
| `--help`                               | off                       | Show the help message and exit.                                                                                                                                                                                                     |

Torch provisioning is two-phase: `install` configures the index in `pyproject.toml` and reports it as "configured, sync pending"; the GPU build lands only after a follow-up `uv sync` (or `--sync`).

Exit codes: `0` success, including torch-config terminal states `declined`, `conflict`, `absent`, and `disabled`; `1` install failure; `2` torch-config terminated in `error`, `skipped-eof`, or `skipped-non-tty`.

## uninstall

Remove vaultspec-rag enrollment from a workspace. Symmetric mirror of `install`: removes rag's bundled rule and MCP source files from `.vaultspec/rules/` and invokes vaultspec-core's sync. `.vault/` documents are always preserved. Without `--force`, returns a dry-run preview only.

| Flag             | Default                   | Description                                                     |
| ---------------- | ------------------------- | --------------------------------------------------------------- |
| `--target`, `-t` | current working directory | Workspace path.                                                 |
| `--remove-data`  | off                       | Also remove `.vault/data/` (rag's index, preserved by default). |
| `--dry-run`      | off                       | Preview changes without removing.                               |
| `--force`        | off                       | Required to execute. Uninstall is destructive.                  |
| `--skip`         | unset                     | Skip a component, repeatable.                                   |
| `--yes`, `-y`    | off                       | Skip confirmation prompts.                                      |
| `--json`         | off                       | Output result as JSON.                                          |
| `--help`         | off                       | Show the help message and exit.                                 |

Exit codes: `0` success; `1` uninstall failure.

## benchmark

Run search latency benchmarks against the indexed vault. Reports p50, p95, p99 latency, store counts, and GPU VRAM usage. Requires an indexed vault.

| Flag          | Default | Description                       |
| ------------- | ------- | --------------------------------- |
| `--n-queries` | `20`    | Number of search queries to time. |
| `--help`      | off     | Show the help message and exit.   |

Exit codes: `0` success; `1` vault empty or GPU error.

## quality

Run quality-scoring probes against a synthetic test corpus. Fails when precision falls below the configured threshold.

| Flag     | Default | Description                     |
| -------- | ------- | ------------------------------- |
| `--help` | off     | Show the help message and exit. |

Exit codes: `0` precision at or above threshold; `1` precision below threshold or GPU error.

## test

Run the test suite via pytest.

| Flag     | Default | Description                     |
| -------- | ------- | ------------------------------- |
| `--help` | off     | Show the help message and exit. |

Additional positional arguments are forwarded to pytest unchanged.

Exit codes: pytest's own exit code is propagated.

## MCP tools

The fifteen tools below are exposed by both the stdio and HTTP MCP transports. Parameters match the corresponding CLI flags where the surfaces overlap. `project_root` is required in HTTP service mode and optional in stdio mode (where it defaults to `VAULTSPEC_RAG_ROOT` or the current working directory). See [mcp.md](mcp.md) for client setup.

### search_vault

Semantic search over indexed vault documents with optional metadata filters.

| Name           | Type    | Default  | Description                            |
| -------------- | ------- | -------- | -------------------------------------- |
| `query`        | string  | required | Search query text.                     |
| `top_k`        | integer | `5`      | Maximum results to return.             |
| `doc_type`     | string  | `null`   | Vault doc type filter.                 |
| `feature`      | string  | `null`   | Feature tag filter (kebab-case).       |
| `date`         | string  | `null`   | Exact ISO date filter.                 |
| `tag`          | string  | `null`   | Free-form tag filter.                  |
| `project_root` | string  | `null`   | Workspace root; required in HTTP mode. |

Returns:

- `results`: list of ranked result items, descending by score.
- `summary`: human-readable summary string.
- `backend_capabilities`: backend concurrency capability object.

### search_codebase

Semantic search over indexed source code with optional structural and path filters.

| Name            | Type           | Default  | Description                                                      |
| --------------- | -------------- | -------- | ---------------------------------------------------------------- |
| `query`         | string         | required | Search query text.                                               |
| `top_k`         | integer        | `5`      | Maximum results to return.                                       |
| `language`      | string         | `null`   | Programming language filter.                                     |
| `path`          | string         | `null`   | Exact project-relative file path.                                |
| `node_type`     | string         | `null`   | parse-tree node type (for example `function_definition`) filter. |
| `function_name` | string         | `null`   | Function or method name filter.                                  |
| `class_name`    | string         | `null`   | Class or struct name filter.                                     |
| `include_paths` | list of string | `null`   | Repeatable fnmatch globs to keep.                                |
| `exclude_paths` | list of string | `null`   | Repeatable fnmatch globs to drop.                                |
| `dedup_locales` | boolean        | `false`  | Collapse near-tie locale variants.                               |
| `prefer`        | string         | `null`   | One of `prod`, `tests`, `docs`.                                  |
| `project_root`  | string         | `null`   | Workspace root; required in HTTP mode.                           |

Returns:

- `results`: list of ranked code result items, descending by score.
- `summary`: human-readable summary string.
- `backend_capabilities`: backend concurrency capability object.

### reindex_vault

Re-index vault documentation. Incremental by default. Invalidates the vault graph cache after indexing.

| Name           | Type    | Default | Description                            |
| -------------- | ------- | ------- | -------------------------------------- |
| `clean`        | boolean | `false` | Drop and rebuild the vault collection. |
| `project_root` | string  | `null`  | Workspace root; required in HTTP mode. |

Returns:

- `total`: total items in index after the operation.
- `added`: newly indexed items.
- `updated`: re-indexed items.
- `removed`: removed items.
- `duration_ms`: wall-clock time in milliseconds.
- `files`: number of source files processed.

### reindex_codebase

Re-index the source codebase. Incremental by default.

| Name           | Type    | Default | Description                            |
| -------------- | ------- | ------- | -------------------------------------- |
| `clean`        | boolean | `false` | Drop and rebuild the code collection.  |
| `project_root` | string  | `null`  | Workspace root; required in HTTP mode. |

Returns:

- `total`: total items in index after the operation.
- `added`: newly indexed items.
- `updated`: re-indexed items.
- `removed`: removed items.
- `duration_ms`: wall-clock time in milliseconds.
- `files`: number of source files processed.

### get_index_status

Return the current status of the RAG index and GPU hardware.

| Name           | Type   | Default | Description                            |
| -------------- | ------ | ------- | -------------------------------------- |
| `project_root` | string | `null`  | Workspace root; required in HTTP mode. |

Returns:

- `vault_count`: number of indexed vault documents.
- `code_count`: number of indexed codebase chunks.
- `storage_path`: absolute path to the Qdrant local database directory.
- `target_dir`: workspace root directory.
- `vram_gb`: total GPU VRAM in gigabytes.
- `backend_capabilities`: backend concurrency capability object.

### get_code_file

Retrieve the full content of a source file by project-relative path.

| Name           | Type   | Default  | Description                            |
| -------------- | ------ | -------- | -------------------------------------- |
| `path`         | string | required | Path relative to codebase root.        |
| `project_root` | string | `null`   | Workspace root; required in HTTP mode. |

Returns:

- File content as a string.

### list_projects

Return a snapshot of every active project slot on the running service. Registry-wide; `project_root` is accepted for signature parity and ignored.

| Name           | Type   | Default | Description                             |
| -------------- | ------ | ------- | --------------------------------------- |
| `project_root` | string | `null`  | Accepted for signature parity; ignored. |

Returns:

- `projects`: list of project slot snapshots.
- Per-slot fields: `root` (project path), `last_access_iso` (ISO timestamp), `idle_seconds` (seconds since last use), `ref_count` (active references).
- Top-level fields: `max_projects` (the soft cap from `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`), `idle_ttl_seconds` (the eviction threshold).

### evict_project

Force-evict the project slot for the given root.

| Name   | Type   | Default  | Description                                    |
| ------ | ------ | -------- | ---------------------------------------------- |
| `root` | string | required | Workspace root directory; resolved internally. |

Returns:

- `evicted` (boolean): true when the slot was dropped.
- `reason` (string): one of `forced`, `busy` (slot still has active refs), or `not_found` (no slot for that root).

### get_watcher_state

Report the filesystem-watcher configuration (`watch_enabled`, `debounce_ms`, `cooldown_s`) and which roots currently have a live watcher. Mirrors `server service watcher` on the CLI.

| Name           | Type   | Default | Description                            |
| -------------- | ------ | ------- | -------------------------------------- |
| `project_root` | string | `null`  | Workspace root; required in HTTP mode. |

Returns:

- `watch_enabled`: whether auto-reindex is enabled.
- `debounce_ms`: debounce window in milliseconds.
- `cooldown_s`: per-source cooldown in seconds.
- `roots`: list of roots with a live watcher.

### start_watcher

Eagerly start the filesystem watcher for a root. No-op (reports `started=false`) when auto-reindex is disabled. Mirrors `server service watcher start` on the CLI.

| Name   | Type   | Default  | Description                                    |
| ------ | ------ | -------- | ---------------------------------------------- |
| `root` | string | required | Workspace root directory; resolved internally. |

Returns:

- `started` (boolean): true when the watcher was started; false when auto-reindex is disabled.

### stop_watcher

Stop the filesystem watcher for a root, leaving that root pull-only. Mirrors `server service watcher stop` on the CLI.

| Name   | Type   | Default  | Description                                    |
| ------ | ------ | -------- | ---------------------------------------------- |
| `root` | string | required | Workspace root directory; resolved internally. |

Returns:

- `stopped` (boolean): true when the watcher was stopped.

### reconfigure_watcher

Restart a root's filesystem watcher with new tuning (stop, then restart). Mirrors `server service watcher reconfigure` on the CLI.

| Name          | Type    | Default  | Description                                    |
| ------------- | ------- | -------- | ---------------------------------------------- |
| `root`        | string  | required | Workspace root directory; resolved internally. |
| `debounce_ms` | integer | `null`   | New debounce window in milliseconds.           |
| `cooldown_s`  | number  | `null`   | New per-source cooldown in seconds.            |

Returns:

- `restarted` (boolean): true when the watcher was restarted with the new tuning.

### get_service_state

Consolidated read of the running service: per-source index counts, GPU/device info, project slots, and a watcher rollup. Mirrors `server service info` on the CLI.

| Name           | Type   | Default | Description                            |
| -------------- | ------ | ------- | -------------------------------------- |
| `project_root` | string | `null`  | Workspace root; required in HTTP mode. |

Returns:

- `index`: per-source index counts (vault and codebase).
- `device`: GPU/device information.
- `projects`: active project slot snapshots.
- `watcher`: watcher configuration and live-root rollup.

### get_logs

Return the tail of the service log across the rotated log set. Mirrors `server service logs` on the CLI.

| Name    | Type    | Default | Description                             |
| ------- | ------- | ------- | --------------------------------------- |
| `lines` | integer | `200`   | Number of trailing log lines to return. |

Returns:

- `lines`: list of trailing log lines across the rotated set.

### get_jobs

Return recent and in-flight index/reindex activity from the service's in-flight registry. Mirrors `server service jobs` on the CLI.

| Name    | Type    | Default | Description                       |
| ------- | ------- | ------- | --------------------------------- |
| `limit` | integer | `null`  | Maximum number of jobs to return. |

Returns:

- `jobs`: list of recent and in-flight index/reindex job records.

## Need help?

See the [Support](../README.md#support-and-help) section of the repo README.
