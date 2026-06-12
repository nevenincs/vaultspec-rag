---
tags:
  - '#research'
  - '#service-concurrency'
date: '2026-06-12'
related:
  - "[[2026-06-11-server-bound-search-production-readiness-adr]]"
  - "[[2026-04-02-service-graph-adr]]"
  - "[[2026-06-02-index-gpu-pipeline-adr]]"
  - "[[2026-06-02-index-perf-hardening-adr]]"
  - "[[2026-06-05-qdrant-performance-adr]]"
  - "[[2026-06-07-sparse-search-latency-adr]]"
---

# `service-concurrency` research: `concurrent service saturation architecture`

Architecture survey for reworking the resident service and backend so they can serve
multiple agents, multiple concurrent repo roots, and saturated call loads. Hardware
benchmarks confirm minimal GPU and CPU utilization under load, so the throughput cap is
software serialization, not hardware. This research inventories every serialization
point in the request and index paths, collects the settled constraints and measured
baselines from prior performance work, and frames the option space for the follow-on
ADR. It positions itself as the architectural successor to the server-bound-search
production-readiness ADR, which named the GPU/Qdrant/writer-lock contention problem
space and explicitly deferred queueing and backpressure.

## Findings

### F1. Why utilization is low: requests alternate between two exclusive locks

A single search on the service path acquires the **global** `gpu_lock` twice — once for
the dense+sparse query encode (`search/_searcher.py:686-693`) and once for the entire
CrossEncoder `predict` retry loop (`search/_searcher.py:257-275`) — with the per-root
Qdrant scan under `store._client_lock` in between (`store.py:1052-1092`). Under
concurrent load every request ping-pongs between a process-global GPU mutex and a
per-root storage mutex. Neither resource is ever pipelined: while one request holds the
GPU lock, the Qdrant phase of every other request on the hot root is blocked behind the
storage lock, and vice versa. The observable signature is exactly what the hardware
benchmarks show — GPU mostly idle, at most one CPU core busy inside the storage lock.

### F2. Ranked serialization inventory

Ranked by suspected throughput impact:

1. **Per-root `store._client_lock`** (`store.py:315`, an `RLock`): wraps every Qdrant
   operation because `QdrantLocal` is not thread-safe. Consequences: no read/read
   concurrency at all; reads block during upserts; both collections (`vault_docs`,
   `codebase_docs`) share one lock, so vault search and code search on the same root
   serialize against each other. Qdrant local mode is an in-process brute-force scan
   (local mode ignores payload indexes — settled in the sparse-search-latency ADR), so
   the lock is held for the longest CPU-bound phase of the request. **Hardest cap for a
   single hot root.**
1. **Global `gpu_lock`** (`service.py:117`): one lock shared by every root's searcher
   and both indexers. Held across query encode and the full reranker predict loop per
   search, and across every index slice encode. All roots serialize here; an index run
   on root A delays every search encode on root B. Prior estimate (PERF-001) put the
   combined hold at ~40-100ms per search; everything process-wide is strictly
   sequential within those holds.
1. **MCP transport hazard**: every tool in `mcp/_tools.py` is `async def` but performs
   a blocking `urllib.request.urlopen` to the daemon (`mcp/_tools.py:46-47`) with no
   thread dispatch. The daemon also mounts the same MCP app at `/mcp`
   (`server/_main.py:133`), so a tool call served there issues a blocking loopback HTTP
   request back into the same single-event-loop server **from the loop thread** — at
   best a full-server stall for the round trip, at worst self-deadlock. For agent
   traffic arriving via MCP rather than raw HTTP, this alone can serialize the entire
   service. Needs runtime confirmation of which transport agents actually exercise.
1. **anyio default thread limiter (40 tokens, process-wide)**: no custom
   `CapacityLimiter` anywhere. Searches, minutes-long background reindex jobs
   (`jobs.py:323,389`), and watcher reindexes (`watcher.py:284,356`) all draw from the
   same pool, so a handful of long index jobs permanently consume tokens that searches
   need.
1. **Event-loop blocking in handlers**: `_ensure_watcher` runs `peek_project` (50-200ms
   cold) on the loop thread per search route hit (`server/_routes.py:684`); log reads
   run synchronously on the loop (`_routes.py:965`); `_watcher_lock` is a
   `threading.Lock` acquired inside async handlers.
1. **Secondary overheads**: `jobs._lock` is global and `JobProgressReporter.advance()`
   takes it once per indexed file/chunk with a linear deque scan (`jobs.py:157-166`,
   `:264-272`); each search route call also runs `get_status` inside the same request
   (`_routes.py:625`), adding extra `_client_lock` acquisitions; `RegistryFullError`
   and LRU eviction tear-downs run on the leasing request's thread.

### F3. Search path (per-request lock sequence)

`POST /search` → `anyio.to_thread` (default limiter) → `registry.lease(root)` (brief
global `RLock` holds; exception: cold `load_model()` holds the registry lock across a
multi-second model construction) → `gpu_lock` encode → `_client_lock` hybrid
`query_points` → `gpu_lock` rerank → graph boost (per-root `GraphCache._lock`, full
rebuild on TTL expiry blocks that root's searchers). Timing plumbing for
`gpu_queue_wait_seconds`, `project_lease_seconds`, and phase attribution already exists
on this branch and is the measurement substrate for the rework.

### F4. Write path and index-vs-search contention

Indexers hold a per-root, per-corpus `_writer_lock` for the **entire** run
(`indexer/_vault_indexer.py:103,298`; `indexer/_codebase_indexer.py:976,1116`) —
minutes for a full index. Per slice they take `gpu_lock` for the encode only (released
before upsert), then `_client_lock` for the upsert. So: index-A vs search-A contend on
both `gpu_lock` and `_client_lock` (with no fairness — a tight slice loop can starve
search's Qdrant phase); index-A vs search-B contend only on `gpu_lock` plus the shared
thread pool. The single GPU consumer thread and CPU-only spawn workers are settled
design (see F6) — write-path gains must come from overlapping non-GPU phases, not more
GPU consumers.

### F5. Qdrant local-mode constraints and the server-mode escape hatch

`QdrantClient(path=...)` is process-exclusive (own `FileLock` at `store.py:334-336`
plus qdrant's own guard) and not thread-safe, which is the entire reason
`_client_lock` exists. Local mode has no inverted sparse index (linear SPLADE scan
measured at ~20s over ~114k chunks) and no payload-index pushdown. The
qdrant-performance ADR already accepted **server mode** (`VAULTSPEC_RAG_QDRANT_URL`)
as the concurrency escape hatch with mandatory local-mode fallback: server mode lifts
the single-process constraint, gives true concurrent reads, real HNSW/sparse indexes,
and payload-index pushdown. The `_client_lock` would remain as a purely software cap
unless narrowed/removed for server-mode clients.

### F6. Settled constraints binding the design space (do not re-litigate)

- Exactly one GPU consumer thread owns `gpu_lock` for indexing; no CUDA streams, no
  second consumer, no inline encode on the pool-draining thread; all consumer shutdown
  waits liveness-guarded and time-bounded (`gpu-consumer-single-thread` rule).
- Index workers are CPU-only spawn processes with lazy `torch` imports across the whole
  worker import chain (`index-workers-stay-cpu-only` rule).
- One global resident service, one shared `EmbeddingModel` and `CrossEncoder`;
  multi-tenant = shared compute, isolated per-root storage. No serving frameworks at
  this scale. `stateless_http=True`.
- No background sweeper/timer threads (rejected repeatedly); eviction stays lazy,
  refcounted, skip-busy. The three-level lock dance (global → per-root → global) for
  parallel cold starts of different roots must be preserved.
- Daemon inherits only env; new concurrency knobs must be `VAULTSPEC_RAG_*` env vars
  translated from CLI flags.
- Operability telemetry is service-domain-owned and surfaced uniformly across
  CLI/MCP/HTTP (`service-domain-owns-operability`); any new queue/lock-wait views are
  bounded and filterable (`operator-views-are-bounded`); CLI-visible changes end with
  manual persona tests in human and JSON modes.
- Tests use real GPU + real Qdrant; no mocks/skips. GPU is an RTX 4080 16GB; no GPU CI
  — concurrency claims are verified locally.
- The in-flight `cli-service-operability-hardening` epic (same branch) owns the
  status/jobs/logs/search-diagnostics surfaces and route shapes in
  `server/_routes.py`; this feature must not redesign those surfaces. It explicitly
  left performance, queueing, and backpressure to this work.

### F7. Measured baselines to beat

- Warm service-backed search: **0.86s** repeat; phase split embedding ~0.55s, qdrant
  ~0.40s, rerank ~0.095s, postprocess ~0.095s. Cold lease ~6.53s → 1.35s after
  reranker lifespan preload (cost is setup, not GPU-lock contention when idle).
- Prior gpu-lock full-pipeline hold estimate: ~40-100ms per search (PERF-001).
- Sparse local-mode scan: up to ~20s across ~114k chunks.
- Index pipeline: chunk stage 1.9-3.6x with the process pool; embed ~17 min for 112k
  chunks at `bs=32` (OOM at `bs>=64` on the 16GB card).
- **Gap:** no benchmark drives N concurrent searches (same-root or cross-root) or
  measures `gpu_queue_wait_seconds` / `_client_lock` wait under saturation, despite the
  timing plumbing existing. This is the first thing the execution phase must build.

### F8. Saturation test substrate

A large production-shaped corpus exists at the `chore-476-restructure-execution`
worktree (separate repository, currently served by the resident service): **6.3 GB** of
search data across both collections. Combined with this repo's own index it provides a
realistic two-root, mixed-size setup for cross-root contention and saturation
benchmarks against the live service on port 8766.

### F9. Option space for the ADR

Ordered roughly by leverage-to-risk:

- **O1 — Storage read concurrency.** (a) Promote Qdrant server mode to the recommended
  concurrent deployment and make the store's locking strategy backend-aware: per-root
  reader-writer lock (concurrent reads, exclusive writes) or no lock at all for
  server-mode clients, retaining the exclusive `RLock` only for local mode. (b) Split
  the lock per collection so vault and code searches stop serializing against each
  other even in local mode.
- **O2 — Narrow the global `gpu_lock` holds.** Keep one lock (single GPU is physics)
  but shrink what runs under it: move CrossEncoder batch assembly/tensor prep outside
  the lock, hold it only for the actual forward pass; consider micro-batching/admission
  so concurrent requests' encodes coalesce into one batched forward instead of N serial
  holds. Tokenization outside the lock where possible.
- **O3 — Fix the MCP transport.** Replace blocking `urllib` in async tools with a
  thread-dispatched or async HTTP client, and either unmount the self-referential
  `/mcp` path on the daemon or make its tools call the service domain in-process
  instead of looping back over HTTP.
- **O4 — Resource-aware admission and backpressure.** Dedicated `CapacityLimiter`s:
  separate pools for searches vs index jobs so long writes cannot exhaust the 40-token
  default pool; bounded queue with depth surfaced via the existing jobs/metrics
  surfaces; explicit `429`/busy signaling per the production-readiness ADR contract.
- **O5 — Fairness between index and search.** Yield points or a fairness gate in the
  slice loop so a long index run cannot starve same-root searches; possibly
  search-priority acquisition on `_client_lock`.
- **O6 — Event-loop hygiene.** Move `peek_project`, log reads, and `_watcher_lock`
  acquisitions off the loop thread; make `_ensure_watcher` non-blocking.
- **O7 — Telemetry first.** A concurrency benchmark harness (N parallel searches ×
  same-root/cross-root × during-index) plus lock-wait metrics, built before any lock
  surgery so every change is measured against F7 baselines on the F8 corpus.

### F10. Open questions for the ADR phase

- Which transport do real agents use against the daemon — `/mcp` tools or raw HTTP
  routes? Determines how hot the O3 hazard is.
- Is server-mode Qdrant acceptable as the *recommended* (not just supported) topology
  for multi-agent deployments, given it requires an external process?
- Can the encode and rerank phases of different requests legally interleave with an
  index slice encode (single lock, three acquisition sites) without violating the
  single-consumer rule? (The rule binds indexing topology, not search-side batching.)
- What is the right admission-control surface: per-root, per-request-class, or global?
- Does `QdrantLocal` tolerate concurrent reads in practice (upstream thread-safety is
  undocumented), or is the read/write RW-lock the only safe local-mode improvement?

## Implementation depth review

Hands-on review (no agents) of the semantic-search core — `embeddings.py`,
`search/_searcher.py`, `search/_rerank.py`, `store.py`, `indexer/_chunking.py`,
`indexer/_ast_chunker.py`, `indexer/_streaming.py`, `config.py` — judging the
implementation itself against current best practice, independent of the concurrency
architecture above. Findings continue the F-numbering; option-space additions extend
F9.

### F11. Reranker scores 200-character snippets, not content (critical, quality)

`_rerank` builds its pairs as `(query, r.snippet)` where the snippet was created as
`content[:200]` during result mapping (`search/_searcher.py:254`, `:397`, `:478`).
BAAI/bge-reranker-v2-m3 accepts ~8k tokens, but it only ever sees the first 200
characters of each candidate — for vault hits that is typically the title plus the
opening sentence; for code chunks the signature line and little else. The CrossEncoder
stage is therefore reranking on a prefix proxy, biased toward candidates whose opening
characters echo the query, and most of its semantic power is discarded. The full
content is already in the payload and in memory at that point. This also explains why
the measured rerank phase is so cheap (~0.095s): the pairs are tiny. Reranking the full
chunk text (truncated to a few hundred tokens) is the single highest-leverage quality
fix found in this review; its GPU cost increase lands exactly in the `gpu_lock` hold
that O2 proposes to restructure, so the two must be designed together.

### F12. Vault documents are unchunked single vectors truncated at 8000 chars (critical, quality)

The vault index path embeds `title + "\n\n" + content` as **one dense vector and one
sparse vector per document** (`indexer/_streaming.py:94`), and `encode_documents`
truncates input at `max_embed_chars=8000` (`embeddings.py:440`). Consequences: content
beyond ~2000 tokens is invisible to retrieval (many ADRs, audits, and plans in this
vault exceed 8000 chars — their tails simply cannot be found); a long document's single
vector dilutes across every topic it covers; and retrieval granularity is whole-doc, so
the returned snippet (`content[:200]`) almost never shows the passage that matched.
Notably the codebase already ships a structure-aware markdown splitter
(`TextSplitter` in `indexer/_chunking.py` with heading separators) — it is simply never
applied to vault documents. Modern practice is heading-aware chunking with doc-level
metadata on each chunk and parent-document expansion at answer time; late chunking
(embed full doc once, pool per-chunk token embeddings) is the bleeding-edge variant the
2048-token cap currently precludes. This is the vault-side twin of F11 and the second
critical quality finding.

### F13. Embedding inputs carry no context; Qwen3 instruction capacity unused (quality)

Code chunks are embedded as raw chunk text only (`_streaming.py:184`): the file path,
language, enclosing class, and function name are stored as payload but never enter the
embedded text, so a query like "watcher debounce reconfigure" cannot match a chunk via
its location or naming context. Prepending a one-line contextual header (path,
class/function) to the embedded text is a cheap, widely validated win (contextual
retrieval). Separately, both vault and code queries use the same generic
`prompt_name="query"` instruction (`embeddings.py:479`); Qwen3-Embedding is
instruction-tuned and its model card documents 1–5% gains from task-specific
instructions — a code-retrieval instruction for `search_codebase` and a
documentation-retrieval instruction for `search_vault` are zero-cost to add. Documents
are truncated by characters mid-token (`t[:max_chars]`), which is crude but acceptable.

### F14. Graph boost multiplies calibrated reranker scores after reranking (quality)

`rerank_with_graph` runs **after** the CrossEncoder and multiplies its sigmoid-
calibrated [0,1] scores: ×(1 + 0.1·min(in_links, 10)) — up to ×2.0 — plus ×1.15 for a
feature-tagged neighbor (`search/_rerank.py:33-44`). A hub document with ten in-links
(umbrella plans, indexes) doubles its relevance score and can displace a strictly more
relevant hit. The multiplicative form was scale-safe when scores were RRF ranks, but
against calibrated reranker output it is a very strong structural prior. Modern
practice bounds the structural signal (additive nudge on near-ties, as `--prefer`
already correctly does with `PREFER_SCORE_NUDGE`) or feeds it to the reranker rather
than overriding it.

### F15. SPLADE-v3 on source code is unvalidated (quality, cost)

The sparse branch applies naver/splade-v3 — a model trained on natural-language MS
MARCO passages — to source code. Code identifiers tokenize poorly in a BERT WordPiece
vocabulary, so the learned expansion is of unproven value for the `codebase_docs`
collection, while costing a second encode per query/slice and the dominant share of
local-mode query latency at scale (the ~20s/114k-chunk linear sparse scan in F7). No
benchmark currently compares code-search quality with `sparse_enabled` on versus off.
An A/B on the existing benchmark harness should decide whether code keeps SPLADE,
switches to a code-aware lexical signal, or runs dense+rerank only.

### F16. Hot-path implementation inefficiencies (performance)

- `_sparse_tensor_to_results` (`embeddings.py:94-152`) densifies the SPLADE output to
  `[batch × ~30k vocab]`, then loops per row calling `.nonzero()` / `.tolist()` —
  O(batch×vocab) work plus a GPU→CPU sync per row, executed inside the `gpu_lock` hold
  on every index slice. A single `.coalesce()` on the COO tensor (or one CSR transfer
  to CPU) replaces the loop.
- Every search issues two sequential model calls (dense then sparse encode) per query
  under the GPU lock; batch-of-one inference both times. Cross-request micro-batching
  (O2) and a small LRU cache of query embeddings (agents repeat queries verbatim)
  would remove most of this.
- Vectors round-trip through Python lists (`vec.tolist()` per point in
  `_streaming.py:118,198`) before Qdrant serialization — minor CPU cost at 112k-chunk
  scale.
- `get_all_ids`/`get_all_code_ids` scroll the entire collection (1000-point pages,
  lock per page) on every incremental index to compute stale IDs — O(N) per watcher
  tick on large roots.
- File-level blake2b hashing skips unchanged files, but any changed file re-encodes
  **all** its chunks; a chunk-content-hash embedding cache would skip unchanged chunks
  within edited files (typically the vast majority).

### F17. Model stack currency (quality, modernity)

Qwen3-Embedding-0.6B (2025) remains a sound choice at this VRAM budget, and the
pipeline uses it correctly (left padding for last-token pooling, asymmetric
query/document prompts, fp16, flash-attention-2 when present). Gaps against the
current frontier: the reranker BAAI/bge-reranker-v2-m3 (2024) is superseded — the
Qwen3-Reranker family (0.6B/4B) outperforms it on retrieval benchmarks, pairs with the
embedding family, and fits the same VRAM envelope; Qwen3-Embedding's Matryoshka
support is unused (truncating 1024d→512d roughly halves Qdrant memory and scan cost
for small quality loss — directly attacks the F2 `_client_lock` hold); bf16 (native on
the RTX 4080) would be the more numerically robust dtype than fp16. The ONNX backend
seam remains upstream-blocked (settled, F6).

### F18. Collection schema is server-mode-naive (performance, forward-looking)

`_ensure_collection` (`store.py:440-452`) creates collections with bare defaults: no
`hnsw_config`, no vector `datatype` (fp16 storage would halve vector memory), no
`on_disk` policy, default sparse index parameters, and the quantization knob is
opt-in-only. All of this is ignored by local mode (brute-force scan), which is why it
has never mattered — but O1's promotion of server mode makes the collection schema the
next bottleneck: an unconfigured HNSW index, fp32 vectors, and no quantization on a
6.3 GB corpus forfeits most of server mode's win. Schema decisions (HNSW m/ef, fp16
datatype, scalar quantization default-on for server mode, Matryoshka dimension) belong
in the same ADR as O1. Existing strengths to preserve: idempotent stable-ID upserts,
per-prefetch filters (settled), RRF via the Universal Query API, payload indexes
already declared for server-mode pushdown, and the dense-only fallback path.

### F19. What is already good

For balance: the cAST-style AST chunker is current best practice and cleanly
implemented; greedy sibling merge with a half-budget merge pass is sensible; the
streaming slice pipeline with length-sorted batching, OOM halving, throttled CUDA
cache flushes, and idempotent per-slice upserts is a mature design; asymmetric SPLADE
encode (document vs query) is correct; the RRF hybrid query structure matches Qdrant's
recommended pattern; incremental indexing via blake2b file digests is sound. The
implementation problems are concentrated in what surrounds the models (snippet-based
reranking, unchunked vault docs, context-free embedding inputs, post-rerank boosts) —
not in the pipeline engineering.

### F9 addendum: option-space additions from the implementation review

- **O8 — Rerank on real content.** Feed the reranker full chunk/document text
  (token-bounded), not 200-char snippets. Design jointly with O2 since it grows the
  GPU hold.
- **O9 — Chunk the vault corpus.** Heading-aware markdown chunking (the existing
  `TextSplitter` supports it), chunk-level vectors with doc metadata, parent-document
  expansion at answer time; evaluate late chunking as the stretch variant. Removes the
  8000-char blindness.
- **O10 — Contextual embedding inputs + task instructions.** Prepend path/symbol
  headers to code-chunk text; add per-surface Qwen3 query instructions.
- **O11 — Bound the graph boost.** Convert the post-rerank multiplicative boost to a
  bounded additive nudge or a rerank-input feature.
- **O12 — Model refresh evaluation.** Benchmark Qwen3-Reranker against
  bge-reranker-v2-m3, and Matryoshka 512d against 1024d, on the existing quality
  harness before any swap.
- **O13 — Sparse-on-code A/B.** Measure code-search quality with the SPLADE branch on
  vs off; keep, replace, or scope it to vault accordingly.
- **O14 — Server-mode collection schema.** HNSW config, fp16 vector datatype, default
  scalar quantization, sparse index params — decided together with O1.
