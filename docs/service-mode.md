# Run the background service

Run vaultspec-rag as a long-lived background service to keep the models loaded and, in managed-server mode, the Qdrant server running. The first query pays the model-loading cost once, and every later query reuses the already-loaded models.

This guide assumes the workspace is installed and its service environment has a PyTorch build for CUDA or Metal Performance Shaders (MPS). In managed-server mode, `install` or a host `server start` fetches missing model files and the Qdrant binary. In local-only mode, it fetches missing model files but does not need or fetch the Qdrant binary. A start never changes the PyTorch build. If you have not set up the workspace, start with the [installation guide](installation.md).

Starting the service also requires the compiled browser monitor executable; see
[local browser monitor setup](#local-carbon-browser-monitor).

For the choice between the managed server and the local-only store, see the [backends guide](backends.md). For the vocabulary used here, see the [glossary](glossary.md).

Examples use the `uv run` prefix, which runs the command inside a project environment.
If you installed vaultspec-rag as a standalone tool, drop the prefix and call
`vaultspec-rag` directly; see the [installation guide](installation.md) for lane selection.

## Start the service

Run:

```
uv run vaultspec-rag server start
```

Before it starts anything, the command checks that the environment can run the service, then makes sure the model files are present and, in managed-server mode, that the Qdrant binary is available. It downloads whichever required item is missing and shows the transfer. In local-only mode, the Qdrant step is skipped. It prints each outcome under `Provisioning:` in the words `install` uses, and names an operator-supplied Qdrant binary as such. A download that fails, or a model that is missing while the Hugging Face Hub is in offline mode, stops the start there with the reason, before any daemon exists.

In managed-server mode, the command starts the Qdrant server on loopback at
`http://127.0.0.1:8765`; in local-only mode, it uses the in-process store and starts
no Qdrant server. It warms the models, binds the service on port 8766, writes a status
file, and polls until the service reports ready.

To keep `server start` from downloading the Qdrant binary, pass `--no-qdrant-auto-provision` or set `VAULTSPEC_RAG_QDRANT_AUTO_PROVISION=0`; a missing binary then fails the start with the install command. See [managed server provisioning](configuration.md#managed-server-provisioning).

If you don't want a managed server, run local-only instead:

```
uv run vaultspec-rag server start --local-only
```

The default index profile accepts only the managed server, so also set
`VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE=embedded-local` in the environment that starts the
service. See [the installation guide](installation.md#what-you-need-before-you-start).
`install --local-only` records the choice, so a later `server start` needs no flag.

Start it from a host installation, the one that carries the `gpu` extra. The service runs in whatever Python environment launched it, which is why `uv run` is the documented form for a project that depends on `vaultspec-rag[gpu]`; see [Which Python environment runs the service](#which-python-environment-runs-the-service). A client installation, without the `gpu` extra, cannot start it.

`server start` detaches: it returns once the service is ready and leaves the daemon running. A service unit that wraps it needs oneshot or remain-after-exit semantics, or the manager treats the returned command as a stopped service.

Other start flags control the port, automatic updates, update timing, and the managed server. The [CLI reference](cli.md) carries the full list.

## Confirm it is running

### Monitor the service in a browser

The binary installation includes `vaultspec-rag-monitor`. Put the archive's extracted
directory on `PATH` before starting the service. A Python host installation can select
that executable with `VAULTSPEC_RAG_MONITOR_BINARY`, set to its absolute path.

The service supervisor launches the monitor after backend readiness, beginning at the
backend port plus one and choosing the next available higher port. It records the
chosen address with service discovery and stops its owned monitor when the service
stops. The monitor uses the service's initialized Python runtime for lifecycle and
persisted inventory operations.

For a separate diagnostic session, run `vaultspec-rag-monitor --port 5420` and open
the access link it prints after `vaultspec.monitor.ready`. This directly launched process
uses a strict port and is stopped with Ctrl+C. Its frontend remains useful while the
backend is unavailable; search and backend control retain the host installation's
accelerator and bootstrap requirements.

### Read service status

```
uv run vaultspec-rag server status
```

On a service that has been up for a while, that reads like this example, with the
environment path shortened to its last three segments:

```text
Server: running
Requests: ready for requests
Busy: idle
Address: http://127.0.0.1:8766
Service env: main\.venv\Scripts\python.exe
Uptime: 13 hours 19 minutes
Queue: nothing waiting
Processed jobs: 259 finished, 0 active, 0 waiting, 1 failed
  Last failure: job 9ab3eb6b (timeout), 3 hours 58 minutes ago
  Review failures: vaultspec-rag server jobs --failed
Current job: none active
Next action:
  vaultspec-rag search "<query>" --type code --timeout 120
```

`status` shows whether the service is up, its address, uptime, queue, processed jobs, and a suggested next action. Its `Service env:` line names the Python environment running the service. A failure that has already been retired to the history, as above, does not stop the service being ready: the count is there so a failure cannot pass unseen, and the line below it names the command that shows what happened.

Its exit codes:

- `0` running
- `3` stopped
- `4` crashed, divergent, degraded, or running but unable to serve (`not_serving`); the
  label beside it says which, and [Troubleshooting](#troubleshooting) branches on that
- `5` starting, meaning the daemon holds the machine lock and is loading models; retry shortly

"Divergent" means the status file disagrees with the live process, for example naming a process ID that is no longer alive. If `status` reports crashed or divergent, see [Troubleshooting](#troubleshooting).

To check each dependency rather than the process, run:

```
uv run vaultspec-rag server doctor
```

An example of its output:

```text
Service readiness
Backend: server
Readiness: ready for requests
Live service:
  status: running (running)
  process: pid 57856 (alive)
  network: port 8766 (listening)
  heartbeat: 12s ago
  release: 0.4.21 (matches this client)
Installed dependencies: ready
  torch: ready - CUDA available on NVIDIA GeForce RTX 4080 SUPER
  models: ready - all 3 model repos present in the cache
  qdrant: ready - qdrant binary resolves from provisioned
Provisioning (vaultspec-rag):
  declared mode: tool
  install mode: mismatch - .mcp.json launch shape disagrees with the declared mode
  version floor: ok
```

That capture is a healthy service with one thing to fix, which is the useful case
to see: every dependency reads `ready`, and the last section still reports a
`mismatch` because the `.mcp.json` entry launches the server a different way than
the recorded mode. Search keeps working throughout. Readiness and provisioning are
separate questions, and only the first one decides whether a query returns.

The `release:` line above reads `(matches this client)`, and the release numbers in
these captures are examples from older releases. When the release does not match,
the client refuses the request rather than answering it:

```text
Refusing to search against the running service.
This vaultspec-rag client is 0.4.22 but the running service is 0.4.21.
A daemon from another release drops request fields it does not know rather than
rejecting them, so the answer would be computed over a different candidate set
with nothing to show it.
Next actions:
  1. Restart the service so it runs this install: `vaultspec-rag server stop` then `vaultspec-rag server start`.
  2. Confirm the release: vaultspec-rag server status --verbose
```

That happens after an upgrade that left an older daemon running, and the two
next actions are the whole fix. Line breaks above differ from the
terminal's; nothing else is changed. A client installation cannot start the
service, so it is told instead to pin its project to the service's release, or to
have the service restarted from a host installation running the client's release.

`doctor` reports PyTorch and accelerator readiness, the compute backend (`cuda` or `mps`), the models, and Qdrant. It separately names the storage backend (`server` or `local-only`) and states whether the service is ready for requests. If a dependency reports not ready, follow its detail line, which names either a provision step or an install step.

One failure has a detail line that cannot tell you what to do, because the fix is not an install or a provision step: a corrupt collection in the managed store stops the server from starting at all. `server qdrant quarantine` moves it aside so the server starts again, listing the store's collections when you run it with no name and requiring `--yes` to move one. Nothing is deleted and the affected root re-indexes on its next use. To keep working while you investigate, `server start --local-only` skips the managed store entirely, but only with the `embedded-local` index profile set as described under [Start the service](#start-the-service). The [backends guide](backends.md) covers both.

Both accept `--json`, and `status` accepts `--verbose`. The [CLI reference](cli.md) lists each command's options. Exit codes are in the lists on this page and in the [automation guide](automation.md#exit-codes-and-error-strings).

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

That prints once and exits, which is what you want in a script. Watching an
index run instead wants the live view:

```
uv run vaultspec-rag server jobs --watch
```

`--watch` opens the interactive jobs interface, with per-job controls and a
refresh you can slow down or speed up with `--interval`. It is the command to
reach for while a first index is running on a large tree, where the one-shot
form tells you only what was true at the moment you asked.

The watch separates daemon health and TypeSafe classification from indexing
state. Indexing jobs and queued, processing, and recently finished serving
requests have their own lanes. The focused log follows the selected work and
refreshes without reselection; raw service and Qdrant logs remain grouped by
producer. Each observation shows its freshness, failures, and truncation.

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

Four job signals are worth knowing. A failed job carries a stable `error_kind` in `--json` and on `GET /jobs`, classified once by the service so every surface agrees, and the human feed renders the matching remediation. A running job whose progress hasn't moved for five minutes is flagged `stalled`, so you never have to infer it. A job still queued after five minutes, on a service that isn't paused, degrades health with `jobs_undispatched`: the service starts queued work the moment it is queued, so a job still waiting was left behind and won't start on its own. `server jobs` lists it right after running work, and restarting the service starts it again. If the service process dies mid-job, the next startup restores what it was running as `interrupted`, with the last progress and who started it.

An index job that reused vectors from an already-indexed sibling worktree carries a `reuse` block describing what it avoided re-encoding. See [reusing vectors across worktrees](indexing.md#reusing-vectors-across-worktrees) for the mechanism, and the [CLI reference](cli.md) for the block's fields.

### Local Carbon browser monitor

Use the service commands to start and stop the managed browser monitor:

```bash
uv run vaultspec-rag server start
uv run vaultspec-rag server stop
```

Start prints a `Monitor: http://127.0.0.1:<assigned-port>/#capability=<secret>`
line. Open that whole link in a browser on the machine running the service.
`server status` reports the backend address; its human, verbose and JSON output
do not report the monitor link. To redisplay it, run `server start` again: an
already-running owned service is reused. For scripts, `server start --json`
returns the assignment as `data.monitor_port` and `data.monitor_url` when
recorded.

The link is a credential. Every local account can reach a loopback port, so
the monitor operates the service only for a caller that presents the
capability in the link. The monitor mints a new one each time it starts and
keeps it in memory; the daemon records the link in its owner-only discovery
file. The page moves the capability out of the address bar into that tab's
session storage, so a new tab needs the link again, and a bookmark of the bare
address shows a notice instead of the service. Treat the link like the service
token: do not paste it into shared logs or tickets. Restarting the service
replaces it.

The monitor port starts at the backend's actual port plus one and advances
until free. With the default backend port 8766, it first tries 8767. For a
custom backend port:

```bash
uv run vaultspec-rag server start --port 9000
```

The monitor tries 9001, then 9002 if 9001 is occupied. Use the printed URL
because a later start may choose another port. The backend itself still
refuses an occupied requested port.

The daemon records the actual monitor port and process identity in its managed
user scratch directory. `server stop` stops both processes and removes their
assignments. A forced daemon death also closes the monitor's parent pipe and
stops its web server; a later stop cleans any remaining scratch identity.
Stopping the service from this managed browser also closes its web server.

Managed startup requires the compiled `vaultspec-rag-monitor` command on
`PATH`, or its absolute path in `VAULTSPEC_RAG_MONITOR_BINARY`. The monitor
contains the frontend resources and runtime; startup does not compile sources
or require a checkout, Node or Bun. A missing or failed executable fails the
coupled start and cleans up the frontend child. Building and bundling the
executable are separate from this lifecycle integration.

For a standalone development monitor, use the shared harness below.

From a source checkout with the Node/npm versions pinned in `.nvmrc` and
`package.json`, run:

```bash
just init-monitor
just build-monitor
just dev
```

For the accelerator-free lifecycle tests, run `just build-monitor-test` and
set `VAULTSPEC_RAG_MONITOR_BINARY` to the absolute executable path it prints
before running `just test-python`. This uses the pinned release compiler and
embedded Vite assets, marks the local executable as a development build, and
writes it under `dist-bin`. The CI test jobs prepare and select it automatically.

Open the `Monitor:` access link the dev server logs when it starts listening;
`just dev logs` shows it again. The monitor automatically connects to the local
service recorded in the managed status directory. It has no login form,
credential prompt, or admin role: the link's capability is the only caller
credential. The standalone monitor has its own lifecycle.
A stopped service shows a connection
message and retains any previous observations with their timestamps.

The packaged monitor, dev and preview bind to `127.0.0.1`. Dev and preview use
their strict declared ports. The shared
`just dev` harness attaches to a healthy owned server and recreates a stale,
degraded, or foreign server on that port. Its canonical **Dev server** workflow
runs `just dev ci` to verify start, reattach, and stop.

The devservers repository owns the local reverse proxy at
`https://vaultspec-rag-monitor.localhost`; append the logged link's
`#capability=...` fragment to that address. Every monitor request requires a
loopback client and a local Host, with a matching browser Origin when supplied.
Every read and control under `/api/monitor/` also requires the capability as a
bearer credential, and is refused with 401 before the monitor reads the service
token or runs a service command. The service token itself is not accepted
there. Tailnet reachability and forwarded identity headers do not authorize
access.

For remote use, connect through an authenticated SSH tunnel to the printed
loopback monitor address and open the full access link through it. Direct
remote access and Tailscale Serve exposure are unsupported. Keep local proxies
local; a proxy that rewrites remote requests to a loopback Host would defeat
the loopback boundary and leave the capability as the only control.

Health and TypeSafe details sit above separate indexing and serving tabs.
Inspect a job or request for its current details and correlated live logs;
service and Qdrant logs have their own panels. Job controls follow the service's
reported capabilities, and requested state stays distinct from observed state.
Deleting a finished job record asks for confirmation.

Work pages show up to 100 records, and each log panel requests the latest 200
matching records. Counts describe the service's retained snapshot and recent
history. **Pause live updates** pauses browser polling; the service continues
working. Resume updates to observe new work again.

Background browser tabs stop polling and retain the last displayed data.
Returning to the tab refreshes it immediately, unless live updates were
manually paused.

The built preview at `http://127.0.0.1:5421` uses the same automatic local
connection. Serving the static assets alone does not provide that connection.
Use `just dev stop` to stop this checkout's browser servers.

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

This also stops the managed browser monitor and clears its recorded port
assignment. A separately launched development monitor keeps its own lifecycle.

To restart, stop and start again. No single restart command exists.

Stopping is safe on both platforms, and the vector store recovers either way. The platforms differ in how the stop reaches the daemon.

On Unix, `server stop` sends `SIGTERM`, which drives the daemon's own graceful shutdown. It removes the status file and stops the Qdrant child last, so the store stays reachable until the service is down. The stop escalates to `SIGKILL` if the drain window expires.

On Windows, the daemon runs detached from any console, so a separate process cannot deliver `CTRL_BREAK` to it. The stop degrades to a bounded force-kill. The daemon runs none of its own teardown, so the CLI reaps the managed Qdrant child and clears the discovery pointer itself. The result is abrupt but safe.

`server stop --json` emits one outcome envelope per exit path for scripting. Every termination writes a shutdown audit line naming the initiating process, so you can always answer who stopped the service. On Windows the CLI writes that line itself, because the force-killed daemon never runs its own shutdown record.

## Running it automatically

vaultspec-rag ships no service-manager integration. No systemd unit, launchd agent, or Windows service ships with it, and `server start` installs none. To run the service at login or boot, wrap `uv run vaultspec-rag server start` in your own unit, and point it at the project directory so it inherits the right Python environment. Because `server start` returns once the service is up, give the unit oneshot or remain-after-exit semantics.

## Keep the index fresh automatically

Automatic updates are on by default: the service watches your files and reindexes changes, so you rarely index by hand. Manage updates on a running service:

```
uv run vaultspec-rag server updates status
uv run vaultspec-rag server updates start <project>
uv run vaultspec-rag server updates stop <project>
uv run vaultspec-rag server updates timing <project>
```

To re-time updates for a project, pass `--update-delay-ms` or `--repeat-update-delay-s` to `server updates timing`. A value of `0` on either delay means "no delay", not "disabled".

The single off switch is `--no-updates` at start time, or `VAULTSPEC_RAG_WATCH_ENABLED=0`. The legacy debounce and cooldown inputs remain compatibility mappings for the adaptive bounds. See the [automatic convergence reference](automatic-convergence.md) for policy keys, limits, controller states, and telemetry.

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

A client installation, without the `gpu` extra, never launches the service: its `server start` succeeds only when a service at the client's release is already running, and otherwise names the `gpu` extra as the fix. Start the service from the host installation instead. A standalone tool installed with `[gpu]` is a host installation, and on Linux or Windows it can launch the service only if its tool receipt pins the CUDA wheel. The [installation guide](installation.md) covers that pin, and the [architecture overview](architecture.md) covers why the accelerator is required at all.

## HTTP monitoring routes

The running service exposes token-gated HTTP routes on loopback. Most are read-only monitoring routes. Mutating routes exist too, all behind the same token: `POST /search`, `/reindex`, `/clean`, `/pause` and `/resume`, `PUT /jobs/{job_id}/desired-state`, and `DELETE /jobs/{job_id}`, among others. The monitoring routes are:

- `GET /health` - service health. Ungated.
- `GET /readiness` - dependency readiness. Requires the service token.
- `GET /logs` and `GET /logs/json` - grouped service and Qdrant log lines. Require the service token.
- `GET /jobs` - indexing activity. Requires the service token.
- `GET /metrics` - Prometheus metrics. Requires the service token.

Token-gated routes take the service token as a bearer: `Authorization: Bearer <service_token>`. The token is in the status file at `~/.vaultspec-rag/service.json`, and `/health` also returns it.

The token plus loopback binding is a local access gate, not an authentication boundary. Keep the service loopback-bound.

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

Exit `4` covers two different faults, and the fix for one is the wrong move for
the other. Read the label `status` printed beside it rather than the code alone.

**`crashed (its process is no longer running)`, `crashed (its process ID now belongs to another program)`, `crashed (its port gives no usable answer)`, or `crashed (it stopped reporting that it is alive)`, or a divergent status file.** No daemon is serving. The status file disagrees with the live process -
naming a process id that is no longer alive, for instance. Re-run `server start`
to overwrite it cleanly, and if that does not clear it, delete the status file at
`~/.vaultspec-rag/service.json` and start again.

**`unreachable (a service holds this machine but its address cannot be trusted)`.**
A daemon is alive and holding the lock; what is missing or unreadable is the pointer it
should have published. `server doctor` shows what holds the machine. Deleting the file
does not help - the holder is the only writer of canonical discovery, so nothing
you delete makes it publish - and starting a second daemon only loses the race
for the lock. Run `server reconcile` and give it time to converge. If it exits
without converging, the holder is wedged: stop it (`server stop`, and on a
resistant process by its own PID, which the label names) and start again.

**`running but unable to serve (its search models never loaded)`.** The process is up,
but it cannot answer searches. Run `server doctor` to see why the models did not load,
then restart with `server stop` and `server start`.

### The service won't stop

A stale process ID can keep `server stop` from completing. Kill the process by its ID, then remove the status file at `~/.vaultspec-rag/service.json`.

### The managed server can't start

Server mode needs the Qdrant binary. `server start` downloads it when it is missing, unless that download is switched off, in which case provision it with `server qdrant install`. If the start reports `qdrant_binary_unverified`, the installed binary failed its checksum: replace it with `server qdrant install --upgrade`. If it reports `qdrant_binary_invalid`, `VAULTSPEC_RAG_QDRANT_BINARY` names something that is not an absolute path to a regular file: correct or unset it. The [installation guide](installation.md#server-start-cannot-find-the-qdrant-binary) covers each case. To run without the managed server, use `server start --local-only` and the `embedded-local` index profile (see [Start the service](#start-the-service)).

### `server start` says the environment cannot run the service

The Python environment you launched it from cannot run the service. If the message says the installation is a client, you started it from an environment without the `gpu` extra: run `server start` from the host installation instead. Otherwise the environment has no supported accelerator. On Linux or Windows, for a project that depends on `vaultspec-rag[gpu]`, run `uv run vaultspec-rag install`, then `uv sync --reinstall-package torch`, to install the CUDA wheel; for a standalone tool, follow the [GPU build pin](installation.md#pin-the-gpu-build). On Apple silicon, install the standard macOS PyTorch wheel and make sure `PYTORCH_ENABLE_MPS_FALLBACK` is unset or `0`. The service never runs on the CPU. See [Which Python environment runs the service](#which-python-environment-runs-the-service).

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
- [CLI reference](cli.md) catalogues every command and flag.
