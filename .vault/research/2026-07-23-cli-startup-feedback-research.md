---
tags:
  - '#research'
  - '#cli-startup-feedback'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:d2ed1554696241a011be880859c8f66cb039c8145687536e3178bb8a2104b874'
related:
  - "[[2026-04-12-index-progress-bars-adr]]"
  - "[[2026-06-01-service-operability-adr]]"
---

# `cli-startup-feedback` research: `async live progress during service and index startup`

`vaultspec-rag server start` runs to readiness in near-silence: on a cold start
it can spend many seconds provisioning the Qdrant binary and minutes loading
GPU models, during which the operator sees a single static spinner and cannot
tell a live warm-up from a wedged process. The question is how to report
genuine, live per-stage progress to the CLI while the work runs inside a
separate daemon process. The evidence is that the CLI and the work are on
opposite sides of a process boundary the daemon spawns, so no in-process
progress callback can reach the CLI: progress must be *published* by the daemon
and *polled and rendered* by the CLI. A minimal increment of that shape already
ships (a coarse per-stage `phase_detail` string in the start spinner); the open
design space is how granular the published progress should be, what transports
it, and how the CLI renders it - which is what the ADR must settle.

## Findings

### The start command blocks on a poll loop with a Rich spinner, not on the daemon directly

`server start` spawns the daemon, then waits in `_await_service_ready`
(`src/vaultspec_rag/cli/_service_start.py:750`), which polls `/health` with
exponential backoff up to a 300s deadline while displaying a Rich
`console.status` spinner (suppressed under `--json`). The spinner text is
produced by `_startup_phase_label` (`src/vaultspec_rag/cli/_service_start.py:734`).
Until recently that label collapsed the entire cold start to one string,
"warming (loading models)"; commit `034a0dd4` made it render a per-stage
`phase_detail` the daemon publishes. So the CLI already has a live render loop
and a wired data channel - the question is the richness of the signal, not
whether one can exist.

### The daemon is a separate process; progress can only cross by publish-and-poll

The daemon is spawned (and, through the venv stub, relaunched) as its own
process; the CLI holds no handle to its in-process state. The only channels the
CLI reads back are the daemon's `/health` endpoint (available only once the port
binds) and the machine-discovery / service-status view it writes via
`_DiscoveryPublisher` (`src/vaultspec_rag/server/_lifecycle.py:206`), read by
`_read_service_status`. Before the port binds - which is exactly the
provisioning and model-load window the operator most wants feedback on - only
the published status view is observable. Any "genuine async live progress"
therefore reduces to: the daemon publishes structured progress into that view
(or an equivalent side channel), and the CLI polls and renders it. There is no
callback or shared-memory path across the boundary to exploit.

### The cold-start stages differ sharply in cost and in whether sub-progress is measurable

The pre-yield startup runs in `_start_components`
(`src/vaultspec_rag/server/_lifespan.py:368`): first-use Qdrant provisioning
and server start (`start_supervised_from_config`, which downloads and
SHA-verifies the pinned binary before spawning), a storage-manifest reconcile,
then `load_model` and the reranker load. The dominant wall-clock cost is model
loading (a first run also downloads weights from Hugging Face); provisioning is
seconds-to-minutes only on first use. This matters to the ADR because the stages
admit *different* progress fidelities: a binary download and a weights download
expose byte counts (a real percentage), model load exposes a discrete
"N of M models" count, and a manifest reconcile is effectively a spinner-only
step. A one-size signal (a bare phase string) underserves the stages that could
show a bar.

### A genuine progress-reporter abstraction already exists, but it does not cross processes

The `index-progress-bars` decision introduced a Rich-decoupled `ProgressReporter`
(with a `NullProgressReporter`) so the indexer emits granular per-document
progress without importing Rich. The daemon's startup index paths pass
`NullProgressReporter` today, so any indexing the daemon performs at or after
startup emits no progress the operator sees. The reporter is the right
in-process vocabulary, but it terminates inside the daemon; to reach the CLI its
output would still have to be published into the cross-process view. The ADR
should decide whether the published startup-progress contract reuses that
reporter's phase/advance/total vocabulary (so the daemon can forward reporter
events straight into the status view) or defines its own smaller startup schema.

### "Service startup" and "index startup" are distinct progress surfaces

Two different waits are in scope. Service readiness (provision + model load) is
what `server start` blocks on and ends when `/health` is ready. Index build
progress is a separate, longer, post-ready activity: the daemon auto-reindexes
on file changes and can restore interrupted jobs, and `vaultspec-rag index`
already renders granular bars in-process (the `index-progress-bars` surface).
The user ask spans both, but they have different consumers - the start spinner
for the former, a jobs/progress surface for the latter - and the operability
decisions already cover job/status reporting. The ADR should scope which surface
this feature owns and where it defers to the existing jobs-operability contract
rather than duplicating it.

### Transport options for the published progress signal

- **Extend the discovery/status snapshot** with a structured progress field
  (the current `phase_detail` string is the minimal instance; a richer form
  adds an optional stage id plus `done`/`total` or a fraction). Pro: reuses the
  atomic status-write path and the existing CLI poll; con: the snapshot is
  rewritten wholesale each publish and carries a machine-singleton write lock,
  so high-frequency percentage updates would contend on that lock.
- **A dedicated progress side file** the daemon rewrites at a high cadence and
  the CLI tails, separate from the singleton status write. Pro: decouples
  chatty progress from the authoritative status claim; con: a second file to
  keep consistent and clean up.
- **Structured progress log events** the CLI tails from the daemon log. Pro: no
  new schema; con: parsing prose logs is brittle and the log path is already
  surfaced only as a fallback.

The trade-off the ADR must weigh is update frequency versus contention on the
authoritative status write, and whether a percentage-granular bar is worth a
second transport.

### Rendering and mode constraints the design must respect

The CLI already owns the only Rich surface; it can drive a `Progress` bar from
published counts as readily as it drives the current spinner. Any design must
keep `--json` mode emitting exactly one structured envelope with no spinner
(`_await_service_ready` already branches on this), keep publication best-effort
so a progress-write failure never fails startup (the daemon's phase publishes
are `require=False`), and stay within the existing readiness deadline. Not
investigated: whether Hugging Face's downloader and the pinned-binary downloader
expose incremental byte callbacks the daemon could forward - a prerequisite for
true download percentages, and a concrete question the ADR or its plan should
resolve before committing to bar-granularity for the download stages.

## Sources

- `src/vaultspec_rag/cli/_service_start.py:734` - `_startup_phase_label`, the
  spinner label.
- `src/vaultspec_rag/cli/_service_start.py:750` - `_await_service_ready`, the
  poll-and-render wait loop.
- `src/vaultspec_rag/server/_lifespan.py:368` - `_start_components`, the
  pre-yield cold-start sequence (provision, reconcile, model load, reranker).
- `src/vaultspec_rag/server/_lifecycle.py:206` - `_DiscoveryPublisher`, the
  cross-process status/discovery publisher the CLI reads back.
- commit `034a0dd4` - the coarse `phase_detail` per-stage increment already
  shipped.
- Hugging Face Hub download API: https://huggingface.co/docs/huggingface_hub
