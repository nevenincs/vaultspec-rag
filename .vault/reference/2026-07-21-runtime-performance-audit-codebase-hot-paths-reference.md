---
tags:
  - '#reference'
  - '#runtime-performance-audit'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:2ee34e3b88423bdf56f35b55dcd28074fbc19a05d3748e628163dc1091b35b97'
related: []
---

# `runtime-performance-audit` reference: `service, indexing, search, and log hot paths`

This audit examined the production service lifecycle, watcher, index pipeline,
hybrid search, and managed-log surfaces. Sources included the current code and
tests, the installed library implementation used by the reranker, live service
status and logs, focused microbenchmarks, and the governing service-concurrency,
GPU-gate, storage-lock, managed-log, search-noise, and large-index decisions.

## Summary

The dominant live failure was lifecycle contention rather than log parsing. A
machine service was warming while an auto-discovered CLI index command failed
to connect and silently enabled local fallback in `cli/_index.py:508-513`.
That produced a second GPU-heavy indexer alongside the daemon. The two processes
held roughly 2.7-3.1 GiB resident memory each, the GPU reached 100 percent load
and 15,865 of 16,376 MiB, two watcher jobs stopped making visible progress, and
read-only semantic discovery repeatedly exceeded 60 seconds. The existing
machine-singleton decision already makes the resident service the GPU owner, so
local fallback must be refused whenever `machine_lock_live_holder()` reports a
live owner, including the warming phase. Explicit `--allow-fallback` is not
authority to violate that singleton.

Managed log reads are already bounded and fast. Reading eight real log sources
totalling 10.87 MiB averaged 15.6 ms for 200 rows, 37.6 ms for 5,000 rows, and
41.3 ms for a filtered 5,000-to-200 result. The write path is the regression:
`server/_main.py:137` first installs core's Rich root handler, then
`logging_config.py:501-550` adds a rotating handler and redirects stderr into
the same file. Each Python record therefore arrives once through the rotating
handler and once through Rich on redirected stderr. A live sample contained
180 `service.search completed` lines representing 90 events. The active log
also accumulated 1,375 INFO-level HTTP client records, about 470 KiB in fourteen
minutes. The daemon should have one canonical root handler while raw stdout and
stderr remain redirected, and `httpx`/`httpcore` routine request chatter should
be WARNING unless explicitly debugged.

Index discovery has four linearity and parity defects:

- `indexer/_ignore_specs.py:23-55` performs an unpruned `rglob` before the
  pruned source scan. Resolving scan inputs took 7.58 seconds on this tree while
  the actual pruned scan took 0.62 seconds. A top-down walk can prune the fixed
  always-excluded directories without changing nested gitignore semantics.
- `indexer/_chunking.py:309-316` calls `read_bytes()` and then slices 8 KiB,
  allocating the whole file. An 8 MiB probe peaked at about 8.01 MiB; a bounded
  binary stream read avoids size-proportional memory.
- `indexer/_chunk_worker.py:593-637` repeatedly counts newlines from the start
  for every fallback chunk. Timings for 100k, 200k, and 400k characters were
  0.010, 0.039, and 0.171 seconds, consistent with quadratic growth.
  `indexer/_ast_chunker.py:154-169` has the same prefix-slice/count pattern and
  measured 0.309, 1.563, and 7.042 seconds at 1, 2, and 4 million characters.
  Both can maintain a monotonic line cursor so each character is counted once.
- `watcher.py:31-63` duplicates the supported-extension table and has drifted.
  It misses `.bash`, `.cc`, `.css`, `.html`, `.json`, `.sh`, `.toml`, `.yaml`,
  and `.yml`, while waking for unsupported `.lua`, `.swift`, and `.zig`.
  Its case-sensitive suffix checks also miss supported uppercase extensions.
  The watcher can import the CPU-only `SUPPORTED_EXTENSIONS` source of truth and
  normalize suffixes.

The new batch preprocessing path also has correctness/performance hazards.
`indexer/_codebase_indexer.py:573-600` submits every group at once and retains
all futures and completed result objects despite the single-group-memory claim.
A bounded in-flight window should replenish as tasks complete. More seriously,
`future.result()` and `handle_group()` share one broad exception handler at
`indexer/_codebase_indexer.py:589-598`; GPU encode or storage failures in the
handler are misreported as worker failures and swallowed. Similar broad catches
at lines 623-640, 716-731, 785-792, 832-842, and 975-981 swallow the documented
`PreprocessAbortError` for `on_error = "fail"`. Worker file-read failures may be
reported and continued, but explicit preprocess aborts and downstream
publication failures must propagate so stale-vector cleanup cannot publish a
partial generation.

Search showed amplification rather than a Python postprocessing bottleneck. A
successful live vault query took 1.237 seconds: reranking 1.049 seconds, query
embedding 0.154 seconds, Qdrant 0.023 seconds, and status 0.031 seconds. Ordinary
code search with default hard-domain policy enters a 10x candidate window in
`search/_searcher.py:573-578` even though domain filters are pushed into Qdrant,
and `_store_search.py:231-261` multiplies each dense and sparse prefetch by four
again. For `top_k=10`, that is a 100-result fusion with two 400-point prefetches
before reranking. Only real path globs require the initial 10x window; pushed
domain filters can start at the normal rerank window and use the existing
backfill loop if legacy rows are depleted.

One smaller search regression is safe to correct in this pass:
`postprocess_seconds` includes `rerank_seconds`, causing telemetry to
double-count the observed dominant phase. Postprocessing must contain only
mapping and post-rerank shaping. Concurrent identical cache misses are also
visible, but a simple second cache lookup after GPU admission would put cache
work inside the forward-pass-only GPU gate. Correct coalescing therefore needs
per-key single-flight outside the gate and is deferred with the other GPU
scheduling changes.

The public search model also exposes `rerank_text` in `server/_models.py:75` and
serializes it in `server/_routes.py:446-454`, despite the internal model contract
declaring the full scoring content private and excluded. Live responses included
whole ADR bodies. Removing it from the public response bounds network, JSON, and
agent-context costs; the public mirror should retain the smaller `status` and
`related` fields instead. No backward-compatibility shim is warranted because
the field contradicts its declared contract.

Several important findings are intentionally deferred. The global GPU gate
wraps CrossEncoder tokenization, sorting, device movement, forward execution,
and result conversion because the project calls the library's monolithic
`predict`; reranking represented about 85 percent of the measured request. A
forward-only adapter needs real-model score-equivalence and concurrency
benchmarks. Search routes also perform three Qdrant counts per success (one
source preflight plus both counts from `get_status`), and widening repeats full
hybrid work. Changing those response/status contracts needs separate design and
instrumentation. Fair search-versus-index GPU scheduling is likewise already a
known option in the service-concurrency research and should not be improvised
during this regression pass.

## Implementation boundary

This pass may implement the singleton fallback guard, single daemon log sink,
bounded ignore and binary probes, linear line accounting, watcher extension
parity, bounded batch futures and failure propagation, normal initial search
window for pushed-down domain filters, exclusive phase timing, and private
scoring-content removal. Tests must exercise real files, real locks and
discovery records, real subprocess routing, production parsing and filtering,
and actual logging file descriptors. Broader GPU scheduling, cache
single-flight, and status-response redesign remain follow-up architecture work.

## Implemented outcome

The service path now refuses in-process indexing whenever a live machine owner
exists, including warming discovery, and multi-source delegation reports a
structured partial outcome instead of silently continuing locally. Daemon
logging has one rotating root sink, keeps raw stdout and stderr capture, and
suppresses routine HTTP client INFO noise. The public search response no longer
contains private reranker input.

Index discovery now prunes fixed exclusions before walking nested ignore files,
while fixed exclusions remain authoritative over root negations. Binary probes
read at most 8 KiB. Fallback and AST line accounting use monotonic cursors, the
watcher imports the indexing extension source of truth, and batch preprocessing
keeps only one worker window in flight while propagating abort, publication,
storage, and GPU failures.

Post-change measurements on the same workspace reduced ignore resolution from
7.58 seconds to about 0.37 seconds, reduced an 8 MiB binary probe from about
8.01 MiB peak allocation to 0.016 MiB, reduced 400k-character fallback line
accounting from 0.171 seconds to about 0.036 seconds, and reduced the
4-million-character AST leaf case from 7.042 seconds to about 0.026 seconds.
Search candidate widening now begins at the normal rerank window for pushed
domain filters, retains the full rerank window when legacy domain-less rows
require backfill, and widens initially only for real path globs.

The initial review conclusion above was superseded by the mandatory completion
audit on 2026-07-22. Three independent reviewers found open high-severity
lifecycle and indexing defects, and the installed daemon plus a competing GPU
index process made live end-to-end search evidence invalid for this worktree.

## Revalidation update — 2026-07-22

The resident watcher failed code and vault indexing with CUDA OOM and retried on
success-cooldown idle ticks, filling the retained 256-record job history. That
ring is not a retry limit and can evict a running job. The accepted
large-index-resilience plan still has unchecked production steps for bounded
incremental streaming, durable progress, memory enforcement, persistent watcher
circuits, and real-Qdrant/CUDA failure verification. Code incrementals also
delete old modified-file chunks before replacement embedding and upsert, leaving
an avoidable search gap on failure.

The current production path never calls the newer `JobManager`. Watcher,
routes, restoration, and `/jobs` all use the legacy deque, whose direct test
explicitly proves that running records are evicted after 256 later starts and
whose finish operation silently ignores an evicted ID. Every legacy start,
step transition, and finish also serializes, flushes, `fsync`s, and replaces
the complete shared persistence envelope while holding the operator lock. A
real CPU exercise measured roughly 2.25 seconds for 306 starts and 7.2 seconds
for 800 concurrent start/finish pairs, with about 1,969 log lines. Combined with
the one-second watcher failure loop, the same outage amplifies GPU attempts,
durability traffic, lock contention, and managed logs.

Lifecycle inspection found that abruptly terminated integration tests can
orphan the production-detached service and Qdrant, isolated test roots bypass a
physical machine-wide GPU lease, and Windows Qdrant startup fails open when
kill-on-close Job Object containment cannot be established. The current CLI and
installed daemon also lack an explicit API/build handshake, so an incompatible
daemon is discovered and invoked before response validation fails.

Search retains medium-severity amplification: the GPU gate surrounds library
tokenization and CPU conversion as well as forward execution, depleted filters
can issue hybrid queries at 40, 80, 160, 320, and 500 candidates with four-times
prefetch, successful requests perform three count calls, concurrent cold
identical queries duplicate encoding, and limiter wait is absent from queue-wait
telemetry. Stored concurrency baselines are not post-change evidence and have no
acceptance threshold.

This revalidation fixed three contained regressions. Timeout resolution cannot
disable the mandated local deadline with zero, negative, NaN, or infinity.
Human rendering uses the bounded public snippet and performs no per-result file
read or private-field fallback. Chunk-result publication separates worker
failure from coordinator accounting, and its clean CPU benchmark measured 7.38
seconds serial versus 4.47 seconds parallel for 20,000 chunks, a 1.65-times
speedup. Batch scheduling now refills each released worker slot immediately,
preserving the worker-sized memory bound while overlapping CPU preprocessing
with sequential GPU/storage publication; the real subprocess bounded-window
test passes.

Static validation passes for those changes. The settled worktree now passes 93
focused search/render/deadline tests, 24 CPU-only preprocess/batch tests, and 22
search-noise/candidate/phase-accounting tests, plus 24 managed-log tests and
seven legacy jobs-registry tests. A broad non-GPU unit run passed 1,604 tests
and exposed one stale sparse OOM model double: the real installed SparseEncoder
accepts the production arguments, but the double accepts only `batch_size`.
Project rules prohibit extending that fake as a compatibility shortcut; real
allocator-pressure recovery remains part of isolated GPU acceptance.
Current-worktree service measurements remain blocked by the incompatible
installed daemon and competing GPU workload. The audit therefore remains
revision-required rather than accepted.
