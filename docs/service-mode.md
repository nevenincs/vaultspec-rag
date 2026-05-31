# Running as a background service

This page shows you how to start, route commands at, and stop a long-running vaultspec-rag service so commands return without reloading models on every invocation. Model load is noticeable enough that batch use feels different from single commands; see [architecture.md](architecture.md) for the trade-off.

Before you start, this page assumes you have vaultspec-rag installed and at least one search has worked. See [installation.md](installation.md) for setup and [search-and-index.md](search-and-index.md) for the ad-hoc form this page replaces for repeat searches.

## Start the service

```bash
uv run vaultspec-rag server service start
```

This detaches a background process, binds the default port 8766, and writes a status file to `~/.vaultspec-rag/service.json`. To change the port, set `VAULTSPEC_RAG_PORT` or pass `--port`; see [configuration.md](configuration.md) for the full env var list.

## Route commands at the service

```bash
uv run vaultspec-rag search "query" --port 8766
```

```bash
uv run vaultspec-rag index --port 8766
```

If the port is unreachable, the CLI exits with remediation instead of silently falling back to in-process execution. To opt in to in-process fallback for a single command, pass `--allow-fallback`. Use it sparingly; the name reflects what it bypasses, not a default.

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

## See also

- [architecture.md](architecture.md) for why service mode exists and why `--port` hard-fails on an unreachable port.
- [search-and-index.md](search-and-index.md) for the ad-hoc form without a daemon.
- [mcp.md](mcp.md) for how AI assistants consume the same service.
- [cli.md](cli.md) for status column meanings and every service command flag.

## Need help?

See the [Support](../README.md#support-and-help) section of the repo README.
