# CLI reference

Canonical surface for the `vaultspec-rag` command line. Every command shares the same JSON envelope shape and exit-code conventions described under [Global options](#global-options).

## Contents

- [Global options](#global-options)
- [index](#index)
- [search](#search)
- [clean](#clean)
- [status](#status)
- [server mcp start](#server-mcp-start)
- [server service start](#server-service-start)
- [server service stop](#server-service-stop)
- [server service status](#server-service-status)
- [server service warmup](#server-service-warmup)
- [server service projects list](#server-service-projects-list)
- [server service projects evict](#server-service-projects-evict)
- [install](#install)
- [uninstall](#uninstall)
- [benchmark](#benchmark)
- [quality](#quality)
- [test](#test)

## Conventions

JSON envelopes (where `--json` is documented) use one of two shapes:

```json
{"ok": true, "command": "<name>", "data": { ... }}
{"ok": false, "command": "<name>", "error": "<code>", "message": "<human text>"}
```

Standard exit codes:

| Code | Meaning                                                                                                                  |
| ---- | ------------------------------------------------------------------------------------------------------------------------ |
| 0    | Success.                                                                                                                 |
| 1    | Generic failure (GPU error, empty vault, quality threshold not met, runtime fault).                                      |
| 2    | Usage error or unrecoverable precondition (invalid flag combination, missing required argument, install gating failure). |
| 3    | Service stopped (no `service.json` present).                                                                             |
| 4    | Service divergent or crashed (`service.json` present but signals disagree).                                              |

Codes 3 and 4 are emitted only by `server service status`.

## Global options

Apply to every subcommand. Pass them before the subcommand name.

| Flag                     | Default                   | Description                                                  |
| ------------------------ | ------------------------- | ------------------------------------------------------------ |
| `--target`, `-t DIR`     | current working directory | Workspace directory containing `.vault/` and `.vaultspec/`.  |
| `--verbose`, `-v`        | off                       | Enable INFO logging.                                         |
| `--debug`, `-d`          | off                       | Enable DEBUG logging.                                        |
| `--data-dir TEXT`        | `.vault/data/search-data` | RAG data root.                                               |
| `--qdrant-dir TEXT`      | derived                   | Qdrant storage directory, resolved relative to `--data-dir`. |
| `--index-meta TEXT`      | derived                   | Vault index metadata filename.                               |
| `--code-index-meta TEXT` | derived                   | Code index metadata filename.                                |
| `--status-dir TEXT`      | `~/.vaultspec-rag`        | Service status directory.                                    |
| `--log-file TEXT`        | derived                   | Service log filename, resolved relative to `--status-dir`.   |
| `--version`, `-V`        | -                         | Print version and exit.                                      |
| `--install-completion`   | -                         | Install shell completion.                                    |
| `--show-completion`      | -                         | Print shell completion script.                               |
| `--help`                 | -                         | Show help and exit.                                          |

## index

Index vault documents, codebase chunks, or both. Loads embedding models and requires CUDA unless delegating to a running service via `--port`.

| Flag                        | Default            | Description                                                                                              |
| --------------------------- | ------------------ | -------------------------------------------------------------------------------------------------------- |
| `--type [vault\|code\|all]` | `all`              | What to index.                                                                                           |
| `--model TEXT`              | configured default | Override the embedding model name.                                                                       |
| `--rebuild`                 | off                | Drop the selected index collections before re-indexing.                                                  |
| `--port INTEGER`            | unset              | Delegate to a running MCP server on this port.                                                           |
| `--dry-run`                 | off                | List files that would be indexed without indexing. Codebase only.                                        |
| `--exclude TEXT`            | none               | Ad-hoc exclusion pattern, gitignore syntax. Repeatable. Combined with `.vaultragignore`.                 |
| `--allow-fallback`          | off                | When `--port` is unreachable, fall back to in-process indexing instead of hard-failing.                  |
| `--verbose`                 | off                | Re-enable HuggingFace tqdm progress bars.                                                                |
| `--json`                    | off                | Emit one JSON envelope summarising per-source `added`, `updated`, `removed`, `total`, and `duration_ms`. |

Exit codes: 0, 1, 2.

## search

Search the vault or codebase. Emits a Rich table or, with `--json`, the standard envelope (see [Conventions](#conventions)).

Required argument: `QUERY` (free text).

| Flag                    | Default | Description                                                                           |
| ----------------------- | ------- | ------------------------------------------------------------------------------------- |
| `--type [vault\|code]`  | `vault` | Search source.                                                                        |
| `--max-results INTEGER` | `10`    | Maximum number of results.                                                            |
| `--language TEXT`       | none    | Code filter: programming language (e.g. `python`).                                    |
| `--path TEXT`           | none    | Code filter: exact project-relative file path.                                        |
| `--include-path TEXT`   | none    | Code filter: fnmatch glob, keep matching paths. Repeatable.                           |
| `--exclude-path TEXT`   | none    | Code filter: fnmatch glob, drop matching paths. Repeatable.                           |
| `--dedup-locales`       | off     | Code post-process: collapse near-tie locale variants into one canonical result.       |
| `--prefer TEXT`         | none    | Code post-process: nudge results in `prod`, `tests`, or `docs` up after rerank.       |
| `--node-type TEXT`      | none    | Code filter: AST node type.                                                           |
| `--function-name TEXT`  | none    | Code filter: function or method name.                                                 |
| `--class-name TEXT`     | none    | Code filter: class or struct name.                                                    |
| `--doc-type TEXT`       | none    | Vault filter: doc type (e.g. `adr`, `plan`).                                          |
| `--feature TEXT`        | none    | Vault filter: feature tag, kebab-case.                                                |
| `--date TEXT`           | none    | Vault filter: exact ISO date `yyyy-mm-dd`.                                            |
| `--tag TEXT`            | none    | Vault filter: free-form tag, no leading `#`.                                          |
| `--no-truncate`         | off     | Disable 120-character snippet truncation in the table.                                |
| `--port INTEGER`        | unset   | Delegate to a running MCP server.                                                     |
| `--allow-fallback`      | off     | When `--port` is unreachable, fall back to in-process search instead of hard-failing. |
| `--verbose`             | off     | Re-enable HuggingFace tqdm progress bars.                                             |
| `--json`                | off     | Emit one JSON envelope to stdout.                                                     |

JSON envelope shape on success:

```json
{"ok": true, "command": "search", "data": {"results": [ ... ]}}
```

On error:

```json
{"ok": false, "command": "search", "error": "<code>", "message": "<text>"}
```

Exit codes: 0, 1, 2.

## clean

Drop selected index collections without re-indexing. Does not load embedding models, walk the vault, scan the codebase, or touch GPUs. Drops and re-creates Qdrant collections and clears the matching metadata sidecar files.

Required argument: `CLEAN_TYPE` - one of `vault`, `code`, `all`. No default; an `all` default would be destructive.

| Flag          | Default | Description                                                                         |
| ------------- | ------- | ----------------------------------------------------------------------------------- |
| `--yes`, `-y` | off     | Confirm the destructive wipe without prompting.                                     |
| `--json`      | off     | Emit one JSON envelope to stdout. Requires `--yes` so the stream stays uncorrupted. |

Exit codes: 0, 1, 2.

## status

Show RAG engine status, storage metrics, and GPU info.

| Flag     | Default | Description                                                          |
| -------- | ------- | -------------------------------------------------------------------- |
| `--json` | off     | Emit one JSON envelope. Mirrors the MCP `get_index_status` response. |

Output rows (table mode): Device (GPU name), Storage Path (Qdrant local directory), Vault Documents (count), Codebase Chunks (count), Target Directory (project root), plus a Backend Capabilities block (backend type, concurrent-search support, same-project search strategy, cross-project search strategy, storage process model).

Exit codes: 0, 1.

## server mcp start

Start the MCP server in the foreground. Defaults to stdio transport (LLM integration). With `--port`, runs HTTP transport on that port for standalone use. Propagates `--target` to the server via the `VAULTSPEC_ROOT` environment variable.

| Flag             | Default | Description                        |
| ---------------- | ------- | ---------------------------------- |
| `--port INTEGER` | stdio   | Run on HTTP port instead of stdio. |

Exit code: propagates the server process exit (typically 0 on Ctrl+C).

## server service start

Start the background RAG service as a detached process. Spawns the MCP server on the given port, polls `/health` with exponential backoff until ready, and writes `~/.vaultspec-rag/service.json`.

| Flag             | Default                          | Description                    |
| ---------------- | -------------------------------- | ------------------------------ |
| `--port INTEGER` | `8766` (or `VAULTSPEC_RAG_PORT`) | TCP port for the HTTP service. |

Exit codes: 0, 1.

## server service stop

Stop the background RAG service. Reads `~/.vaultspec-rag/service.json`, verifies the PID belongs to a `vaultspec-rag` process, sends a graceful signal (SIGTERM on Unix, CTRL_BREAK_EVENT on Windows), waits briefly, then removes the status file. Force-kills if graceful shutdown fails.

No flags beyond `--help`.

Exit codes: 0, 1.

## server service status

Display the current status of the background RAG service. Gathers four signals before rendering: `service.json` present, PID alive, port listening, heartbeat fresh. Each surfaces as its own row plus a derived `State` row.

| Flag     | Default | Description                                                |
| -------- | ------- | ---------------------------------------------------------- |
| `--json` | off     | Emit one JSON envelope. Preserves the three-way exit code. |

Output rows (table mode): `service.json`, `pid`, `port`, `heartbeat`, `state`.

Exit codes:

| Code | State                                                                      |
| ---- | -------------------------------------------------------------------------- |
| 0    | `running` - all signals green.                                             |
| 3    | `stopped` - no `service.json`.                                             |
| 4    | `divergent` or `crashed-*` - file present, one or more signals contradict. |

## server service warmup

Pre-download GPU model files to the HuggingFace cache. Checks CUDA availability, then downloads each of the three model repositories (dense, sparse, reranker) if not already cached. Reports per-model status.

No flags beyond `--help`.

Exit codes: 0, 1 (CUDA unavailable, `huggingface_hub` not installed, or download failure).

## server service projects list

List active project slots on a running RAG service.

| Flag             | Default              | Description             |
| ---------------- | -------------------- | ----------------------- |
| `--port INTEGER` | running service port | MCP port.               |
| `--json`         | off                  | Emit one JSON envelope. |

Exit codes: 0, 1, 3 (service not running).

## server service projects evict

Evict a project slot on a running RAG service.

Required argument: `ROOT` - project root to evict.

| Flag             | Default              | Description             |
| ---------------- | -------------------- | ----------------------- |
| `--port INTEGER` | running service port | MCP port.               |
| `--json`         | off                  | Emit one JSON envelope. |

Exit codes: 0, 1, 2 (project root not found), 3 (service not running).

## install

Install `vaultspec-rag` enrollment into a workspace. Seeds rag's bundled rule and MCP source files into `.vaultspec/rules/` and invokes `vaultspec-core`'s sync to propagate them to `.mcp.json` and provider directories. Creates the workspace if absent.

Flag names mirror `vaultspec-core install`.

| Flag                                 | Default                   | Description                                                                                                    |
| ------------------------------------ | ------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `--target`, `-t DIR`                 | current working directory | Workspace path.                                                                                                |
| `--upgrade`                          | off                       | Re-seed bundled rule and MCP files even if present.                                                            |
| `--dry-run`                          | off                       | Preview changes without writing.                                                                               |
| `--force`                            | off                       | Override existing files; also bypasses the torch-config confirmation prompt and prunes orphaned sync state.    |
| `--skip TEXT`                        | none                      | Skip a component. Repeatable.                                                                                  |
| `--torch-config / --no-torch-config` | `--torch-config`          | Patch `pyproject.toml` with the cu130 torch index. `--no-torch-config` always wins over `--force` and `--yes`. |
| `--yes`, `-y`                        | off                       | Skip the torch-config confirmation prompt. Required on non-TTY runs.                                           |
| `--sync`                             | off                       | Run `uv sync --reinstall-package torch` after the patch lands. No-ops if the patch did not apply.              |
| `--json`                             | off                       | Emit one JSON envelope.                                                                                        |

Torch-config gating, in precedence order:

- `--no-torch-config` always wins. Reports `torch_config_action: disabled`.
- Non-TTY without `--yes` or `--force`: patch skipped with warning; reports `skipped-non-tty`; exits 2.
- `--yes` or `--force` bypasses the prompt. `--force` additionally re-seeds bundled files and prunes orphaned sync state.
- TTY without `--yes` or `--force`: user is prompted; Enter declines (default-no).

Exit codes: 0 on success or on terminal states reflecting intent (`declined`, `conflict`, `absent`, `disabled`); 2 when torch-config terminates in `error`, `skipped-eof`, or `skipped-non-tty`.

## uninstall

Remove `vaultspec-rag` enrollment from a workspace. Symmetric mirror of `install`. Without `--force`, returns a dry-run preview only. `.vault/` documents are always preserved. The rag index under `.vault/data/` is preserved unless `--remove-data` is set. `vaultspec-core`'s installation is never touched.

| Flag                 | Default                   | Description                                                    |
| -------------------- | ------------------------- | -------------------------------------------------------------- |
| `--target`, `-t DIR` | current working directory | Workspace path.                                                |
| `--remove-data`      | off                       | Also remove `.vault/data/` (rag's index).                      |
| `--dry-run`          | off                       | Preview changes without removing.                              |
| `--force`            | off                       | Required to execute. Uninstall is destructive.                 |
| `--skip TEXT`        | none                      | Skip a component. Repeatable.                                  |
| `--yes`, `-y`        | off                       | Skip confirmation prompts. Reserved for forward compatibility. |
| `--json`             | off                       | Emit one JSON envelope.                                        |

Exit codes: 0, 1, 2.

## benchmark

Run search latency benchmarks against the indexed vault. Requires an indexed vault. Reports p50, p95, p99 latency; store counts; GPU VRAM usage. For maintainers tracking regression on a specific workspace.

| Flag                  | Default | Description                       |
| --------------------- | ------- | --------------------------------- |
| `--n-queries INTEGER` | `20`    | Number of search queries to time. |

Exit codes: 0; 1 when the vault is empty or on GPU errors.

## quality

Run quality-scoring probes against a synthetic test corpus. Generates a temporary synthetic vault, indexes it, runs needle-based precision probes, and reports results. For developer regression of retrieval quality; not tied to a user vault.

No flags beyond `--help`.

Exit codes: 0; 1 when precision drops below 75% or on GPU errors.

## test

Run the test suite via pytest. All extra arguments are forwarded to pytest. For maintainers running the project's own test suite from inside an installed environment.

No flags of its own. Pass pytest arguments after the subcommand name, for example `vaultspec-rag test -m unit` or `vaultspec-rag test -m integration -v --timeout=120`.

Exit code: propagates pytest's exit code.
