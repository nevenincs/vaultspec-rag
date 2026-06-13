---
tags:
  - '#adr'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-12'
related:
  - "[[2026-06-12-service-concurrency-research]]"
  - "[[2026-06-11-server-bound-search-production-readiness-adr]]"
  - "[[2026-06-05-qdrant-performance-adr]]"
  - "[[2026-06-02-index-gpu-pipeline-adr]]"
---

# `service-concurrency` adr: `concurrent saturation architecture rework` | (**status:** `accepted`)

## Problem Statement

Hardware benchmarks show minimal GPU and CPU utilization while the resident service is
saturated with requests: throughput is capped by software serialization, not compute.
The sibling research's lock inventory (F1–F8) identified the causes — every request
alternates between a process-global `gpu_lock` (held across query encode and the full
CrossEncoder predict loop) and a per-root `store._client_lock` that wraps every Qdrant
operation with zero read concurrency; MCP tools block the single event loop with
synchronous loopback HTTP; searches and minutes-long index jobs share one default
40-token thread pool. The same review found two critical retrieval-quality defects in
the implementation core (F11: the reranker scores 200-character snippets; F12: vault
documents are unchunked single vectors truncated at 8000 chars) plus a set of
quality/efficiency gaps (F13–F18). This ADR decides the rework that fixes all
identified issues, with adversarial saturation conditions as the acceptance gate: the
service must demonstrably serve multiple agents, concurrent repo roots, and saturated
call loads without deadlock, starvation, or quality regression.

## Considerations

- The single-GPU physics are settled: no compute/compute overlap exists; gains must
  come from overlapping non-GPU phases, shrinking lock holds, and batching — never
  from a second GPU consumer.
- `QdrantLocal` source inspection confirms each collection owns independent state (its
  own in-memory structures and its own sqlite connection via `CollectionPersistence`);
  the only cross-collection shared mutable state is the client's collections dict.
  Per-collection locking is therefore structurally sound when collection lifecycle
  (create/drop) stays under a store-level lock. qdrant-client also probes sqlite
  THREADSAFE and sets `check_same_thread` accordingly, so cross-thread access to one
  collection's connection is supported.
- Qdrant server mode (`VAULTSPEC_RAG_QDRANT_URL`) is already the accepted concurrency
  escape hatch; the server and its client are concurrency-safe, so software locking
  for server-mode stores is pure overhead.
- The reranker fix (rerank on real content) increases GPU work per request, landing
  exactly inside the lock hold the concurrency work narrows — the two must be designed
  and measured together.
- Vault chunking changes the vault collection's point granularity and requires a
  one-time rebuild of `vault_docs`; the public search contract (doc-level results)
  must be preserved by grouping chunk hits per document.
- The in-flight `cli-service-operability-hardening` feature on this branch owns the
  status/jobs/logs surfaces and `server/_routes.py` shapes; this work must keep route
  edits minimal and additive.

## Constraints

- `gpu-consumer-single-thread` rule: one GPU consumer for indexing; all shutdown waits
  liveness-guarded and bounded. Binding.
- `index-workers-stay-cpu-only` rule: spawn workers, lazy torch imports. Binding.
- No background sweeper/timer threads (repeatedly rejected pattern). Backpressure and
  limiters must be lazy/traffic-driven.
- Daemon inherits only env: every new tuning knob ships as a `VAULTSPEC_RAG_*` env var
  with CLI translation.
- `service-domain-owns-operability`: new telemetry (queue depth, lock waits) is
  service-domain first, uniform across adapters; `operator-views-are-bounded` applies
  to any new view.
- Tests are real-GPU/real-Qdrant, no mocks/skips; GPU CI does not exist — adversarial
  benchmarks run locally (RTX 4080 16 GB) against the 6.3 GB two-root corpus.
- ONNX dense backend remains upstream-blocked (settled); torch is the only encoder
  backend in scope.

## Implementation

Eleven accepted decisions, three explicit deferrals.

**D1 — Adversarial benchmark harness first (research O7).** A concurrency benchmark
drives N parallel searches (same-root, cross-root, vault+code mixed) optionally during
a live index run, against real service plumbing, and reports throughput, p50/p95
latency, and the existing phase timings (`gpu_queue_wait_seconds`, `qdrant_seconds`,
lease waits). It captures the baseline before any lock surgery and re-runs after each
wave; it is also the acceptance instrument for the adversarial gate. Quality
benchmarks (existing `benchmark`/`quality` harness) guard against relevance
regressions from D7–D9.

**D2 — Backend-aware, per-collection storage locking (O1).** The store's single
`_client_lock` splits: a store-level lock guards client lifecycle and collection
create/drop; each collection gets its own lock for point operations. Local mode keeps
exclusive per-collection locks (QdrantLocal is not thread-safe within a collection);
server mode skips point-operation locking entirely. Net effect: vault and code
searches stop serializing against each other; index upserts on one collection stop
blocking searches on the other; server mode gains true concurrency.

**D3 — GPU lock narrowing + rerank on real content (O2 + O8).** The reranker input
becomes the full result content, token-bounded by the CrossEncoder's own tokenizer
(`max_length` ~512–1024), replacing the 200-char snippet pairs (F11). Jointly, the
`gpu_lock` holds shrink: pair assembly, tokenization-adjacent prep, and result
mapping move outside the lock; the lock wraps only the model forward calls. A small
thread-safe LRU cache of query embeddings (keyed by surface + cleaned query text)
removes repeat-encode holds for agents that re-issue identical queries.

**D4 — Async-safe MCP transport (O3).** The MCP tools' blocking `urllib` daemon calls
move off the event loop (thread dispatch with the existing timeouts). This removes the
full-server stall/self-deadlock hazard when tools are served from the daemon's own
`/mcp` mount, and unblocks the stdio MCP process's loop during daemon round trips.

**D5 — Dedicated capacity limiters (O4).** Two `anyio.CapacityLimiter`s replace
implicit sharing of the 40-token default pool: a search limiter (default 16) and an
index-job limiter (default 4), both env-tunable. Long reindex jobs can no longer
exhaust the pool that serves searches; saturation beyond the limiter queues instead of
piling threads.

**D6 — Event-loop hygiene (O6).** `_ensure_watcher`'s cold `peek_project` and the log
reads dispatch to threads; `threading.Lock` acquisitions inside async handlers are
audited and made loop-safe. Route shapes do not change.

**D7 — Vault document chunking (O9).** The vault index path applies the existing
heading-aware markdown `TextSplitter` to document bodies, producing one point per
chunk carrying the parent doc's metadata (doc_id, doc_type, feature, date, tags,
title) plus a chunk ordinal. Point IDs derive from `doc_id#ordinal` so upserts stay
idempotent and deletion-by-document filters on the `doc_id` payload. Search groups
chunk hits per document (best-chunk score; snippet from the matched chunk, not the doc
head), preserving the doc-level result contract. `get_by_id` and document listings
continue to serve full documents (payload retains full content on a designated head
chunk or via doc-level reconstruction). Requires a one-time vault collection rebuild,
performed automatically by detecting the index schema version bump.

**D8 — Contextual embedding inputs + per-surface instructions (O10).** Code chunks are
embedded with a one-line contextual header (project-relative path, enclosing
class/function) prepended to the chunk text; stored content stays raw. Vault chunks
embed `title + heading-path + chunk text`. Queries gain per-surface Qwen3
instructions: a code-retrieval instruction for codebase search, a documentation-
retrieval instruction for vault search.

**D9 — Bounded graph nudge (O11).** The post-rerank multiplicative graph boost
(×2.0 in-links, ×1.15 feature-neighbor) becomes a bounded additive nudge in the same
spirit as the existing `--prefer` mechanism, so structural priors break ties instead
of overriding calibrated relevance.

**D10 — Sparse conversion and hot-path hygiene (F16).** SPLADE output conversion stops
densifying `[batch × vocab]` tensors and looping per row; a single coalesced-COO (or
one CPU CSR transfer) pass replaces it, shrinking index-slice `gpu_lock` holds.
Vector list round-trips are trimmed where the client accepts arrays.

**D11 — Concurrency telemetry (service-domain).** Limiter queue depths, per-collection
lock wait times, and reranker batch sizes surface through the existing metrics/jobs
plumbing (bounded views), giving the benchmark harness and operators the same signal.

**Deferred:**

- **DX1 — Model refresh (O12):** Qwen3-Reranker vs bge-reranker-v2-m3 and Matryoshka
  512d vs 1024d are benchmark-gated follow-ups once D1's harness and D3's content
  reranking land (a reranker eval against snippet-based scoring would be meaningless).
- **DX2 — Sparse-on-code A/B (O13):** run on D1's harness; decision recorded as a
  follow-up ADR amendment.
- **DX3 — Server-mode collection schema + promotion (O14):** HNSW config, fp16 vector
  datatype, default quantization, and operational promotion of server mode are a
  separate feature; D2 keeps the store backend-aware so the seam is ready.

## Rationale

The research's F1 finding explains the observed idle hardware: strict alternation
between two exclusive locks with no pipelining. D2 and D3 attack the two locks
directly along the only legal axis (narrowing holds and removing false sharing — the
single-GPU and single-writer-local constraints stay intact). D4–D6 remove the
event-loop and thread-pool failure modes that can serialize the whole service
regardless of lock behavior. D7–D9 fix the quality defects that would otherwise make a
faster service merely return bad results faster — and D3/D7 interact (content
reranking needs chunk-granular content to rerank), which is why they ship in one
architecture revision rather than as independent patches. D1 brackets everything:
since utilization claims started this work, every change must be measured against the
same adversarial harness on the same corpus.

## Consequences

- Search concurrency improves on every axis that is legally improvable: cross-
  collection, cross-root, and within-request pipelining; the GPU lock degenerates to
  forward-pass-only holds. The hard residual is local-mode same-collection
  serialization, which only DX3 (server mode) removes.
- Vault retrieval quality changes behavior: long documents become findable past 8000
  chars, snippets show matched passages, and hub documents stop dominating via
  structural boosts. Result ordering will visibly change; the quality harness is the
  regression gate.
- The vault collection rebuild is a one-time migration cost per root (minutes on
  large vaults), triggered by schema-version detection.
- Rerank cost rises by design (real content through the CrossEncoder); D3's
  narrowing and D1's measurements must confirm the net effect on saturated throughput
  stays positive.
- Touching `mcp/_tools.py`, `service.py`, and `store.py` concurrently with the
  in-flight operability feature carries merge risk; route-shape freezes and additive
  edits mitigate it.
- The backend-aware lock seam plus telemetry leaves DX3 (server-mode promotion) a
  configuration-and-schema exercise rather than another lock rework.

## Codification candidates

- **Rule slug:** `gpu-lock-wraps-forward-passes-only`.
  **Rule:** The global GPU lock may be held only across model forward calls (encode,
  predict); tokenization, pair assembly, tensor post-processing, and any storage I/O
  must run outside it.
- **Rule slug:** `storage-locks-are-backend-aware`.
  **Rule:** Store-layer locking must distinguish local mode (exclusive per-collection
  locks) from server mode (no point-operation locks); never reintroduce a single
  store-wide mutex across collections.
- **Rule slug:** `rerankers-score-real-content`.
  **Rule:** Reranking inputs must be the token-bounded full candidate content, never a
  fixed-character snippet proxy.
