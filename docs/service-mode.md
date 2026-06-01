# Running as a background service

This page shows you how to start, route commands at, and stop a long-running vaultspec-rag service so commands return without reloading models on every invocation. Model load is noticeable enough that batch use feels different from single commands; see [architecture.md](architecture.md) for the trade-off.

Before you start, this page assumes you have vaultspec-rag installed and at least one search has worked. See [installation.md](installation.md) for setup and [search-and-index.md](search-and-index.md) for the ad-hoc form this page replaces for repeat searches.

## Start the service

```bash
uv run vaultspec-rag server service start
```

This detaches a background process, binds the default port 8766, and writes a status file to `~/.vaultspec-rag/service.json`. To change the port, set `VAULTSPEC_RAG_PORT` or pass `--port`; see [configuration.md](configuration.md) for the full env var list.

The service also runs a filesystem watcher that re-indexes on change. Control it at start time:

```bash
uv run vaultspec-rag server service start \
  --watch \
  --watch-debounce-ms 2000 \
  --watch-cooldown-s 30
```

The watcher flags are:

- `--watch` / `--no-watch` — enable or disable the watcher (enabled by default).
- `--watch-debounce-ms N` — debounce window in milliseconds (default 2000).
- `--watch-cooldown-s S` — minimum seconds between re-index passes per source (default 30).

The daemon inherits only its environment, not its command-line arguments, so these flags are translated to `VAULTSPEC_RAG_WATCH_*` environment variables on the child process before it is spawned. Setting those variables directly has the same effect.

## Route commands at the service

```bash
uv run vaultspec-rag search "query" --port 8766
```

```bash
uv run vaultspec-rag index --port 8766
```

If the port is unreachable, the CLI exits with remediation instead of silently falling back to in-process execution. To opt in to in-process fallback for a single command, pass `--allow-fallback`. Use it sparingly; the name reflects what it bypasses, not a default.

## Automatic re-indexing (the watcher)

The resident service runs a filesystem watcher that incrementally re-indexes your vault and codebase whenever files change. It is **on by default**, so an indexed project stays fresh without any manual `index` calls.

Opt out for a pull-only service — one that re-indexes only when you ask it to — with `--no-watch` at start time, or by setting `VAULTSPEC_RAG_WATCH_ENABLED=0`:

```bash
uv run vaultspec-rag server service start --no-watch
```

Tune the watcher's responsiveness with two settings:

- `--watch-debounce-ms` (default 2000) — how long to wait after the last change before re-indexing, coalescing bursts of edits into one pass.
- `--watch-cooldown-s` (default 30) — the minimum gap between re-index passes for a given source, so rapid saves cannot trigger back-to-back rebuilds.

A value of `0` for either setting means "no delay", **not** disabled. `watch_enabled` is the only off-switch; for a pull-only service use `--no-watch` or `VAULTSPEC_RAG_WATCH_ENABLED=0`.

See [automation.md](automation.md) for the full watcher behaviour and [configuration.md](configuration.md) for the `VAULTSPEC_RAG_WATCH_*` environment variables.

## Control the watcher on a running service

You can inspect and reconfigure the watcher without restarting the service. Each subcommand accepts `--port` and `--json`, and exits with code 3 if the service is not running.

Show the watcher configuration and the roots currently being watched:

```bash
uv run vaultspec-rag server service watcher status --port 8766
```

Start eager watching for a root (a no-op if the watcher is disabled):

```bash
uv run vaultspec-rag server service watcher start /path/to/project --port 8766
```

Switch a root to pull-only by stopping its watcher:

```bash
uv run vaultspec-rag server service watcher stop /path/to/project --port 8766
```

Re-tune a root in place — this stops and restarts its watcher with the new tuning:

```bash
uv run vaultspec-rag server service watcher reconfigure /path/to/project \
  --debounce-ms 5000 \
  --cooldown-s 60 \
  --port 8766
```

Each of these commands has a matching MCP tool for CLI parity: `get_watcher_state`, `start_watcher`, `stop_watcher`, and `reconfigure_watcher`.

## Observe the running service

Three CLI commands report on the live service. Each accepts `--port` and `--json`, and exits with code 3 if the service is not running.

Show consolidated service state — per-source index counts, the GPU and device in use, project slots, and a watcher rollup:

```bash
uv run vaultspec-rag server service info --port 8766
```

Tail the rotated service log:

```bash
uv run vaultspec-rag server service logs --lines 100 --port 8766
```

Show recent and in-flight index and reindex activity, read from the service's in-flight job registry:

```bash
uv run vaultspec-rag server service jobs --limit 20 --port 8766
```

These commands also map to MCP tools for parity: `get_service_state`, `get_logs`, and `get_jobs`.

## HTTP monitoring routes

The running service exposes a small set of read-only HTTP routes on its loopback port. They back the observability commands above and are also useful for external monitoring:

- `GET /health` — readiness probe. **Ungated**, so probes never need a token.
- `GET /logs?lines=N` — the tail of the service log as `text/plain`.
- `GET /jobs` — recent and in-flight job activity as JSON.
- `GET /metrics` — Prometheus-format metrics as text. Metrics are computed inline on each request; there is no background collection thread.

The `/logs`, `/jobs`, and `/metrics` routes require the service token as a bearer token:

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8766/metrics
```

The `service_token` is recorded in `~/.vaultspec-rag/service.json` and is also returned by `/health`.

This is a **monitoring gate plus loopback binding, not an authentication boundary.** The token only fences off the read-only monitoring routes, and `/health` returns it in the clear. Keep the service loopback-bound: knowing the token grants nothing more than read access to monitoring data.

## Check status

```bash
uv run vaultspec-rag server service status
```

The output lists each signal as its own row (status file present, PID alive, port listening, heartbeat fresh) plus a derived state row. Exit codes are 0 when running, 3 when stopped, and 4 when divergent or crashed. See [cli.md](cli.md) for the full column meanings.

## Stop the service

```bash
uv run vaultspec-rag server service stop
```

This sends a graceful termination signal (SIGTERM on Linux and macOS, CTRL_BREAK_EVENT on Windows), waits briefly for shutdown, and removes the status file. If the graceful signal does not land in time, the daemon is force-killed.

## Warm models before serving

```bash
uv run vaultspec-rag server service warmup
```

This pre-downloads the model files to the HuggingFace cache so the first real request is not delayed by the download. Warmup requires CUDA. Download time depends on your network and which model snapshots HuggingFace serves.

## Use the service for multiple projects

A single service handles every project on your machine. Each command sends the current working directory as the project to operate on, and the service loads per-project indexes on demand.

To see what is currently in memory:

```bash
uv run vaultspec-rag server service projects list
```

To evict a project's slot:

```bash
uv run vaultspec-rag server service projects evict /path/to/project
```

See [cli.md](cli.md) for the full flag reference on both commands.

## Troubleshooting

### Port already in use

Choose a different port and use it consistently. Set `VAULTSPEC_RAG_PORT=8767` in your shell, or pass `--port 8767` to every command including `server service start`. The port the daemon binds and the port the CLI dials must match.

### Status reports `crashed-*` with exit code 4

The daemon was killed without cleanup, so the status file disagrees with the live process state. Running `uv run vaultspec-rag server service start` again overwrites the file cleanly. If status still reports divergence, delete `~/.vaultspec-rag/service.json` by hand and start again.

### Daemon will not stop

The graceful signal did not land, usually because the PID in `service.json` no longer points at the daemon. Read the PID from `~/.vaultspec-rag/service.json`, kill it manually with your platform's process tools, and remove the status file.

### The index seems stale

Check `server service watcher status` and `server service jobs` to confirm the watcher is running and re-indexing, rather than reindexing manually.

## See also

- [architecture.md](architecture.md) for why service mode exists and why `--port` hard-fails on an unreachable port.
- [automation.md](automation.md) for the filesystem watcher and continuous re-indexing.
- [configuration.md](configuration.md) for environment variables, including the `VAULTSPEC_RAG_WATCH_*` watcher settings.
- [search-and-index.md](search-and-index.md) for the ad-hoc form without a daemon.
- [mcp.md](mcp.md) for how AI assistants consume the same service.
- [cli.md](cli.md) for status column meanings and every service command flag.

## Need help?

See the [Support](../README.md#support-and-help) section of the repo README.
