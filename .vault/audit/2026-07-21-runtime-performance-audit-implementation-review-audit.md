---
tags:
  - '#audit'
  - '#runtime-performance-audit'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Runtime performance audit: service, indexing, search, and logs

## Verdict

The reviewed runtime paths are materially safer and more predictable than the
pre-audit baseline. The implemented changes remove unbounded raw-log growth,
corpus-sized vector retention, eager incremental chunk materialization,
quadratic scan accounting, unbounded preprocessing submission, unsafe
incremental replacement ordering, and one-second watcher failure storms.

The patch set intentionally contains no legacy response adapters, state-schema
fallbacks, or compatibility branches. Removed private behavior stays removed.

## Scope and method

The audit covered service startup and watcher ownership, managed service and
Qdrant logs, operator status/log responses, search rendering and candidate
selection, source discovery, preprocessing, full and incremental code indexing,
Qdrant write deadlines, GPU critical sections, failure recovery, and restart
convergence.

Evidence came from source review, independent adversarial reviews, strict static
analysis, real filesystem and multi-process lock tests, real local Qdrant tests,
pinned supervised-Qdrant tests, real model/GPU integration tests, and a synthetic
large-index producer benchmark. Tests did not introduce fakes, mocks, runtime
patching, skips, or expected failures.

## Implemented corrections

### Storage deadlines and liveness

- Qdrant operations now honor the configured operation timeout instead of an
  unrelated client default (`1a09067`).
- Transient store retries are capped by both attempt count and the remaining
  run budget (`6c94136`).
- A durable run-liveness policy exists for future storage-confirmed progress
  ownership (`51c3594`). It is deliberately not wired into production indexing
  until the W02 run ledger supplies authoritative durable progress; resetting a
  timeout from producer activity would make a wedged store appear healthy.

### Bounded index production

- Source scanning and line accounting are linear (`d467328`).
- Preprocessing retains a continuously refilled bounded future window rather
  than one future per file (`587933a`).
- Code chunks cross the producer boundary as immutable file-local segments,
  capped at 8 MiB, and enter a queue bounded by both chunk count and weighted
  bytes (`0732900`).
- Full indexing uses the weighted streaming producer (`35cc9d7`). Both unscoped
  and scoped incrementals use the same bounded publication path (`dede3a4`,
  `c4196f7`).
- Dense and sparse vector owners are released after each store operation, and
  device-to-CPU transfer remains outside the forward-pass-only GPU gate.
- Incremental publication snapshots every attempted path before the first
  upsert, confirms new content before deleting obsolete IDs, and rolls back IDs
  introduced by a failed partial publication (`1981060`). This covers new,
  modified, deleted, scoped, and unscoped retry convergence.

### Search and operator views

- Search timeout resolution rejects non-finite and non-positive values and
  retains the bounded production default.
- Human rendering consumes only the bounded public snippet. It no longer reads
  and splits each source file for every hit or falls back to a removed private
  reranker field.
- Domain-filter candidate backfill restores the full rerank window so the
  optimization does not change ranking semantics.
- Search status and log responses clamp item counts and encoded bytes before
  crossing the service boundary (`3395353`).

### Unified bounded logging

- Python records and raw service stdout/stderr share one managed binary sink;
  raw Qdrant stdout/stderr uses the same sink implementation and retention
  policy (`d4a0505`).
- Service and Qdrant each receive a 10 MiB per-generation default with five
  backups. Both configuration values reject unbounded input.
- Rollover preserves complete lines, bounds an incomplete-line tail, handles a
  Windows reader retaining the active path, and prevents an old drain thread
  from writing into a replacement child's log.
- CLI and server parsing use the same source-grouped contract, stable ordering,
  record cap, line cap, response-byte cap, filters, and visible truncation
  metadata. Neither path reads the entire retained history into an operator
  response.

### Watcher retry and convergence

- Retry and circuit state is durable per canonical root and source, current
  schema only, and serialized by a shared-deadline thread/file lock
  (`b4dc437`).
- Only explicit timeout and unavailable outcomes retry. Admission, disk,
  memory, schema, invalid path, invalid lock-file, and marker-cleanup failures
  fail closed.
- Event collection and indexing dispatch are separate. An accepted event is
  generation-marked before dispatch, events arriving during an active attempt
  advance the durable generation, and externally authored or restart-restored
  generations require an unscoped convergence pass.
- Replacement startup retries transient state-lock contention, and every idle
  dispatch refreshes durable state so a retiring watcher cannot strand intent
  behind a cached clean view.
- Admission and outcome settlement defer cancellation for a three-second state
  transaction window, then wait at most two seconds for a lock-independent
  recovery marker. Each marker carries root/source authority and a unique claim
  fence: the next owner clears only the abandoned attempt it names, preserves a
  newer live claim, and performs unscoped convergence. Mixed vault/code batches
  start both handoffs concurrently and settle both source obligations before
  cancellation is delivered. Marker content is flushed through a unique
  non-discoverable temporary file and atomically published; transient handoff
  I/O retries within the two-second budget. Invalid or undeletable markers fail
  closed instead of creating a permanent reindex loop. A live unmatched fence
  remains for its exact in-flight policy; owner PID/start-time validation lets a
  later process consume it only after the original process is confirmed dead.
  Admission ownership and token reservation publish atomically before native
  scheduling; a pre-start handoff cancels the reservation while an active
  admission remains fenced. An exact bounded in-process admission-token
  registry consumes completed stale fences without waiting for process exit.
  Non-discoverable crash temporaries require a one-hour timestamp grace before
  cleanup, processed in bounded 1,024-entry passes. Abandonable native state
  calls have four non-blocking worker slots, so stalled filesystem threads
  cannot grow without bound. Two separate bounded handoff slots keep marker
  publication available when all ordinary state workers are occupied.
- Naturally exited watcher tasks are removed from the service registry.

## Performance evidence

The weighted producer benchmark processed 83,624 files and 250,872 chunks as
4,646 slices in 10.627 seconds, or 23,608 chunks per second. The largest slice
and queue occupancy were 54 chunks and 133,936,146 estimated bytes. Traced
coordinator memory was 0.369 MiB. Cross-flush ordering and slice bounds were
validated during the same run.

The final watcher suite passed 48 tests covering real files, real child
processes, lock contention, cancellation, local Qdrant, watcher configuration,
failure backoff, restart, and physical payload convergence. Two additional
pinned real-Qdrant server-mode deletion tests passed. Ruff formatting and lint,
BasedPyright, Python compilation, and diff whitespace checks passed for the
final watcher implementation and tests. With both source locks held for 30
seconds, mixed-source cancellation published both recovery markers and returned
in about 3.25 seconds. The final independent Terra xhigh adversarial review
reported no critical, high, or medium findings after rechecking worker-capacity
isolation and admission/marker linearization.

Earlier focused suites for storage retry, scanning, preprocessing, bounded
segments, full and both incremental production paths, search/status/log views,
and raw-log rollover passed at their respective commits.

## Hugging Face 404 log entries

The observed Hugging Face 404 entries are optional SentenceTransformers model
artifact probes, including adapter or processor configuration files. Model
initialization succeeds after those probes, so they are not missing required
runtime assets or a retry failure. Production daemon logging raises routine
`httpx` and `httpcore` traffic to WARNING; pytest capture can still expose the
underlying informational requests.

## Remaining planned work and constraints

- W02 must make the durable run ledger the production owner of
  storage-confirmed progress before the run-liveness policy can safely terminate
  a no-progress index.
- Worker IPC still returns one whole-file/fixed-batch result, and non-vector
  path, metadata, and identity sets remain corpus-sized. These are the next
  memory ceilings after vector-bearing production was bounded.
- Watcher job calls remain on the existing job surface until W03 completes the
  canonical job-manager and direct circuit-observability migration. No parallel
  compatibility authority was added here.
- The concurrent W02 `jobs.py` rewrite attempts a parent-directory `fsync` on
  Windows and can emit a debug traceback per durable progress write. That file
  was not mixed into this patch while another workstream owns its large rewrite;
  its owner should use the same explicit Windows no-op already used by watcher
  state persistence.
- A fresh current-source end-to-end service saturation benchmark was not run
  against the resident daemon because that process and an unrelated index run
  shared the single GPU. Focused real-GPU and real-Qdrant verification passed,
  but no new whole-service tail-latency claim is made from a non-isolated GPU.

These items are explicit plan work or environment constraints, not hidden
acceptance claims. The reviewed fixes do not require backward-compatibility
code to address them.
