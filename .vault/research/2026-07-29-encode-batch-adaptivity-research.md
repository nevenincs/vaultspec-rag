---
tags:
  - '#research'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:05d53073d5c903651e99da76f8fa8ad81640e29bad46de4e898d20d764d97887'
related:
  - "[[2026-07-24-index-throughput-adr]]"
  - "[[2026-07-24-index-cuda-ceiling-adr]]"
  - "[[2026-07-24-index-cuda-shared-device-adr]]"
  - "[[2026-07-28-index-observability-adr]]"
  - "[[2026-06-02-onnx-encoder-backend-adr]]"
---

# `encode-batch-adaptivity` research: `encode tail throughput collapse: remediation pathways`

Why does a code-index run encode at full speed for ~90% of its corpus and then
collapse roughly 10-20x for the tail, and what are the remediation pathways? The
question matters because the collapse presents to operators as a hang, survives the
degradation verdict as `healthy`, and turns the last 10% of a run into half its
wall-clock. A live incident (job `474cb8b0`, 2026-07-29, incremental code index of
4,703 files, succeeded in 1,723 s) was instrumented end to end. The evidence
exonerates the storage path entirely and localises the collapse to a three-way
collision on the encode stage: a count-based encode batch size with unbounded token
footprint, an OOM backoff ladder whose learned ceiling oscillates instead of
converging under ~500-600 MiB of VRAM headroom, and a whole-slice retry granularity
that discards completed GPU work on every OOM. Five remediation pathways are framed
below; the evidence favors token-budgeted batching as the root fix, with
sub-batch-scoped OOM retry as the independent resilience fix.

## Findings

### The collapse is a step function caused by CUDA OOM events, not gradual decay

The run encoded the first ~4,000 of 4,703 files in under 5 minutes (operator
observation, consistent with derived ~160 chunks/s), then collapsed after two
back-to-back CUDA OOMs at 08:30:12 dropped the dense encode batch from 32 to 16 to 8
(service log, `vaultspec_rag.embeddings` WARNING pair at 08:30:12.393/.605).
Sampled file completion rate decayed 1.907 → 1.237 → 0.798 → 0.442 → 0.231 files/s
over the following ~25 minutes (service `/jobs` `progress_rate_per_second`, five
samples). Tail slices sustained ~7.5 chunks/s against ~160 chunks/s early — a ~20x
chunk-throughput collapse. A comparable earlier code job (`21622f03`) finished in
519 s.

### The storage backend is exonerated: backpressure points at the encoder

A 20-sample py-spy profile of the consumer thread over ~40 s during the collapse:
17 samples in the dense forward, 2 in sparse encode, 1 in the qdrant upsert
(`src/vaultspec_rag/indexer/_streaming.py:1565`). The producer thread sat blocked in
the bounded queue's admission wait
(`src/vaultspec_rag/indexer/_chunk_producer.py:160`) in 20 of 20 samples — CPU
chunking out-produces the GPU encode stage, and the store is starved, not swamped.
The qdrant server process (v1.18.2, server mode) idled at ~4% CPU with ~1 write
op/s during encode, bursting to ~84% CPU only for its own asynchronous HNSW
indexing of already-acknowledged points; combined disk writes of the service and
qdrant processes stayed under 0.5 MB/s throughout. This rules out the previously
seen upsert-hammering degradation mode for this incident class.

### Root collision: count-based batching under ~500-600 MiB of headroom

The code encode path requests a fixed 32-item batch
(`embedding_code_encode_batch_size`, `src/vaultspec_rag/config/_settings.py:169`)
with per-item truncation at 8,000 chars ≈ 2,000 tokens
(`max_embed_chars`, `src/vaultspec_rag/config/_settings.py:146`;
`src/vaultspec_rag/embeddings.py:695`). Activation memory for a batch scales with
items × sequence length (attention quadratic in sequence length), so a count-based
batch has an unbounded token footprint: 32 near-cap code chunks demand an order of
magnitude more activation memory than 32 typical short chunks. During the incident
the resident stack (dense Qwen3 + sparse + reranker) held 12,383-12,589 MiB against
the derived absolute ceiling of 13,001 MiB (job record `cuda_ceiling_mb`; ceiling
semantics per the index-cuda-ceiling and index-cuda-shared-device ADRs), leaving
~500-600 MiB of working headroom. Short-chunk batches fit; the tail's long-chunk
batches did not. The tail is long-chunk-dense because paths index in lexical order
(`src/vaultspec_rag/indexer/_codebase_indexer.py:1110`) — slices near the end held
~490 chunks but completed only ~12 files each (~40 chunks/file) versus a ~12
chunks/file run average, so chunk length, not file count, is what changed at the
90% mark.

### The learned ceiling oscillates rather than converging

`EncodeBatchCeiling` (`src/vaultspec_rag/embeddings.py:114`) persists the
OOM-halved batch across calls and, after `RECOVERY_SUCCESSES = 16` consecutive
at-ceiling successes (`src/vaultspec_rag/embeddings.py:142`), probes double. Under
sustained pressure the recovery is the defect: the log shows a third OOM at
08:44:42 logged as a retry at batch 16 — meaning the call *started* at 32, i.e. the
ceiling had fully climbed back after the 08:30 clamp and re-collided. Each cycle of
climb-probe-OOM pays a discarded forward pass plus a `torch.cuda.empty_cache()`
(`src/vaultspec_rag/embeddings.py:722`), and the allocator then re-grows its
reserve. The ceiling is also regime-blind: it is keyed to nothing, so an OOM on a
long-sequence batch clamps subsequent short-sequence batches that would fit at 32.

### OOM retry granularity is the slice, so each OOM discards completed GPU work

The backoff ladder wraps the entire slice encode call
(`src/vaultspec_rag/embeddings.py:698-733`): `SentenceTransformer.encode` iterates
sub-batches internally, and an OOM on any sub-batch abandons every completed
sub-batch of a slice bounded at 512 chunks / 128 MiB
(`index_queue_max_chunks`, `src/vaultspec_rag/config/_settings.py:294`) and
re-encodes the full text list at the halved size. Observed tail slices carried
480-498 chunks, so a single mid-slice OOM discards minutes of GPU work. Slice
chunks are pre-sorted longest-first (`src/vaultspec_rag/indexer/_consumer_pipeline.py:544`),
which biases OOMs toward early sub-batches but does not bound the waste.

### At clamped batch sizes, per-batch overhead dominates and GPU load turns uneven

With the ceiling at 8, a ~490-chunk slice becomes ~61 micro-batches, each paying
tokenisation, host-to-device transfer, and Python dispatch: the single most common
py-spy top frame during the collapse was sentence-transformers' `batch_to_device`
(11 of 20 samples), and an in-slice tqdm trace decayed 6.80 → 3.76 it/s across a
57-batch slice. `nvidia-smi dmon` over one 20 s window showed ~7 s at 97-100% SM
followed by 11+ consecutive seconds at 0% while the job was mid-run — the GPU
starves in long stretches. Attribution of the zero-utilisation windows was not
completed (candidates: inter-slice upsert + checkpoint on the consumer thread,
CPU-side tokenisation between micro-batches, allocator re-growth after
`empty_cache`); the code path still runs its upsert inline on the GPU consumer
thread (`src/vaultspec_rag/indexer/_consumer_pipeline.py:591`), the writer-side
overlap decided in the index-throughput ADR Part C having targeted the vault and
document paths.

### The degradation verdict cannot see a throughput collapse

The index-observability ADR's verdict distinguishes starved/hung/backend-fault via
forward-entry recency — and worked as designed here: forwards were always recent,
so the job read `degradation: healthy` at 0.231 files/s, 12% of its own opening
rate. Progress advances only at slice boundaries when files' final segments commit
(`src/vaultspec_rag/indexer/_consumer_pipeline.py:619-629`), so a multi-minute
clamped slice is externally silent, and no surface reports the encode batch size,
OOM count, or a rate-vs-self-baseline signal. The OOM WARNINGs were the only
evidence trail, in an unstructured log.

### Remediation pathway space

- **A. Token-budgeted encode batching** (root fix): plan sub-batches by a token
  budget (items × padded length ≤ budget) instead of item count, sized from
  measured headroom. Makes activation memory approximately constant, removing the
  OOM class that drives the ladder; B and C become rare-path insurance. Slice
  chunks are already length-sorted (`_consumer_pipeline.py:544`), so bucketing is
  cheap. Cost: `SentenceTransformer.encode` owns its internal batching loop, so
  this needs either per-bucket encode calls with adapted `batch_size` or a custom
  loop over `tokenize`/`forward`; the index-observability ADR rejected
  sub-batching *as a progress heartbeat* over padding-efficiency concerns — a
  length-aware planner preserves length-grouping by construction, but the ADR's
  rejection scope must be reconciled, not silently overridden.
- **B. Sub-batch-scoped OOM retry**: move the backoff inside the sub-batch loop so
  an OOM discards at most one sub-batch instead of a ~490-chunk slice. Independent
  of A; requires the same custom-loop ownership as A, which argues for deciding
  them together.
- **C. Ceiling hysteresis or regime keying**: keep the learned ceiling but key it
  to a sequence-length band, or record the token footprint that OOM'd and clamp
  only batches exceeding it; alternatively slow recovery under repeated collision.
  Cheapest change; treats the symptom — throughput at clamped sizes remains
  overhead-dominated (batch 8 measured here), so it caps the loss rather than
  recovering it.
- **D. Headroom recovery**: the resident model stack consumes ~12.4 GiB of a 16
  GiB device; options include releasing or lazily loading the reranker during
  encode-bearing jobs and re-examining the flush-cadence caution recorded in the
  index-throughput ADR consequences. Raises the OOM threshold rather than removing
  the unbounded-footprint defect; interacts with search availability on the shared
  device.
- **E. Encode-stage observability**: publish batch size, ceiling state, OOM count,
  and intra-slice sub-batch progress through the existing jobs projection, and add
  a rate-vs-self-baseline degradation input so a 10x collapse stops reading
  `healthy`. Pure truth-surface work per the service-surface rule; prerequisite
  for measuring whatever A-D ships.

The evidence favors A as the root fix with B as its resilience complement (they
share the custom-loop cost), E as the measurement prerequisite, and C as the
fallback if the ADR rejects owning the encode loop. The ONNX O4 encoder backend
(accepted 2026-06-02, experimental opt-in, degrades to torch —
`src/vaultspec_rag/config/_settings.py:205`) changes encode economics and memory
profile wholesale and would need this same batching analysis re-run; it is not a
substitute for A-C. The ADR must settle: who owns the sub-batch loop (library or
this codebase), the token-budget derivation (static config vs headroom-derived),
the reconciliation with the observability ADR's sub-batching rejection, and
whether D is in scope for the same record.

### Not investigated

Attribution of the 11 s GPU-idle windows (job finished mid-measurement); whether
`sentence-transformers` exposes a supported length-bucketed or token-budget encode
path in the pinned version; sparse-encode ladder behaviour (same
`EncodeBatchCeiling` class, `src/vaultspec_rag/embeddings.py:529`, not observed
OOMing); Windows-specific allocator behaviour after `empty_cache`; whether
donor-reuse runs exhibit the same tail (this run replayed no reuse,
`committed_units: 0`).

## Sources

- `src/vaultspec_rag/embeddings.py:114` — `EncodeBatchCeiling`; `:142`
  `RECOVERY_SUCCESSES`; `:529` sparse instance; `:695` char truncation; `:698-733`
  whole-slice OOM ladder; `:722` `empty_cache` on OOM.
- `src/vaultspec_rag/indexer/_consumer_pipeline.py:544` — longest-first slice
  sort; `:591` inline encode+upsert on the consumer thread; `:619-629` slice-end
  progress accounting.
- `src/vaultspec_rag/indexer/_chunk_producer.py:160` — bounded-queue admission
  wait (producer-side backpressure).
- `src/vaultspec_rag/indexer/_streaming.py:1565` — synchronous slice upsert.
- `src/vaultspec_rag/indexer/_codebase_indexer.py:1110` — lexical path ordering.
- `src/vaultspec_rag/config/_settings.py:146,169,205,294` — `max_embed_chars`,
  code encode batch size, ONNX backend flag, slice bounds.
- Live incident telemetry, 2026-07-29: service job records for `474cb8b0` and
  `21622f03` (rates, `cuda_ceiling_mb`, forward block); service log OOM WARNINGs
  at 08:30:12.393, 08:30:12.605, 08:44:42.572; 20-sample py-spy profile and
  `nvidia-smi dmon` traces (session captures; job records re-fetchable via
  `vaultspec-rag server jobs`).
