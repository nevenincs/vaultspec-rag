# How to run vaultspec-rag as a background service

Run a single long-lived daemon so search and index commands skip GPU warm-up on every call. For the reasoning behind the service mode, see [Ad-hoc vs service](../explanation/ad-hoc-vs-service.md).

## Start the service

Launch the daemon. It detaches and listens on port 8766 by default.

```
uv run vaultspec-rag server service start
```

To use a different port, set the environment variable before starting:

```
VAULTSPEC_RAG_PORT=8767 uv run vaultspec-rag server service start
```

## Route commands to the service

Add `--port` to any CLI invocation. The command sends your current working directory as the target project.

```
uv run vaultspec-rag search "graph rebuild race" --port 8766
uv run vaultspec-rag index --port 8766
```

If the port is unreachable, the CLI exits with a remediation message. To run in-process instead, pass `--allow-fallback`. Use that flag only when a missing service is acceptable; it bypasses the daemon entirely and reacquires the GPU models for the call.

## Check status

Inspect the daemon and its health signals.

```
uv run vaultspec-rag server service status
```

Exit codes:

- `0` - running
- `3` - stopped (no status file)
- `4` - divergent or crashed (status file present but signals disagree)

The output lists rows for `service.json`, PID alive, port listening, and heartbeat freshness, followed by a derived `State` row. For the meaning of each column, see [CLI reference](../reference/cli.md).

## Stop the service

```
uv run vaultspec-rag server service stop
```

This sends SIGTERM (TerminateProcess on Windows) and clears the status file.

## Warm models before serving

Pre-download model files so the first request does not pay the cold-start cost.

```
uv run vaultspec-rag server service warmup
```

Run this once after install, or after switching machines.

## Serve multiple projects

One daemon serves any project on the host. Run commands from each project's directory; the CLI passes that directory as the project root.

```
cd /path/to/project-a && uv run vaultspec-rag search "query" --port 8766
cd /path/to/project-b && uv run vaultspec-rag search "query" --port 8766
```

List active project slots:

```
uv run vaultspec-rag server service projects list
```

Free a slot when you are done with a project:

```
uv run vaultspec-rag server service projects evict /path/to/project-a
```

For how slot allocation and eviction work, see [Ad-hoc vs service](../explanation/ad-hoc-vs-service.md). For column meanings, see [CLI reference](../reference/cli.md).

## Troubleshoot

### Port conflict

Another process holds 8766. Pick a different port on start, then pass it to every command:

```
VAULTSPEC_RAG_PORT=8767 uv run vaultspec-rag server service start
uv run vaultspec-rag search "query" --port 8767
```

### Stale status file

If the daemon was killed without cleanup, `service status` reports `crashed-*` with exit code 4. The next `server service start` overwrites the file. If start refuses, delete the file manually:

```
rm ~/.vaultspec-rag/service.json
```

If you set `VAULTSPEC_RAG_STATUS_DIR`, delete `service.json` from that directory instead.

### Daemon won't stop

`server service stop` already sends SIGTERM. If the process is wedged, read the PID from `~/.vaultspec-rag/service.json` and kill it directly:

```
kill -9 <pid>
```

On Windows:

```
taskkill /F /PID <pid>
```
