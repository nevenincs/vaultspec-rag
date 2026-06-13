# Running as a background service

This page shows you how to start, route commands at, and stop a long-running vaultspec-rag service so commands return without reloading models on every invocation. Model load is noticeable enough that batch use feels different from single commands; see [architecture.md](architecture.md) for the trade-off.

Before you start, this page assumes you have vaultspec-rag installed and at least one search has worked. See [installation.md](installation.md) for setup and [search-and-index.md](search-and-index.md) for the ad-hoc form this page replaces for repeat searches.

## Server-first, local-explicit

The resident service is **server-first**: by default it supervises a managed Qdrant server child process and routes every project's stores at it. Server mode is the default because, on large codebases and under multi-agent load, the supervised Qdrant server returns searches at interactive latency where the on-disk store's brute-force scan degrades by orders of magnitude.

Local mode — the pure-Python on-disk store, with no external process — is a deliberate, first-class **opt-out**, not a fallback. Choose `--local-only` (or set `VAULTSPEC_RAG_LOCAL_ONLY=1`) when you are on:

- CI, where a long-lived server process is unwanted overhead;
- an air-gapped or proxied host, where the binary cannot be fetched (or use the operator-supplied-binary path, below); or
- a small project, where the on-disk store is already sub-millisecond and needs nothing more.

If you ran `install --local-only`, that choice is persisted, and `server start` honours it without any extra flag.

## Start the service

```bash
uv run vaultspec-rag server start
```

This detaches a background process, binds the default port 8766, and records how the CLI can reach it. By default it starts in server mode and supervises the managed Qdrant child; if the Qdrant binary is missing, `start` prints the install command rather than failing opaquely. To opt in to the download at start time, pass `--qdrant-auto-provision`.

To change the port, set `VAULTSPEC_RAG_PORT` or pass `--port`; see [configuration.md](configuration.md) for the full env var list.

Start in local mode instead, skipping the managed Qdrant server and using the on-disk store:

```bash
uv run vaultspec-rag server start --local-only
```

The service also runs automatic index updates (a filesystem watcher) that re-index on change. Control them at start time:

```bash
uv run vaultspec-rag server start \
  --updates \
  --update-delay-ms 2000 \
  --repeat-update-delay-s 30
```

The automatic-update flags are:

- `--updates` / `--no-updates` — enable or disable automatic index updates (enabled by default).
- `--update-delay-ms N` — delay before indexing a burst of file changes, in milliseconds (default 2000).
- `--repeat-update-delay-s S` — minimum wait before automatically updating a project again, in seconds (default 30).

The daemon inherits only its environment, not its command-line arguments, so each set flag is translated to the matching `VAULTSPEC_RAG_*` environment variable on the child process before it is spawned. Setting those variables directly has the same effect.

## Check readiness

`server doctor` reports a bounded, read-only readiness snapshot for every external dependency, so you learn what is missing before a runtime failure:

```bash
uv run vaultspec-rag server doctor
```

It reports, per dependency, the backend in use (server or local) and:

- **torch** — whether CUDA is available;
- **models** — whether the model snapshots are present in the cache; and
- **qdrant** — the binary's resolution source (provisioned, operator-supplied, or missing) and the supervised server's liveness.

Add `--json` for a machine-readable envelope. The same snapshot is available over HTTP at the token-gated `GET /readiness` route (see [HTTP monitoring routes](#http-monitoring-routes) below).

## Route commands at the service

```bash
uv run vaultspec-rag search "query" --port 8766
```

```bash
uv run vaultspec-rag index --port 8766
```

If the port is unreachable, the CLI exits with remediation instead of silently falling back to in-process execution. To opt in to in-process fallback for a single command, pass `--allow-fallback`. Use it sparingly; the name reflects what it bypasses, not a default.

## Automatic re-indexing

The resident service automatically re-indexes your vault and codebase whenever files change. It is **on by default**, so an indexed project stays fresh without any manual `index` calls.

Opt out for a pull-only service — one that re-indexes only when you ask it to — with `--no-updates` at start time, or by setting `VAULTSPEC_RAG_WATCH_ENABLED=0`:

```bash
uv run vaultspec-rag server start --no-updates
```

Tune responsiveness with two settings:

- `--update-delay-ms` (default 2000) — how long to wait after the last change before re-indexing, coalescing bursts of edits into one pass.
- `--repeat-update-delay-s` (default 30) — the minimum gap between re-index passes for a given project, so rapid saves cannot trigger back-to-back rebuilds.

A value of `0` for either setting means "no delay", **not** disabled. Disabling automatic updates is the only off-switch; for a pull-only service use `--no-updates` or `VAULTSPEC_RAG_WATCH_ENABLED=0`.

See [automation.md](automation.md) for the full update behaviour and [configuration.md](configuration.md) for the `VAULTSPEC_RAG_WATCH_*` environment variables.

## Control automatic updates on a running service

You can inspect and reconfigure automatic updates without restarting the service. Each subcommand accepts `--port` and `--json`.

Show the update settings and the projects currently being watched:

```bash
uv run vaultspec-rag server updates status --port 8766
```

Start automatic updates for a project (a no-op if updates are disabled):

```bash
uv run vaultspec-rag server updates start /path/to/project --port 8766
```

Switch a project to pull-only by stopping its automatic updates:

```bash
uv run vaultspec-rag server updates stop /path/to/project --port 8766
```

Change a project's update timing in place:

```bash
uv run vaultspec-rag server updates timing /path/to/project \
  --update-delay-ms 5000 \
  --repeat-update-delay-s 60 \
  --port 8766
```

Each of these commands has a matching MCP tool for parity: `get_watcher_state`, `start_watcher`, `stop_watcher`, and `reconfigure_watcher`.

## Observe the running service

Tail the rotated service log:

```bash
uv run vaultspec-rag server logs --limit 100 --port 8766
```

Show recent and in-flight index and reindex activity, read from the service's in-flight job registry:

```bash
uv run vaultspec-rag server jobs --limit 20 --port 8766
```

`server jobs` is bounded and filterable: scope it with `--state`, `--failed`, `--job-id`, `--since`, `--index`, or `--started-by` so running or relevant work is not buried under stale history. These commands also map to MCP tools for parity: `get_logs` and `get_jobs`.

## HTTP monitoring routes

The running service exposes a small set of read-only HTTP routes on its loopback port. They back the observability commands above and are also useful for external monitoring:

- `GET /health` — readiness probe. **Ungated**, so probes never need a token.
- `GET /readiness` — the per-dependency readiness snapshot (the same data `server doctor` reports). Token-gated.
- `GET /logs?lines=N` — the tail of the service log as `text/plain`. Token-gated.
- `GET /jobs` — recent and in-flight job activity as JSON. Token-gated.
- `GET /metrics` — Prometheus-format metrics as text. Token-gated. Metrics are computed inline on each request; there is no background collection thread.

The gated routes require the service token as a bearer token:

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8766/metrics
```

The `service_token` is recorded in `~/.vaultspec-rag/service.json` and is also returned by `/health`.

This is a **monitoring gate plus loopback binding, not an authentication boundary.** The token only fences off the read-only monitoring routes, and `/health` returns it in the clear. Keep the service loopback-bound: knowing the token grants nothing more than read access to monitoring data.

## Check status

```bash
uv run vaultspec-rag server status
```

The output summarises whether the service is running, the backend in use, and the next checks worth running. Add `--verbose` for process, heartbeat, identity, and model detail. Exit codes are 0 when running, 3 when stopped, and 4 when divergent or crashed. See [cli.md](cli.md) for the full meanings.

## Stop the service

```bash
uv run vaultspec-rag server stop
```

This sends a graceful termination signal (SIGTERM on Linux and macOS, CTRL_BREAK_EVENT on Windows), waits briefly for shutdown, and removes the status file. If the graceful signal does not land in time, the daemon is force-killed. Stopping the service also shuts down the supervised Qdrant child in server mode.

## Warm models before serving

```bash
uv run vaultspec-rag server warmup
```

This pre-downloads the model files to the HuggingFace cache so the first real request is not delayed by the download. Warmup requires CUDA. Download time depends on your network and which model snapshots HuggingFace serves.

## Manage the Qdrant server binary

Server mode depends on the managed Qdrant binary, which `install` provisions by default. Manage it directly when needed:

```bash
uv run vaultspec-rag server qdrant status
```

Download and verify the binary on demand (idempotent if already installed):

```bash
uv run vaultspec-rag server qdrant install
```

On an air-gapped host, register an operator-supplied executable instead of downloading — a first-class path that still flows through the same supervised resolution:

```bash
uv run vaultspec-rag server qdrant install --binary /path/to/qdrant
```

## Use the service for multiple projects

A single service handles every project on your machine. Each command sends the current working directory as the project to operate on, and the service loads per-project indexes on demand.

To see what is currently in memory:

```bash
uv run vaultspec-rag server projects list
```

To unload a project's slot:

```bash
uv run vaultspec-rag server projects unload /path/to/project
```

See [cli.md](cli.md) for the full flag reference on both commands.

## Troubleshooting

### Port already in use

Choose a different port and use it consistently. Set `VAULTSPEC_RAG_PORT=8767` in your shell, or pass `--port 8767` to every command including `server start`. The port the daemon binds and the port the CLI dials must match.

### Server will not start

If `server start` fails because the managed Qdrant binary is missing, it prints the install command. Run `uv run vaultspec-rag install` or `uv run vaultspec-rag server qdrant install`, or fall back to local mode with `server start --local-only`. The failure is loud and actionable by design; a server-first default must never fail opaquely on a constrained host.

### Status reports `crashed-*` with exit code 4

The daemon was killed without cleanup, so the status file disagrees with the live process state. Running `uv run vaultspec-rag server start` again overwrites the file cleanly. If status still reports divergence, delete `~/.vaultspec-rag/service.json` by hand and start again.

### Daemon will not stop

The graceful signal did not land, usually because the PID in `service.json` no longer points at the daemon. Read the PID from `~/.vaultspec-rag/service.json`, kill it manually with your platform's process tools, and remove the status file.

### The index seems stale

Check `server updates status` and `server jobs` to confirm automatic updates are running and re-indexing, rather than reindexing manually.

## See also

- [architecture.md](architecture.md) for why service mode exists and why `--port` hard-fails on an unreachable port.
- [automation.md](automation.md) for automatic index updates and continuous re-indexing.
- [configuration.md](configuration.md) for environment variables, including the `VAULTSPEC_RAG_WATCH_*` update settings and `VAULTSPEC_RAG_LOCAL_ONLY`.
- [search-and-index.md](search-and-index.md) for the ad-hoc form without a daemon.
- [mcp.md](mcp.md) for how AI assistants consume the same service.
- [cli.md](cli.md) for status column meanings and every service command flag.

## Need help?

See the [Support](../README.md#support-and-help) section of the repo README.
