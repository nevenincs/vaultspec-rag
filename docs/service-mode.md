# Run the background service

Run vaultspec-rag as a long-lived background service to keep the GPU models loaded and the managed Qdrant server running. This is the standard server-backed path: the first query pays the model-loading cost once, and every later query reuses the already-loaded models instead of reloading them.

This guide assumes the workspace is already installed and provisioned. "Provisioned" means the `install` command has fetched the GPU model files and the Qdrant server binary. If you haven't done that yet, start with the [installation guide](installation.md). For the difference between the managed server and the on-disk store, see the [backends guide](backends.md). For how the service, the GPU consumer, and the vector store fit together, see the [architecture overview](architecture.md).

## Start the service

Run:

```
uv run vaultspec-rag server start
```

The command starts the managed Qdrant server on loopback at `http://127.0.0.1:8765` and warms the models. It then binds the service on port 8766, writes a status file, and polls until the service reports ready. When the poll succeeds, the service is serving requests.

If you don't want a managed server, run the service local-only instead:

```
uv run vaultspec-rag server start --local-only
```

"Local-only" means an on-disk store with no separate server process. The on-disk store skips the Qdrant binary, so it's the path to use on a machine where the binary isn't provisioned. See the [backends guide](backends.md) for the trade-offs.

Other start flags - `--port`, `--updates` / `--no-updates`, `--update-delay-ms`, `--repeat-update-delay-s`, `--qdrant` / `--no-qdrant`, and `--qdrant-auto-provision` - cover specific cases described in the sections that follow. For the full list, see the [CLI reference](cli.md).

## Warm models before serving

The first search after a cold start downloads the GPU model files if they aren't cached yet, which delays that query. To pull the model files ahead of time, run:

```
uv run vaultspec-rag server warmup
```

Warmup is optional. `server start` already warms the models as part of startup; run `warmup` separately when you want the model files downloaded before you start serving.

## Route commands at the service

When a service is running, `search` and `index` detect it and route through it. No `--port` is needed:

```
uv run vaultspec-rag search "retry backoff"
uv run vaultspec-rag index
```

To target a service on a specific port, pass `--port N`. To run a command in the current process when the service is unreachable, add `--allow-fallback`:

```
uv run vaultspec-rag search "retry backoff" --port 8766
uv run vaultspec-rag search "retry backoff" --allow-fallback
```

Without `--allow-fallback`, an unreachable service fails with an error and a suggested fix, rather than silently running in the current process. That keeps a stopped or stale service from quietly running searches in-process with a cold model load. For more on searching and indexing, see the [search and index guide](search-and-index.md).

## Check readiness and status

If a search fails or you're unsure the service is healthy, run the two diagnostic commands and act on what they report.

To check whether each dependency is ready, run:

```
uv run vaultspec-rag server doctor
```

`doctor` reports the readiness of PyTorch CUDA, the models, and Qdrant, names the active backend (`server` or `local-only`), and states whether the service is ready for requests. If a dependency reports not ready, follow its detail line - usually a provision or install step. Add `--json` for a machine-readable report.

To check the running service, run:

```
uv run vaultspec-rag server status
```

`status` shows whether the server is up, its address, uptime, queue, processed jobs, and a suggested next action. Its exit codes are `0` running, `3` stopped, and `4` crashed or divergent. "Divergent" means the status file disagrees with the live process - for example, the file names a process ID that's no longer alive. If `status` reports crashed or divergent, see the troubleshooting section.

Both commands accept `--json`, and `status` accepts `--verbose` for extra detail. For the full meaning of every field and exit code, see the [CLI reference](cli.md).

## Observe activity

To see recent and in-flight indexing work, run:

```
uv run vaultspec-rag server jobs
```

To read the recent service activity feed, run:

```
uv run vaultspec-rag server logs
```

Both commands accept `--json`.

## Keep the index fresh automatically

Automatic updates are on by default: the service watches your files and reindexes changes for you, so you rarely need to index by hand. Manage updates on a running service with four commands:

```
uv run vaultspec-rag server updates status
uv run vaultspec-rag server updates start <project>
uv run vaultspec-rag server updates stop <project>
uv run vaultspec-rag server updates timing <project>
```

To re-time updates for a project, pass `--update-delay-ms` or `--repeat-update-delay-s` to `server updates timing`. A value of `0` on either delay means "no delay", not "disabled".

The single off switch is `--no-updates` at start time, or `VAULTSPEC_RAG_WATCH_ENABLED=0`. For the full behavior - debounce, cooldown, and how changes are batched - see the [automation guide](automation.md).

## Manage projects

One service serves many projects. To list the loaded project slots, run:

```
uv run vaultspec-rag server projects list
```

To unload a project's slot, run:

```
uv run vaultspec-rag server projects unload <project>
```

Idle projects are evicted over time, so you don't normally need to unload by hand. Unload when you want to free a slot right away.

## HTTP monitoring routes

The running service exposes read-only HTTP routes on loopback for monitoring:

- `GET /health` - service health. Ungated.
- `GET /readiness` - dependency readiness. Requires the service token.
- `GET /logs` - recent log lines. Requires the service token.
- `GET /jobs` - indexing activity. Requires the service token.
- `GET /metrics` - Prometheus metrics. Requires the service token.

Token-gated routes need the service token as a bearer: `Authorization: Bearer <service_token>`. The token is in the status file at `~/.vaultspec-rag/service.json` and is also returned by `/health`.

The token plus loopback binding is a monitoring gate, not an authentication boundary. Keep the service loopback-bound. For the MCP surface mounted on the same service, see the [MCP guide](mcp.md).

## Manage the managed Qdrant server

Installing, inspecting, and cleaning the managed Qdrant server is covered separately. Use `server qdrant install`, `server qdrant status`, and `server qdrant clean`; see the [backends guide](backends.md) for the workflow.

## Stop the service

To stop the service gracefully, run:

```
uv run vaultspec-rag server stop
```

Shutdown removes the status file and stops the Qdrant child last, so the vector store stays reachable until the service itself is down.

## Troubleshooting

**Port already in use.** If `server start` reports the port is taken, another process is bound there. Use one port consistently - pass `--port N` or set `VAULTSPEC_RAG_PORT` - so commands and the service agree.

**Status reports crashed or divergent (exit 4).** The status file disagrees with the live process. Re-run `server start` to overwrite the status file cleanly. If that doesn't clear it, delete the status file at `~/.vaultspec-rag/service.json` and start again.

**The service won't stop.** A stale process ID can keep `server stop` from completing. Kill the process by its ID, then remove the status file at `~/.vaultspec-rag/service.json`.

**The server can't start.** Server mode needs the managed Qdrant binary. Provision it with `uv run vaultspec-rag server qdrant install`, or run the service local-only with `uv run vaultspec-rag server start --local-only`.

**The index seems stale.** Check `server updates status` and `server jobs` before reindexing. Automatic updates may be catching up, or an update may be in flight. Don't reindex by hand while updates are running - it competes for the single-writer GPU and Qdrant path.

## See also and where to get help

- [Installation guide](installation.md) - install and provision the workspace.
- [Backends guide](backends.md) - managed server vs local-only, and managing the Qdrant binary.
- [Architecture overview](architecture.md) - how the service, GPU consumer, and store fit together.
- [Automation guide](automation.md) - how automatic updates behave.
- [Search and index guide](search-and-index.md) - searching and indexing through the service.
- [MCP guide](mcp.md) - the MCP tools on the running service.
- [CLI reference](cli.md) - every command, flag, field, and exit code.

For help, see the [support section](../README.md#support-and-help).
