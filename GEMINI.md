<vaultspec type="config">
## Vaultspec Rules

You MUST respect these rules at all times:

---
name: automated-destruction-requires-time-confirmed-danglingness
trigger: always_on
---

# Automated destruction requires time-confirmed danglingness

## Rule

Automated deletion of indexed data requires classification AND a persisted
continuous grace window - a single-scan "root path does not exist"
observation is never sufficient. Data-bearing namespaces additionally
require a recoverable archive to have succeeded before destruction, and
`unknown`/`unverifiable` namespaces are never auto-touched.

## Why

A valid root can transiently not-exist: an unplugged drive, an offline
share, a directory mid-rename, a worktree being re-created. The manual
prune has a human as the confirmation; the scheduled auto-prune
(`2026-07-14-storage-autoprune-safety-adr`) replaces that human with time -
`first_seen_orphaned` persists in the storage manifest across daemon
restarts, any live or unverifiable observation resets it to zero, so
protection can only ever be extended by races, never shortened. The
empty/data tier split matches the measured waste profile: the 167.9GB
reclaimed on 2026-07-13 was entirely zero-point namespaces.

## How

- **Good:** `evaluate_reclaim` in `src/vaultspec_rag/storage_ops.py` -
  orphaned-only input, per-tier grace windows (24h empty / 168h data),
  riskless-empty-first under a per-cycle cap; `archive_prefix` raises on
  any snapshot failure so `delete_prefix` is never reached for unarchived
  data; the empty tier re-counts points immediately before the drop.
- **Bad:** dropping a namespace because one survey said its root was
  missing; destroying a point-bearing namespace after a failed archive;
  resetting grace clocks on daemon restart; auto-deleting anything the
  manifest cannot attribute.

---
name: broker-facing-cli-outcomes-are-structured-and-idempotent
trigger: always_on
---

# Broker-facing CLI outcomes are structured and idempotent

## Rule

A lifecycle CLI verb a broker drives (`server start`, `server stop`) must, in
`--json` mode, emit exactly ONE structured envelope on every exit path -
success and each failure - and treat an already-satisfied request as a success
(exit 0 with an `already_*` status), never a non-zero fault a broker would
misread as a gateway error. An outcome that leaves the requested state
unachieved (a stop that leaves the service running) is a failure and exits
non-zero in BOTH human and json modes.

## Why

The `2026-06-27-rag-broker-affordances-adr` shipped `server start --json`
after a supervising broker misread "already running" as an opaque 502; the
`2026-07-13-control-plane-affordances-adr` completed the sibling
`server stop --json`. The candidate held through both execution cycles: a
broker can speculatively start (attach on `already_running`) and stop
(no-op on `already_stopped`), and the one genuine stop failure
(`identity_unconfirmed`, service left running) is a visible exit 1 instead
of a silent success.

## How

- **Good:** `_start_success`/`_fail_start` and `_stop_success`/`_fail_stop`
  in `src/vaultspec_rag/cli/_service_lifecycle.py` - every terminal branch
  converges on exactly one helper; `{ok, command, data:{status,...}}` on
  success, `{ok:false, command, error, message, data}` on failure.
- **Good:** `server stop` with nothing to stop emits `already_stopped`
  (exit 0); terminating outcomes carry initiator attribution fields.
- **Bad:** printing human text on a `--json` path, emitting zero or two
  envelopes on any exit, or exiting 0 from a stop that skipped a live
  unconfirmed process.

---
name: gpu-consumer-single-thread
trigger: always_on
---

# Single dedicated GPU consumer thread for indexing

Promoted from the `2026-06-02-index-gpu-pipeline` ADR codification candidate and its code
review.

## Rule

GPU encoding in the indexing pipeline runs on exactly one dedicated consumer thread that
owns `gpu_lock`. Never add a second GPU consumer thread or use CUDA streams to parallelise
compute on the single device, and never run the encode inline on the thread that drains the
process pool. Every wait involved in shutting that consumer down (the end-of-stream sentinel
put and the join) must be liveness-guarded and time-bounded so a wedged CUDA/Qdrant call
aborts the run rather than hanging it under the indexer's writer lock.

## Why

On a single GPU there is no compute/compute overlap to exploit: two compute-bound kernels
serialise on the SMs regardless of CUDA streams (research A3). The only real parallelism is
CPU-produce versus GPU-consume, captured by a process-pool producer feeding one consumer
thread that the GIL-releasing async-CUDA path keeps busy (A1/A2) — the `DataLoader` pattern.
Running the encode inline on the pool-draining thread idles the GPU during pool bookkeeping.
A second consumer thread only serialises on GIL launch overhead and the SMs. And because the
codebase index runs under `self._writer_lock`, any unbounded wait on the consumer escalates a
single GPU/Qdrant stall into a permanently wedged indexer (review C1/H1/H2).

## How

- **Good:** one `threading.Thread` consumer drains a bounded `queue.Queue`, holds `gpu_lock`
  across `encode_and_upsert_code_slice`, and is the only code that touches CUDA; the producer
  refills the queue while the GPU runs.
- **Good:** shutdown sends the `None` sentinel only while `consumer.is_alive()`, with a
  timed `put`, and `join(timeout=...)`; if the thread does not terminate within the bound,
  log and raise rather than block forever.
- **Bad:** calling `encode` inline in the `wait()`/collect/submit loop (idles the GPU during
  bookkeeping).
- **Bad:** a second GPU consumer thread, or separate CUDA streams for dense and sparse, to
  "parallelise" GPU work — they serialise on one saturated device.
- **Bad:** an unguarded blocking `queue.put(sentinel)` or unbounded `join()` on shutdown —
  a dead-without-draining or wedged consumer then hangs the producer and holds the writer
  lock indefinitely.

## Source

ADR `2026-06-02-index-gpu-pipeline-adr` (codification candidate `gpu-consumer-single-thread`)
and its code review (findings C1/H1/H2). Research `2026-06-02-index-gpu-pipeline-research`
(A1 to A3). Related rule `index-workers-stay-cpu-only`.

---
name: gpu-lock-wraps-forward-passes-only
trigger: always_on
---

# GPU lock wraps forward passes only

## Rule

Hold the global GPU lock only across model forward calls (encode, predict);
tokenization-adjacent preparation, pair assembly, tensor post-processing, score
conversion, and any storage I/O must run outside it.

## Why

The `2026-06-12-service-concurrency-adr` and its research measured that over half
of warm search latency at concurrency 4 was queueing on the GPU lock while it was
held across non-GPU work, and that an index slice's sparse-tensor conversion ran
its per-row device syncs inside the lock. Every millisecond the lock is held
beyond the forward pass serializes all roots of the multi-tenant service, because
there is exactly one GPU lock per process.

## How

- Good: build CrossEncoder pairs and apply the character cap before entering the
  GPU section; call `predict` inside it; convert raw scores to floats after
  release (`src/vaultspec_rag/search/_searcher.py`).
- Good: check the query-embedding cache before acquiring the lock so repeat
  queries skip it entirely.
- Bad: wrapping result mapping, sparse-tensor densification, or a Qdrant upsert
  in the same `with gpu_lock:` block as the encode that produced the vectors.

---
name: index-workers-stay-cpu-only
trigger: always_on
---

# Index workers stay CPU-only

Promoted from the `2026-06-02-index-perf-hardening` code review (finding L2) and the
sibling ADR's codification candidate.

## Rule

Codebase-index worker processes must do CPU-only work and never initialise CUDA. The
embedding GPU is touched exclusively by the single in-process consumer. The chunk worker
pool must be created with the `spawn` start method, and **every module reachable from the
worker's import chain must keep its `torch` import lazy** (inside functions, never at
module scope).

## Why

`vaultspec-rag`'s codebase indexer parallelises tree-sitter chunking across a
`ProcessPoolExecutor` because tree-sitter holds the GIL for both parse and traverse, so
threads give no speedup (`2026-06-02-index-perf-hardening` research O1). A spawn worker
re-imports `vaultspec_rag.indexer._chunk_worker`, which transitively runs
`vaultspec_rag/__init__.py`. That works today only because `embeddings.py` imports `torch`
lazily, so importing the worker never loads CUDA. If any module on that chain moved
`import torch` to module scope, every worker would initialise CUDA at startup and
reintroduce the `Cannot re-initialize CUDA in forked subprocess` crash class (and, even
under `spawn`, needless multi-second startup per worker). The single GPU consumer pattern
also preserves the existing `gpu_lock` serialisation with search.

## How

- **Good:** the worker module (`_chunk_worker.py`) imports only `_ast_chunker`,
  `_chunking`, and `store.CodeChunk`; the pool is built via
  `multiprocessing.get_context("spawn")`; dense/sparse encoding happens only in the
  consumer that owns the `EmbeddingModel`.
- **Good:** a fresh-interpreter test asserts `import vaultspec_rag.indexer._chunk_worker`
  leaves `torch` out of `sys.modules` (regression guard for the lazy-import invariant).
- **Bad:** adding `import torch` (or `from torch import ...`) at module scope in
  `embeddings.py`, `api.py`, `search.py`, `store.py`, or anything else the worker import
  chain reaches. Keep torch behind function-local imports.
- **Bad:** constructing an `EmbeddingModel`, calling `torch.cuda.*`, or opening the vector
  store inside a worker. Workers receive plain paths and return plain dataclasses.

## Source

Audit/review `2026-06-02-index-perf-hardening` finding L2. Sibling decision ADR
`2026-06-02-index-perf-hardening-adr` (codification candidate `index-workers-stay-cpu-only`).

---
name: managed-singleton-paths-isolate-storage-dir-in-tests
trigger: always_on
---

# Managed-singleton paths isolate the storage dir in tests

## Rule

Any test or caller that exercises `write_qdrant_identity` or
`acquire_machine_lock` must set `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to a temp path
before invoking it, because the machine-global identity sidecar and the
machine-scoped service lock both derive their location from that env knob, not
from `VAULTSPEC_RAG_STATUS_DIR`.

## Why

The `2026-06-24-service-hardware-singleton-audit` recorded a leaked identity
sidecar written to the real machine-global managed dir: an early test iteration
isolated state with `config_override`, which does not reach
`qdrant_storage_dir`, so the writer targeted the operator's real
`~/.vaultspec-rag/qdrant-server/` instead of a temp dir. The machine lock shares
that parent (`machine_lock_path()` is `storage.parent / "service.lock"`), so an
unisolated test would also acquire the real machine singleton and collide with a
live service or a sibling test. The constraint held across one full execution
cycle: the leak, the `_service_env` fix that sets the storage dir, and the
`W04.P09.S29` follow-up that mirrors the qdrant binary under the isolated dir and
keeps the storage dir relocated.

## How

- **Good:** a fixture sets `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to
  `tmp_path / "qdrant-server" / "storage"`, calls `reset_config()`, then runs the
  identity write or lock acquire; teardown releases the lock and restores the
  env. The integration `_service_env` helper does exactly this, and additionally
  relocates the qdrant port off the shared default so a server-mode test daemon
  never binds the real machine's port.
- **Bad:** isolating only `VAULTSPEC_RAG_STATUS_DIR` (or only `config_override`)
  and then calling `write_qdrant_identity` / `acquire_machine_lock`; the
  machine-global paths still resolve to the real managed dir, leaking a sidecar
  or contending for the real machine lock.

---
name: operator-views-are-bounded
trigger: always_on
---

# Operator Views Are Bounded

## Rule

Always make operator list and tail commands bounded, filterable, and biased toward the
current actionable state rather than unbounded history.

## Why

The `2026-06-11-cli-service-operability-hardening-code-review-audit` and
`2026-06-11-service-jobs-operability-adr` showed that full history tables and unfiltered
log tails hide running or relevant work behind stale noise. Operators need answers to
what is running, failed, stale, or related to a specific job without dumping the whole
service history.

## How

- Good: default `server jobs` to a bounded result set, expose `--state` (e.g.
  `active`/`failed`), `--failed`, `--job-id`, and `--since`, and make
  `server logs --job-id` search a bounded maximum log window before returning the
  requested filtered tail.
- Bad: render every recorded job by default or filter only the last N unfiltered log
  lines so unrelated recent noise can hide the requested job.

---
name: pinned-binaries-verify-before-execute
trigger: always_on
---

# Pinned binaries verify before execute

## Rule

Any native binary the project provisions must be SHA256-verified against a committed
pin before extraction, and re-verified before execution; never extract or run an
unverified or operator-untrusted artifact.

## Why

The `2026-06-12-qdrant-server-provisioning-adr` introduced first-use provisioning of
the Qdrant server binary, and its code review made download-then-execute the load-
bearing security boundary: a tampered archive or a corrupted managed binary must be
refused before it can run. The pinned digests live as reviewed code constants (not
trusted live from the release metadata), the download is HTTPS host-pinned with the
scheme re-checked across redirects, and extraction discards archive-embedded paths
so a malicious member cannot escape the destination.

## How

- Good: download host-pinned over HTTPS, hash the archive and compare to the
  committed constant before extracting, flatten the member by basename into the
  managed dir, then re-hash the extracted binary against its manifest digest
  immediately before spawning it.
- Good: an operator-supplied binary (air-gapped escape hatch) bypasses the download
  but is still resolved through the same supervised path; a checksum mismatch is a
  hard failure that deletes the partial artifact.
- Bad: extracting an archive before verifying its digest, trusting the digest
  embedded in live release metadata instead of a committed pin, or calling
  `extractall` (which honours archive-embedded paths and enables traversal).

---
name: rerankers-score-real-content
trigger: always_on
---

# Rerankers score real content

## Rule

Reranking inputs must be the token-bounded full candidate content, never a
fixed-character snippet or any other display proxy.

## Why

The `2026-06-12-service-concurrency-research` (finding F11) caught the
CrossEncoder scoring 200-character display snippets while the full content sat
in memory - the model's semantic capacity was discarded and ranking was biased
toward candidates whose opening characters echoed the query. The
`2026-06-12-service-concurrency-adr` made content reranking a decision: the
reranker's own tokenizer enforces the token bound, and the display snippet is a
rendering concern only.

## How

- Good: carry the candidate's full content on the result object
  (`rerank_text`), cap it at a generous multiple of the token bound to spare
  tokenizer work, and let the CrossEncoder's `max_length` do the exact
  truncation (`src/vaultspec_rag/search/_searcher.py`).
- Bad: passing `result.snippet`, a title, or any fixed-width prefix as the
  reranker's document side - it will pass every test while silently degrading
  ranking quality.

---
name: service-domain-owns-operability
trigger: always_on
---

# Service Domain Owns Operability

## Rule

Always implement service health, status, jobs, logs, and search diagnostics as
service-domain behavior first; CLI and MCP entry points must adapt to that shared
behavior rather than own or duplicate it.

## Why

The `2026-06-11-cli-service-operability-hardening-code-review-audit` and the
`2026-06-11-service-status-convergence-adr` showed that earlier MCP deconflation did
not fully remove MCP-shaped business logic from CLI and service operations. When MCP,
CLI, and localhost routes drift independently, operators see conflicting names, JSON
contracts, and remediation commands.

## How

- Good: add a `/jobs` filter in the server route, pass the same query parameters through
  `server jobs` and MCP `get_jobs`, and keep the JSON envelope stable across adapters.
- Bad: add a CLI-only `server jobs --failed` path that computes different phases from
  the server or an MCP-only admin helper that the CLI must call to understand service
  state.

---
name: storage-locks-are-backend-aware
trigger: always_on
---

# Storage locks are backend-aware

## Rule

Store-layer locking must distinguish local mode (one reentrant lock per
collection, plus a lifecycle lock for open/close and collection create/drop)
from server mode (no point-operation locks at all); never reintroduce a single
store-wide mutex across collections.

## Why

The `2026-06-12-service-concurrency-adr` and the saturation baseline in its
research showed one store-wide lock dragging 4-second vault searches to a
95-second p50 purely because they shared a mutex with code-collection scans -
the collections are independent inside the local engine, and a remote Qdrant
server handles its own concurrency, so client-side locking there only caps
throughput. Lock ordering is part of the contract: the lifecycle lock is always
acquired before any collection lock, and collection locks stay reentrant
because scan helpers re-enter them.

## How

- Good: `_point_lock(collection)` returning the collection's own RLock in local
  mode and a null context in server mode; `close()` taking the lifecycle lock
  then every collection lock in fixed order
  (`src/vaultspec_rag/store.py`).
- Bad: adding a new store method that takes one global client lock around a
  point operation, or acquiring the lifecycle lock while already holding a
  collection lock.

---
name: storage-maintenance-is-lifecycle-inert
trigger: always_on
---

# Storage maintenance is lifecycle-inert

## Rule

No storage-maintenance code path - survey, prune, delete, or the scheduled
auto-prune - may reach a service stop, terminate, or machine-singleton
reclaim helper. Maintenance is read/drop only, and the import graph is
regression-tested: nothing reachable from the maintenance modules may import
`vaultspec_rag.cli`.

## Why

The `2026-07-13` prune incident trace showed how a storage command that
shares a process and config surface with the lifecycle verbs pattern-matches
to "the prune killed the service" the moment anything terminates a daemon in
the same window - and a maintenance actor that genuinely could reach a
terminate flow would turn a routine reclamation into an outage. The
`2026-07-14-storage-autoprune-safety-adr` made inertness a hard invariant
when reclamation moved inside the daemon on a schedule.

## How

- **Good:** `TestStorageMaintenanceIsLifecycleInert` in
  `src/vaultspec_rag/tests/test_adr_regression.py` - a fresh-interpreter
  import of `storage_manifest`, `storage_ops`, and `server._lifecycle`
  asserts no `vaultspec_rag.cli.*` module loads, and a source scan asserts
  none of them names `_terminate_and_confirm`, `_reclaim_machine_singleton`,
  `_stop_service_on_port`, or `_terminate_pid`.
- **Bad:** importing a CLI lifecycle helper (even function-locally) from
  `storage_ops.py` or the maintenance tick, or adding a "restart the
  service if degraded" branch to a maintenance cycle.

---
name: torch-loads-through-centralized-gpu-gate
trigger: always_on
---

# Torch loads through one centralized GPU gate

## Rule

Every local-mode path that needs torch for compute must obtain it through the single
centralized loader `vaultspec_rag._gpu.load_torch()` - which imports torch, asserts a
CUDA device, and raises hard on a CPU-only build - never a naked `import torch`; service
call paths (the `mcp/` server, the `serviceclient/` client, and the CLI service-control
commands) must stay torch-import-free; and if the installer provisions torch at all it
must be the cu130 GPU build, never a CPU wheel accepted silently.

## Why

vaultspec-rag is GPU-only and never runs inference on CPU. The `2026-06-30` torch
hardening found the hard CUDA gate duplicated across four sites (embeddings, the service
reranker, the searcher reranker, and CLI warmup), each re-implementing
`if not torch.cuda.is_available(): raise` - three with a copy-pasted message - so the
"who, when, and how torch loads" was uncontrolled and a CPU-only build could only be
caught wherever someone remembered to check. The same work found the installer reporting
`PyTorch configuration: already configured` from pyproject text while the active
interpreter carried a CPU-only torch wheel (a bare `uv tool` / `pip install` resolves
torch from PyPI because the cu130 pin is workspace-scoped and absent from published wheel
metadata, and `--torch-backend` is `uv pip`-only). Centralizing the load and probing the
real wheel is what makes the GPU-only contract enforceable and legible rather than
silently violated.

## How

- **Good:** a compute site calls `torch = load_torch()` and uses the returned module;
  `load_torch()` raises `RuntimeError` (CPU-only or no GPU) or `ImportError` (absent) so
  the failure is hard and loud, with one canonical message.
- **Good:** read-only probes that must tolerate a CPU-only or torch-absent host (the
  `/health` and `/metrics` reporters, readiness diagnosis, the memory probe) keep their
  own guarded function-local import and report `cuda=False` rather than raise - they are
  the deliberate exception and do not call `load_torch()`.
- **Good:** the installer probes the active interpreter's wheel
  (`warn_if_active_torch_not_gpu`) and, when torch was meant to be provisioned, warns
  loudly on a CPU-only or absent wheel with topology-aware remediation; an explicit
  torch opt-out is respected silently.
- **Bad:** a naked module-scope `import torch`, or a fresh inline
  `if not torch.cuda.is_available(): raise` on a compute path instead of routing through
  `load_torch()`.
- **Bad:** importing torch (or `sentence_transformers`) anywhere reachable from a service
  call path, or reporting install success over a CPU-only torch wheel.

## Source

The `2026-06-30` torch import-discipline and install-provisioning audits and the
GPU-only mandate they served. Sibling rules `index-workers-stay-cpu-only` (torch imports
stay function-local so spawn workers never initialise CUDA) and
`gpu-consumer-single-thread`.

---
name: vaultspec-cli.builtin
trigger: always_on
---

# Vaultspec Core CLI

This project is vaultspec-managed. See `vaultspec.builtin.md` for framework rules and
workflow concepts.

## Mandate

Use `vaultspec-core` to create, read, audit, and repair `.vault/` documents. Never
hand-write frontmatter, filenames, plan structure, or new `.vault/` documents; editing
the body prose of a document scaffolded by `vaultspec-core vault add` is permitted (see
"Allowed manual edits" below). `vaultspec-core` enforces templates, tag taxonomy,
wiki-link resolution, schema dependencies, and provider sync; bypassing it produces
drift that `vaultspec-core vault check` and `vaultspec-core spec doctor` will flag.

## Orientation

Before starting work in a vaultspec-managed project you have no session context for, run
`vaultspec-core status` and read the in-flight plans it names. Each in-flight plan shows
a one-line overview: tier, completed waves and phases, step completion, and the next
open step. The targeted form `vaultspec-core status <plan-or-feature>` traces a plan to
its steps, execution records, and grounding documents. Orientation is descriptive and
read-only: it is the zeroth move, not a pipeline phase, and produces no artifact.

## Commands

### Orient

- `vaultspec-core status [TARGET]` - orient in an unknown or resumed project
- `vaultspec-core vault feature list` - list feature tags in the vault
- `vaultspec-core vault list [DOC_TYPE] [--feature <tag>]` - list or filter vault
  documents

### Author the pipeline

- `vaultspec-core vault add <type> --feature <tag>` - create a `.vault/` document

### Verify & audit

- `vaultspec-core vault check all [--fix]` - audit drift, broken links, or missing
  references
- `vaultspec-core vault check features --feature <tag>` - confirm required documents
  exist for a feature
- `vaultspec-core vault sanitize annotations [--feature <tag>] [--dry-run]` - strip
  generated template annotations

### Advanced vault inspection

- `vaultspec-core vault stats [--invalid] [--orphaned]` - show statistics, invalid, or
  orphan documents
- `vaultspec-core vault graph [--feature <tag>]` - visualize the vault dependency graph

### Workspace & maintenance

- `vaultspec-core spec <resource> list` - list registered rules, skills, agents, hooks,
  or MCPs
- `vaultspec-core spec mcps status --json` - verify MCP config health
- `vaultspec-core spec system show` - inspect the assembled system prompt
- `vaultspec-core sync` - propagate edits under `.vaultspec/...`
- `vaultspec-core spec doctor` - diagnose overall workspace health
- `vaultspec-core migrations status` / `vaultspec-core migrations run` - inspect or run
  pending schema migrations
- `vaultspec-core vault feature archive <tag>` - archive a feature so it no longer
  exists in the active project
- `vaultspec-core vault feature rename <old> <new>` - rename a feature tag across every
  binding surface (document filenames, the exec folder, the `#feature` tag, `related:`
  wiki-links, and the regenerated feature index); rolls back on failure during apply,
  and `--force` merges the source into an existing target feature
- `vaultspec-core vault rule promote --from <audit-stem> --as <rule-name>` - promote an
  audit finding to a project rule

`<resource>` is one of `rules`, `skills`, `agents`, `hooks`, or `mcps` for `list`; one
of `rules`, `skills`, `agents`, `hooks`, `mcps`, or `system` for resource-scoped
maintenance sync. Use top-level `vaultspec-core sync` as the authoritative complete
propagation command after source-side changes.

## Runtime

- Run `vaultspec-core <cmd>` when the binary is on `PATH`. In uv-managed environments,
  run `uv run --no-sync vaultspec-core <cmd>`.
- Use `--target DIR` (or `-t`) to operate on a directory other than the current one.
- Use `--dry-run` to preview changes.
- Use `--json` for machine-readable output.
- Read sync-shaped results (`vaultspec-core install`, `vaultspec-core sync`,
  `vaultspec-core spec <resource> sync`, `vaultspec-core migrations run`) with one
  vocabulary: `created`, `updated`, `unchanged`, `removed`, `restored`, `skipped`,
  `failed`. `unchanged` is a successful no-op, not a failure; `skipped` always carries a
  reason worth reading; only `failed` stops the pipeline. With `--json`, the top-level
  `status` is the run's aggregate outcome (`mixed` when items disagree).
- Use `--force` when a mutating command must overwrite existing output.
- Run `vaultspec-core <cmd> --help` for the full flag, subcommand, and exit-code
  reference.

## Allowed manual edits

Permitted:

- Edit body prose of a `.vault/` document scaffolded by `vaultspec-core vault add`.
- Edit source files under `.vaultspec/rules/`, `.vaultspec/skills/`,
  `.vaultspec/agents/`, `.vaultspec/hooks/`, or `.vaultspec/mcps/`, then run
  `vaultspec-core sync`.

Forbidden:

- Hand-writing frontmatter, filenames, or new `.vault/` documents.
- Editing files inside generated provider directories; `vaultspec-core sync` regenerates
  them.

## References

- `.vaultspec/reference/cli.md` - locally-resident machine-facing CLI reference: command
  inventory, options, argument enumerations, exit codes, and environment variables. Read
  this first; no network round-trip needed.

---
name: vaultspec-discovery.builtin
trigger: always_on
---

# Codebase and intent discovery

Begin every pipeline phase - Research, ADR, Plan, Execute - by grounding in what the
project already decided and built. The project's own benchmarking is unambiguous: a
semantic-search-led hybrid sweep finds a feature fastest and at the lowest context cost
\- roughly 1.3-2x cheaper than broad keyword search on a large tree - and recalls
governing decisions with near-zero noise. Lead with it. The validated sequence is locate
by meaning, read the epicenter whole, confirm with grep:

1. **Locate by meaning.** For code, lead with
   `vaultspec-rag search "<concept and domain nouns>" --type code` (narrow with
   `--language`/`--path`); it reaches the right file in about one call where broad
   globbing floods context. For decisions and intent,
   `vaultspec-rag search "<intent>" --type vault --doc-type adr` - the directed ADR
   filter, sharper than catch-all `--type vault`. `vaultspec-core status [target]`,
   `vaultspec-core vault list`, and `vaultspec-core vault graph` are first-class for
   orientation, in-flight plan state, and project health - reach for them to get your
   bearings on intent. For a small, well-named module, list the directory.
1. **Read** the epicenter file - or, when extending a feature, the nearest existing
   analogue - in full. This whole-file read is the breakthrough in nearly every run.
1. **Confirm** exact symbols and insertion points with a targeted grep, which is sharper
   than semantic search at exact-symbol lookup.
1. For decision discovery, round out recall by listing `.vault/adr/` and filtering by
   feature - semantic search alone can miss lower-ranked or opaquely-named records.

Do not lead with broad `Glob`/grep sweeps; their context cost scales badly on large
codebases, and grep earns its place at the confirmation step. Where `vaultspec-rag` is
not installed, the `vaultspec-core` discovery verbs and grep carry the same sequence.

---
name: vaultspec-rag.builtin
trigger: always_on
---

# vaultspec-rag — semantic search for code and decisions

Discover by MEANING when you do not know the exact name, instead of grepping keywords or
guessing identifiers. vaultspec-rag does two jobs: find the CODE, and find the DECISIONS -
the ADRs (architecture decision records) that govern it.

Server mode is the default backend. If a search reports the service is down, start it with
`uvx vaultspec-rag server start` (small or offline projects opt into the on-disk local
backend with `--local-only`). The running service auto-reindexes on file changes.
DO NOT manually reindex during normal work.

## Discover code by meaning

`--type code` searches source by meaning. Phrase the query as a short behaviour plus the
concrete domain nouns the target code would use: the behaviour drives semantic matching, the
nouns drive exact matching, so a bare keyword or pure prose finds less than both together.

```
uvx vaultspec-rag search "retry backoff around failed webhook delivery" --type code
```

## Discover architecture decisions

When you need the WHY - the rationale, constraints, or decision behind code - search the
vault's ADRs, not the source. `--type vault --doc-type adr` returns the governing records.

```
uvx vaultspec-rag search "decision on gpu lock scope around the forward pass" --type vault --doc-type adr
```

`--doc-type` also accepts `audit`, `plan`, `reference`, `research`, and `exec` (comma-separate
to union several).

## Cut noise with filters

Semantic search competes production code against its own noise - overlapping tests, parallel
locale files, generated and vendored trees, worktree clones. Code search is production-biased
by default: it hides duplicate/derivative domains (`generated`, `worktree`) and demotes
`tests`, `docs`, `locale`, and `vendored` beneath production. When noise still crowds a page,
narrow by DOMAIN rather than raising `--max-results`. The domains are `prod`, `tests`, `docs`,
`locale`, `generated`, `vendored`, `worktree`.

Steer with inline query tokens (comma-separated, repeatable):

```
uvx vaultspec-rag search "fixture setup helpers exclude:tests" --type code
uvx vaultspec-rag search "auth token validation only:prod" --type code
uvx vaultspec-rag search "translation table lookup include:locale" --type code
```

`exclude:` hides a domain, `only:` keeps just the named domains, and `include:` re-admits a
domain the default profile hides or demotes. Compose with path and category filters:

```
uvx vaultspec-rag search "request handler" --type code --include-path "src/**" --exclude-path "**/legacy/**"
uvx vaultspec-rag search "encode batch" --type code --prefer production
```

The full option set is `uvx vaultspec-rag search --help`. The same search is available through
MCP as the `search_codebase` and `search_vault` tools.

---
name: vaultspec.builtin
trigger: always_on
---

# Spec Skills

This project follows a spec driven development framework and mandates a vaultspec
pipeline of: research -> decision (ADR) -> plan -> verify (+ audit either as closeout or
pipeline start).

The workflow persists the following documents, bound by a single feature tag:

- `.vault/research/yyyy-mm-dd-<feature>-research.md`: The `<Research>` findings.

- `.vault/reference/yyyy-mm-dd-<feature>-reference.md`: A project, code, or research
  grounding `<Reference>`, useful for grounding implementation details prior to ADR
  authoring.

- `.vault/adr/yyyy-mm-dd-<feature>-adr.md`: Research-derived `<ADR>`.

- `.vault/plan/yyyy-mm-dd-<feature>-plan.md`: The `<Plan>` to execute, authored and
  managed by the vaultspec-core CLI (`vaultspec-core vault plan`).

- `.vault/exec/yyyy-mm-dd-<feature>/.../<step>.md`: The individual `<Step Record>`.

- `.vault/exec/yyyy-mm-dd-<feature>/...-summary.md`: The `<Phase Summary>`.

- `.vault/audit/yyyy-mm-dd-<feature>-audit.md`: The `<Audit>` report. A feature with
  multiple audits disambiguates each with an optional narrative infix:
  `yyyy-mm-dd-<feature>-<topic>-audit.md`.

- `.vault/index/<feature>.index.md`: The auto-generated `<Feature Index>` linking every
  document for a feature. Managed by `vaultspec-core vault feature index`; do not author
  by hand.

Use the following pipeline skills:

- `vaultspec-research`
- `vaultspec-code-research`
- `vaultspec-adr`
- `vaultspec-write`
- `vaultspec-execute`
- `vaultspec-code-review`

The following helper skills are available:

- `vaultspec-curate`
- `vaultspec-documentation`
- `vaultspec-team`
- `vaultspec-projectmanager`

## Documentation Hierarchy

The documentation trail follows a strict dependency graph. Artifacts lower in the
hierarchy should reference those above them.

- **Brainstorm** / **Research** / **Reference** (`.vault/research/`,
  `.vault/reference/`)

- **Audits** (`.vault/audit/yyyy-mm-dd-{feature}-audit.md`, optionally
  `.vault/audit/yyyy-mm-dd-{feature}-{topic}-audit.md`)

  - *Depends on:* the artifacts under review (plans, execution records, code)
  - *References:* the artifacts under review

- **Architecture Decision Records (ADR)** (`.vault/adr/`)

  - *Depends on:* brainstorm, research, audits

- **Implementation Plans** (`.vault/plan/`)

  - *Depends on:* ADRs, research, audits, (previous or related feature plans)

- **Execution Records**
  (`.vault/exec/{yyyy-mm-dd-feature}/{yyyy-mm-dd-feature-{phase}-{step}}.md`)

  - *Depends on:* Plans.
  - *References:* The Plan being executed.
  - *Location:* Inside feature-specific folder.
  - *Filename:* `{yyyy-mm-dd-feature-{phase}-{step}}.md` where `{phase}` and `{step}`
    are the canonical container identifiers (`P##`, `S##`) from the plan, zero-padded to
    a minimum of two digits. At `L1` the `{phase}` segment is omitted; at `L3`/`L4` a
    `{wave}` segment (`W##`) is prepended.
  - *Examples:*
    - L1: `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-S01.md`
    - L2: `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-P01-S01.md`
    - L3 / L4:
      `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-W01-P01-S01.md`

- **Summaries**
  (`.vault/exec/{yyyy-mm-dd-feature}/{yyyy-mm-dd-feature-{phase}-summary}.md`)

  - *Depends on:* Execution Records.
  - *References:* The Plan and key Artifacts produced.
  - *Location:* Inside feature-specific folder.
  - *Filename:* `{yyyy-mm-dd-feature-{phase}-summary}.md` where `{phase}` is the
    canonical Phase identifier (`P##`).
  - *Examples:*
    - L2: `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-P01-summary.md`
    - L3 / L4:
      `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-W01-P01-summary.md`

- **Feature Indexes** (`.vault/index/{feature}.index.md`)

  - *Auto-generated* by `vaultspec-core vault feature index`; never authored by hand.
  - *Filename:* `{feature}.index.md` (no date prefix).
  - *Example:* `.vault/index/editor-demo.index.md`

## Must follow

- We **ALWAYS** use **Obsidian-style Wiki Links** for internal documentation.

- **Always** populate the `related:` field in the YAML frontmatter with
  `'[[wiki-links]]'` (quoted as strings).

- **Never** use relative paths (`../`) in wiki links; assume a flat namespace or
  vault-root resolution.

- **Always** check if a referenced file exists before linking (if possible).

- **Always** include the relevant `#{feature}` tag in the YAML frontmatter using the
  `tags:` field.

- **Always** use the `tags:` field (not `feature:`) as a YAML list.

- **Always** quote wiki-links in YAML: `- '[[file-name]]'`.

## Tag Taxonomy

**ALLOWED TAGS - DO NOT REMOVE - REFERENCE:** `#adr` `#audit` `#exec` `#index` `#plan`
`#reference` `#research` `#{feature}`

Every document in `.vault/` MUST include the required tag pair in the frontmatter
`tags:` field:

- **Directory Tag**: Based on the `.vault/` subfolder location (`#adr`, `#audit`,
  `#exec`, `#index`, `#plan`, `#reference`, `#research`)

- **Feature Tag**: Groups related documents across the feature lifecycle (kebab-case,
  e.g., `#editor-demo`)

**CRITICAL:** No structural tags like `#step`, `#summary`, `#phase*`, or `#design` are
allowed. Every document carries exactly one directory tag plus exactly one `#{feature}`
tag - no more, no less. Any additional tag is read as a second feature tag and fails
validation.

### Directory Tags (Required for ALL documents)

The directory tag is determined by the file's location in `.vault/`:

| Directory           | Tag          | Description                              |
| :------------------ | :----------- | :--------------------------------------- |
| `.vault/adr/`       | `#adr`       | Architecture Decision Records            |
| `.vault/audit/`     | `#audit`     | Audit reports and assessments            |
| `.vault/exec/`      | `#exec`      | Execution records (steps & summaries)    |
| `.vault/index/`     | `#index`     | Auto-generated feature indexes           |
| `.vault/plan/`      | `#plan`      | Implementation plans                     |
| `.vault/reference/` | `#reference` | Implementation references and blueprints |
| `.vault/research/`  | `#research`  | Research and brainstorming               |

### Tag Format

All documents use YAML list syntax with exactly 2 tags (one directory tag, one feature
tag):

```yaml
---
tags:
  - '#plan'
  - '#feature-name'
date: '2026-02-06'
modified: '2026-02-06'
related:
  - '[[related-file]]'
---
```

`modified:` is a CLI-maintained last-modified stamp: set equal to `date:` at scaffold,
refreshed by every mutating verb and by `vaultspec-core vault check all --fix`, parsed
leniently but rewritten to the canonical quoted `yyyy-mm-dd` form, never hand-edited.

**Examples:**

- Plan file: `tags: ['#plan', '#editor-demo']`
- ADR file: `tags: ['#adr', '#editor-demo']`
- Exec step: `tags: ['#exec', '#editor-demo']`
- Exec summary: `tags: ['#exec', '#editor-demo']`
- Research: `tags: ['#research', '#text-layout']`
- Reference: `tags: ['#reference', '#text-layout']`
- Feature index (auto-generated): `tags: ['#index', '#editor-demo']`

### Feature Tags

Feature tags use kebab-case and group all documents related to a specific feature or
work stream:

- Format: `#{feature}` (e.g., `#live-preview-blocks`, `#grid-layout`,
  `#syntax-highlighting`)

- Must be consistent across all documents in the feature's lifecycle

- Always quoted in YAML

## Placeholder Naming Conventions

Templates use curly-brace placeholders `{...}` to indicate values that must be replaced.
Follow these conventions:

### Frontmatter Placeholders

| Placeholder      | Format                | Example                   |
| :--------------- | :-------------------- | :------------------------ |
| `{feature}`      | lowercase, kebab-case | `editor-demo`             |
| `{yyyy-mm-dd}`   | lowercase, ISO 8601   | `2026-02-06`              |
| `{yyyy-mm-dd-*}` | lowercase pattern     | `2026-02-04-feature-plan` |
| `{tier}`         | uppercase enum        | `L1`, `L2`, `L3`, `L4`    |
| `modified`       | CLI-maintained stamp  | `2026-02-06`              |

### Document Body Placeholders

Container identifiers (`{wave}`, `{phase}`, `{step}`) use the canonical uppercase
zero-padded form from the plan template hint blocks. `{feature}` uses lowercase
kebab-case. Narrative placeholders (`{topic}`, `{title}`) use concise prose.

| Placeholder | Format              | Example                   |
| :---------- | :------------------ | :------------------------ |
| `{feature}` | kebab-case          | `editor-demo`             |
| `{wave}`    | uppercase canonical | `W01`, `W02`              |
| `{phase}`   | uppercase canonical | `P01`, `P02`              |
| `{step}`    | uppercase canonical | `S01`, `S02`              |
| `{topic}`   | concise prose       | `event handling`          |
| `{title}`   | concise prose       | `display map integration` |

### Machine-Filled Placeholders

A separate placeholder class is filled by the CLI, never by the author. Machine-filled
placeholders use snake_case to distinguish them from author-replaced placeholders; do
not fill or rename them by hand - scaffold the document through the owning CLI verb
instead.

| Placeholder       | Filled by                            | Value                                           |
| :---------------- | :----------------------------------- | :---------------------------------------------- |
| `{heading}`       | `vaultspec-core vault add exec`      | The originating Step row's action text          |
| `{step_id}`       | `vaultspec-core vault add exec`      | The Step's canonical identifier (`S##`)         |
| `{plan_stem}`     | `vaultspec-core vault add exec`      | The parent plan's filename stem                 |
| `{scope_block}`   | `vaultspec-core vault add exec`      | A Scope section listing the Step's scoped files |
| `{document_list}` | `vaultspec-core vault feature index` | The feature's full document list                |

### General Rules

- **YAML frontmatter**: Always lowercase, kebab-case

- **Document titles/headings**: The shipped templates are canonical for level-one
  headings. Top-level vault documents use backticks around both the `{feature}` segment
  and the narrative `{title}`, `{topic}`, or `{phase}` segment. Examples:
  `# {feature} research: {topic}` represents the literal template heading '# `{feature}`
  research: `{topic}`', and `# {feature} plan` represents '# `{feature}` plan'.
  Narrative segments should be concise prose; canonical uppercase identifiers remain
  required for `{wave}`, `{phase}`, and `{step}` identifier segments.

- **File names**: lowercase kebab-case for narrative segments (`{feature}`, `{type}`);
  canonical uppercase identifiers for `{wave}`, `{phase}`, `{step}` segments. Patterns:

  - Top-level docs: `yyyy-mm-dd-{feature}-{type}.md` (e.g.,
    `2026-02-04-editor-demo-plan.md`)

  - Exec Steps (L1): `yyyy-mm-dd-{feature}-{step}.md` (e.g.,
    `2026-02-04-editor-demo-S01.md`)

  - Exec Steps (L2): `yyyy-mm-dd-{feature}-{phase}-{step}.md` (e.g.,
    `2026-02-04-editor-demo-P01-S01.md`)

  - Exec Steps (L3 / L4): `yyyy-mm-dd-{feature}-{wave}-{phase}-{step}.md` (e.g.,
    `2026-02-04-editor-demo-W01-P01-S01.md`) inside `.vault/exec/yyyy-mm-dd-{feature}/`
    folder.

  - Exec Summaries (L2): `yyyy-mm-dd-{feature}-{phase}-summary.md` (e.g.,
    `2026-02-04-editor-demo-P01-summary.md`)

  - Exec Summaries (L3 / L4): `yyyy-mm-dd-{feature}-{wave}-{phase}-summary.md` (e.g.,
    `2026-02-04-editor-demo-W01-P01-summary.md`) inside the feature folder.

- **Replace ALL placeholders**: No template should be committed with `{...}`
  placeholders remaining. Run `vaultspec-core vault check all --fix` to validate and
  format documents before committing - it reconciles frontmatter, strips leftover
  template annotations, and applies markdown hygiene fixes. The dedicated
  `vaultspec-core vault check placeholders` check surfaces any `{...}` residue left in
  body prose, which must be filled in by hand or by the owning CLI verb.
</vaultspec>
