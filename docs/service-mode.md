# Run the background service

Run vaultspec-rag as a long-lived background service to keep the models loaded and the managed server running. The first query pays the model-loading cost once, and every later query reuses the already-loaded models.

This guide assumes the workspace is already installed and provisioned. "Provisioned" means `install` has fetched the model files and the Qdrant binary. It also means the environment has a PyTorch build for CUDA or Metal Performance Shaders (MPS). If you haven't done that, start with the [installation guide](installation.md).

For the choice between the managed server and the local-only store, see the [backends guide](backends.md). For the vocabulary used here, see the [glossary](glossary.md).

## Start the service

Run:

```
uv run vaultspec-rag server start
```

The command starts the managed Qdrant server on loopback at `http://127.0.0.1:8765` and warms the models. It then binds the service on port 8766, writes a status file, and polls until the service reports ready.

If you don't want a managed server, run local-only instead:

```
uv run vaultspec-rag server start --local-only
```

Start it from the project. The service runs in whatever Python environment launched it, which is why `uv run` is the documented form; see [Which Python environment runs the service](#which-python-environment-runs-the-service).

Other start flags control the port, automatic updates, update timing, and the managed server. The [CLI reference](cli.md) carries the full list.

## Confirm it is running

```
uv run vaultspec-rag server status
```

`status` shows whether the service is up, its address, uptime, queue, processed jobs, and a suggested next action. Its `Service env:` line names the Python environment running the service.

Its exit codes:

- `0` running
- `3` stopped
- `4` crashed or divergent
- `5` warming, meaning the daemon holds the machine lock and is loading models; retry shortly

"Divergent" means the status file disagrees with the live process, for example naming a process ID that is no longer alive. If `status` reports crashed or divergent, see [Troubleshooting](#troubleshooting).

To check each dependency rather than the process, run:

```
uv run vaultspec-rag server doctor
```

`doctor` reports PyTorch and accelerator readiness, the compute backend (`cuda` or `mps`), the models, and Qdrant. It separately names the storage backend (`server` or `local-only`) and states whether the service is ready for requests. If a dependency reports not ready, follow its detail line, which names either a provision step or an install step.

Both accept `--json`, and `status` accepts `--verbose`. For every field and exit code, see the [CLI reference](cli.md).

## Route commands at the service

When a service is running, `search` and `index` detect it and route through it. You don't need `--port`:

```
uv run vaultspec-rag search "retry backoff"
uv run vaultspec-rag index
```

To target a service on a specific port, pass `--port N`. To run a command in the current process when the service is unreachable, add `--allow-fallback`:

```
uv run vaultspec-rag search "retry backoff" --port 8766
uv run vaultspec-rag search "retry backoff" --allow-fallback
```

Without `--allow-fallback`, an unreachable service fails with an error and a suggested fix. That keeps a stopped or stale service from quietly running searches in-process with a cold model load. See the [search and index guide](search-and-index.md).

## Observe activity

To see recent and in-flight indexing work:

```
uv run vaultspec-rag server jobs
```

To inspect recent service and Qdrant logs:

```
uv run vaultspec-rag server logs
```

`server logs` prints separate `[service]` and `[qdrant]` sections rather than combining the two timelines. To inspect one source:

```
uv run vaultspec-rag server logs --source service
uv run vaultspec-rag server logs --source qdrant
```

If the service has stopped or crashed, run `server logs` anyway. It reads retained logs from the status directory, and source selection, filters, limits, and JSON output work the same way.

Both commands accept `--json`.

Three job signals are worth knowing. A failed job carries a stable `error_kind` in `--json` and on `GET /jobs`, classified once by the service so every surface agrees, and the human feed renders the matching remediation. A running job whose progress hasn't moved for five minutes is flagged `stalled`, so you never have to infer it. If the service process dies mid-job, the next startup restores what it was running as `interrupted`, with the last progress and who started it.

An index job that reused vectors from an already-indexed sibling worktree carries a `reuse` block describing what it avoided re-encoding. See [reusing vectors across worktrees](indexing.md#reusing-vectors-across-worktrees) for the mechanism, and the [CLI reference](cli.md) for the block's fields.

## Control one job

`server jobs` shows the feed. To act on a single job, address it by id with
`server job`, which accepts a unique prefix in human output:

```
uv run vaultspec-rag server job show <job-id>
```

Five more verbs act on one job:

- `server job pause` requests a cooperative pause.
- `server job resume` resumes a paused job through reconciliation.
- `server job stop` requests cancellation without disabling automatic updates.
- `server job retry` creates a linked retry for a retryable terminal job.
- `server job delete` removes one terminal job from retained history.

Pausing a single job differs from pausing the service: `server pause` holds
everything at safe checkpoints, while `server job pause` affects only the job
you name.

## Pause and resume

To hold the running service at safe checkpoints without stopping it:

```
uv run vaultspec-rag server pause
uv run vaultspec-rag server resume
```

Pause before maintenance that shouldn't race with indexing. To observe whether the service is quiet and what capacity the device has, without authorizing any GPU work:

```
uv run vaultspec-rag server preflight
```

## Stop and restart the service

```
uv run vaultspec-rag server stop
```

To restart, stop and start again. No single restart command exists.

Stopping is safe on both platforms, and the vector store recovers either way. The platforms differ in how the stop reaches the daemon.

On Unix, `server stop` sends `SIGTERM`, which drives the daemon's own graceful shutdown. It removes the status file and stops the Qdrant child last, so the store stays reachable until the service is down. The stop escalates to `SIGKILL` if the drain window expires.

On Windows, the daemon runs detached from any console, so a separate process cannot deliver `CTRL_BREAK` to it. The stop degrades to a bounded force-kill. The daemon runs none of its own teardown, so the CLI reaps the managed Qdrant child and clears the discovery pointer itself. The result is abrupt but safe.

`server stop --json` emits one outcome envelope per exit path for scripting. Every termination writes a shutdown audit line naming the initiating process, so you can always answer who stopped the service. On Windows the CLI writes that line itself, because the force-killed daemon never runs its own shutdown record.

## Running it automatically

vaultspec-rag ships no service-manager integration. No systemd unit, launchd agent, or Windows service ships with it, and `server start` installs none. To run the service at login or boot, wrap `uv run vaultspec-rag server start` in your own unit, and point it at the project directory so it inherits the right Python environment.

## Keep the index fresh automatically

Automatic updates are on by default: the service watches your files and reindexes changes, so you rarely index by hand. Manage updates on a running service:

```
uv run vaultspec-rag server updates status
uv run vaultspec-rag server updates start <project>
uv run vaultspec-rag server updates stop <project>
uv run vaultspec-rag server updates timing <project>
```

To re-time updates for a project, pass `--update-delay-ms` or `--repeat-update-delay-s` to `server updates timing`. A value of `0` on either delay means "no delay", not "disabled".

The single off switch is `--no-updates` at start time, or `VAULTSPEC_RAG_WATCH_ENABLED=0`. For debounce, cooldown, and how changes are batched, see the [automation guide](automation.md).

## Manage projects

One service serves many projects. To list the loaded project slots:

```
uv run vaultspec-rag server projects list
```

To unload one:

```
uv run vaultspec-rag server projects unload <project>
```

The service evicts idle projects over time, so you don't normally need to unload by hand. Unload when you want to free a slot right away.

## Which Python environment runs the service

`server start` spawns the daemon using the interpreter of the environment you launched it from, and the daemon inherits that environment's packages, including PyTorch. So the environment decides which accelerator the service can use.

To see which environment is running the service, read the `Service env:` line in `server status`.

Starting from an environment without a supported accelerator fails immediately. `server start` refuses if the environment has no torch, has no supported accelerator, or has MPS CPU fallback enabled. It names the interpreter and the reason rather than spawning a daemon that crashes during model load.

A globally installed CLI is a fine client but is not a suitable service launcher unless its tool receipt pins the CUDA wheel. The [installation guide](installation.md) covers that pin, and the [architecture overview](architecture.md) covers why the accelerator is required at all.

## HTTP monitoring routes

The running service exposes read-only HTTP routes on loopback:

- `GET /health` - service health. Ungated.
- `GET /readiness` - dependency readiness. Requires the service token.
- `GET /logs` and `GET /logs/json` - grouped service and Qdrant log lines. Require the service token.
- `GET /jobs` - indexing activity. Requires the service token.
- `GET /metrics` - Prometheus metrics. Requires the service token.

Token-gated routes take the service token as a bearer: `Authorization: Bearer <service_token>`. The token is in the status file at `~/.vaultspec-rag/service.json`, and `/health` also returns it.

The token plus loopback binding is a monitoring gate, not an authentication boundary. Keep the service loopback-bound.

The Model Context Protocol (MCP) server is a separate stdio process, not mounted on this HTTP service. It delegates to these same routes over loopback. See the [MCP guide](mcp.md).

## Manage the Qdrant server

Use `server qdrant install`, `server qdrant status`, and `server qdrant clean`. The [backends guide](backends.md) covers the workflow.

## Storage maintenance

Once running, the service maintains its own storage. An hourly cycle reclaims namespaces whose source roots have gone, archives data-bearing ones first, and reports disk health. Each cycle appears in `server jobs` and the `/metrics` gauges.

For what qualifies as reclaimable, the grace windows, the archives, and manual pruning, see the [storage maintenance guide](storage-maintenance.md).

## Troubleshooting

### Port already in use

Another process is bound there. Use one port consistently: pass `--port N` or set `VAULTSPEC_RAG_PORT`, so commands and the service agree.

### Status reports crashed or divergent (exit 4)

The status file disagrees with the live process. Re-run `server start` to overwrite it cleanly. If that doesn't clear it, delete the status file at `~/.vaultspec-rag/service.json` and start again.

### The service won't stop

A stale process ID can keep `server stop` from completing. Kill the process by its ID, then remove the status file at `~/.vaultspec-rag/service.json`.

### The managed server can't start

Server mode needs the Qdrant binary. Provision it with `server qdrant install`, or run local-only with `server start --local-only`.

### `server start` says the environment cannot run the service

The Python environment you launched it from has no supported accelerator. On Linux or Windows, run `vaultspec-rag install`, then `uv sync`, to install the CUDA wheel. On Apple silicon, install the standard macOS PyTorch wheel and make sure `PYTORCH_ENABLE_MPS_FALLBACK` is unset or `0`. The service never runs on the CPU. See [Which Python environment runs the service](#which-python-environment-runs-the-service).

### The index seems stale

Check `server updates status` and `server jobs` before reindexing. Automatic updates may be catching up, or an update may be in flight. Don't reindex by hand while updates are running: manual reindexing competes for the single-writer accelerator and Qdrant path.

### Something else

Capture `server doctor --json`, `server status --json`, and `server logs`, then open an issue on the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues). Those three outputs are what a maintainer needs to reproduce a service fault. The tracker takes questions as well as bug reports.

## Where to go next

- [Getting started](getting-started.md) walks through a first index and search.
- [Installation](installation.md) answers how to install and provision the workspace.
- [Backends](backends.md) answers how the managed server compares with the local-only store.
- [Architecture](architecture.md) answers how the service, the models, and the store fit together.
- [Automation](automation.md) answers how automatic updates behave.
- [Search and index](search-and-index.md) answers how to search and index through the service.
- [Storage maintenance](storage-maintenance.md) answers how to survey and reclaim index storage.
- [MCP integration](mcp.md) answers how to reach the service from an AI assistant.
- [CLI reference](cli.md) catalogues every command, flag, field, and exit code.
