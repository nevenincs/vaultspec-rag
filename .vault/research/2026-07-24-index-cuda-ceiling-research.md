---
tags:
  - '#research'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - "[[2026-07-23-document-chunk-bounding-adr]]"
  - "[[2026-06-12-service-concurrency-adr]]"
---

# `index-cuda-ceiling` research: `the indexing CUDA ceiling is unraisable and charged process-wide across concurrent jobs`

On 2026-07-24 a redeployed service on current code still failed every document
and code index job for a hook-backed corpus with `cuda_memory_ceiling`, on a
16376 MiB GPU whose genuine in-use memory at the time was 6168 MiB. The
document-chunk-bounding work correctly moved enforcement onto allocated demand,
which surfaced - rather than caused - two structural defects in the ceiling
itself. First, the ceiling is a hardcoded profile constant clamped so no
operator lever can raise it, while the failure message directs the operator to
free headroom and resume - a remedy that has no raising lever to reach for.
Second, it is enforced against a process-wide
allocation high-water shared by concurrently running index jobs, so one job's
legitimate peak fails the others and a per-job reset clears a sibling's
measurement. A third, narrower gap compounds both: document embedding has no
dedicated encode sub-batch, so window-sized document chunks are encoded at a
batch tuned for much smaller vault chunks. The question this grounds is how the
ceiling should be sized, scoped, and overridden so that a job fails only on its
own genuine demand against real device headroom. The evidence favours making the
override authoritative, excluding the resident-model baseline from the indexing
budget, and giving documents their own encode sub-batch; whether concurrent
index jobs should share one budget or serialise is the open question the ADR
must settle.

## Findings

### The ceiling is a hardcoded profile constant that no operator lever can raise

The effective CUDA ceiling is `min(profile_limit, config.index_cuda_ceiling_mb)`
(`src/vaultspec_rag/job_dispatch.py:300`). The profile limit is the constant
`cuda_bytes = 12 * _GIB` for the `managed-service` profile
(`src/vaultspec_rag/index_profiles.py:158`, `:168`), and the only other profile,
`embedded-local`, is lower at `6 * _GIB` (`:184`, `:194`). Because the
configured value enters through `min`, the `VAULTSPEC_RAG_INDEX_CUDA_CEILING_MB`
knob can only ever lower the ceiling, never raise it above 12 GiB - verified live
on 2026-07-24 when setting it to 15000 was silently ignored and the failure
continued to name `12288.0 MiB`.

The same one-way clamp is duplicated at the two sites that build the budget that
actually enforces: `src/vaultspec_rag/indexer/_codebase_indexer.py:449` and
`src/vaultspec_rag/indexer/_document_indexer.py:422`. `job_dispatch.py:300` is
the admission-time copy; the per-run budgets each re-apply their own
`min(config.index_cuda_ceiling_mb, limits.cuda_bytes / mib)`. A fix that touches
only the dispatch site leaves the ceiling unraisable where it is enforced.

This is in direct tension with the operator guidance the failure itself emits:
the `cuda_memory_ceiling` job error tells the operator to "stop competing GPU
work or reduce the slice limit, then resume from the last checkpoint" - advice
that cannot be followed in the raising direction on a 16 GiB card where the
ceiling sits at 12 GiB with 4 GiB of unusable headroom. The
`broker-facing-cli-outcomes-are-structured-and-idempotent` rule's spirit - that
an operator-facing outcome be actionable - is not met here.

### The ceiling is enforced against a process-wide high-water shared by concurrent jobs

`MemoryBudget` enforces `peak_cuda_allocated_mb`
(`src/vaultspec_rag/memory_probe.py:498`), whose value derives from
`torch.cuda.max_memory_allocated()` (`memory_probe.py:154`). That reading is
process-global: it records the highest allocation reached anywhere in the
process since the last `reset_peak_memory_stats()`, not the demand of the job
holding the budget. The service runs vault, code, and document index jobs
concurrently, so every job's checkpoint reads a high-water that includes every
other job's peak.

The proof is direct. On 2026-07-24 a code index job failed at
`code producer queue wait` and a document index job failed on an `.xlsx`
`slice-0 after-dense-forward` reporting the byte-identical high-water
`12906.0 MiB` at the same instant; a later pair reported an identical
`12338.2 MiB`. Two jobs of different kinds cannot independently allocate the same
byte count - they are reading one shared counter. The per-job reset compounds
this: `reset_cuda_peak_memory_stats` (`memory_probe.py:167`) is process-wide, so
one job's reset clears a sibling's in-flight peak, and the sibling's next
forward re-establishes it under the wrong job's name.

Reducing the encode batch did not move the number: dropping
`embedding_encode_batch_size` from 32 to 12 changed the reported peak from
`12522.8 MiB` to `12522.0 MiB`, ~0.8 MiB, confirming the peak is not driven by
the failing job's batch but inherited from the process history.

### GPU forward passes are already serialised, so the true concurrent peak is bounded

The instantaneous GPU working set is not the sum of the concurrent jobs. One
process-global `gpu_lock` is created once on the service registry singleton and
handed to the searcher and all three indexers, so dense slice encode
(`src/vaultspec_rag/indexer/_streaming.py:316`), sparse encode
(`src/vaultspec_rag/embeddings.py:728`), and the reranker forward all acquire the
same instance - exactly one forward executes at a time, the single-GPU-consumer
discipline the `2026-06-12-service-concurrency-adr` established. Streaming drops
device tensors between forwards (`_streaming.py:321`), so the genuine
instantaneous demand is one forward plus the resident-model baseline, not three
concurrent forwards. The process-wide high-water overstates that demand because
it is a since-reset maximum spanning every job, while the thing that actually
risks device OOM is bounded by the lock.

A correct fix cannot simply move enforcement under the lock, because the budget's
own architecture forbids it: `MemoryBudget.sample()` "never acquires or accepts
the GPU lock" and must run outside the forward critical section
(`src/vaultspec_rag/memory_probe.py:236`). And the field failures occur at those
outside-the-lock checkpoints - the live `code producer queue wait` failure is a
`_sample_memory_budget` call at `_codebase_indexer.py:2378`, not a forward.
Re-scoping only the forward bracket would leave every enforcing checkpoint still
reading the process-global counter, so the contamination would persist exactly
where it was observed. What the serialisation buys is not a place to enforce but
a place to *capture*: a raw peak reset-and-read bracketed inside the lock hold
yields one job's own forward peak, which every checkpoint can then enforce
against instead of the shared global. The reset helper currently also flushes the
allocator cache (`memory_probe.py:182`), which is deliberate per-run behaviour
and throttled to every eighth slice (`index_cache_flush_slices`, `config.py:546`);
a per-forward capture must use a raw reset without that flush or it reintroduces a
device sync per slice.

The background memory sampler does not complicate this: it records RSS only
(`current_rss_mb`, `memory_probe.py:600`) and never reads or resets a CUDA
counter, so no sampler thread races the CUDA capture.

### The resident-model baseline consumes a third of the ceiling and is not excluded

The three resident models - dense, sparse, reranker - hold roughly 3.5 GiB of
CUDA memory permanently, measured as the freshly-loaded idle allocation on
2026-07-23. That baseline is counted inside the 12 GiB ceiling rather than added
above an indexing headroom, so the budget genuinely available to an indexing
forward is ~8.5 GiB, not 12. `MemoryBudget`'s contract already anticipates a
baseline - "A caller enforcing per-run headroom adds its admitted baseline
before constructing `MemoryBudget`" (`memory_probe.py:215`) - but the indexing
dispatch does not subtract the resident baseline, so a window-sized forward that
is entirely reasonable on an 8.5 GiB working budget is measured against a ceiling
already 3.5 GiB pre-consumed. Excluding the resident baseline so the ceiling
describes indexing headroom is one of the open follow-ons the
`2026-07-23-document-chunk-bounding-adr` explicitly deferred.

Two subtleties bound how the baseline can be used. First, a peak read after a
`reset_peak_memory_stats` is absolute - the reset rebases to the current
allocation, which already includes the ~3.5 GiB resident models
(`memory_probe.py:182`) - so a captured peak is total device use, not the job's
delta. Subtracting the baseline from the ceiling while enforcing an absolute peak
would double-count the models and re-tighten the ceiling by ~3.5 GiB. The two
sides must match: either enforce `peak - baseline` against `capacity - headroom - baseline`, or enforce absolute `peak` against `capacity - headroom`. Second, the
resident baseline is not fully present until every model is resident, and the
CrossEncoder reranker loads lazily under a separate `_reranker_lock` rather than
`gpu_lock`; a baseline sampled before that lazy load understates the true
resident set, and a reranker load landing inside a job's capture bracket inflates
that job's peak by the model's size. The baseline must be pinned to after all
resident models load, and model loading is the one residual perturbation the
`gpu_lock` capture does not itself exclude.

### Document embedding has no dedicated encode sub-batch

Code embedding carries its own `embedding_code_encode_batch_size` (32),
justified in config comments by code chunks being short and length-sorted
(`src/vaultspec_rag/config.py:545`). Vault embedding uses
`embedding_encode_batch_size` (32), justified by vault chunks being heading-aware
and capped near 750 BPE tokens (`config.py:521`). Document embedding has no
equivalent knob and falls through to the generic vault value. After
document-chunk-bounding, document fragments are bounded at the model's full
sequence window (~2048 tokens, roughly 2.7x the vault chunk's token volume), so
32 window-sized fragments per forward is materially more activation memory than
the batch of 32 was ever sized for. The live evidence: lowering both encode
batches to 8 was the runtime change that let the failing corpus index without
tripping the ceiling on 2026-07-24. That workaround lives only in the daemon's
inherited environment and does not survive a restart, and it slows vault and
code encoding too because the knob is shared across all three.

### Option space

The evidence separates three fixes that compose rather than compete.

- **Make the override authoritative** rather than a one-way `min`. Either let
  `index_cuda_ceiling_mb` raise as well as lower, or derive the ceiling from
  real device capacity minus a headroom margin so a 16 GiB card is not pinned at
  12 GiB. The trade is that a too-high ceiling admits a genuine device OOM; the
  existing `torch.cuda.OutOfMemoryError` backoff (`embeddings.py`) is the real
  safety net the ceiling currently preempts.
- **Give documents their own encode sub-batch** (`embedding_document_encode_batch_size`),
  mirroring the code path, defaulting low enough for window-sized fragments. This
  is the smallest change and directly retires the shared-knob workaround, but it
  does not by itself fix the cross-job contamination.
- **Scope the peak measurement to the job**, by resetting and reading the
  high-water under the same `gpu_lock` critical section that already serialises
  the forward, or by giving concurrent index jobs one shared budget rather than
  three independent process-wide readings. This is the deepest change and the one
  the ADR must decide, because it interacts with whether index jobs should run
  concurrently at all.

The substantive question for the ADR is the third: whether to serialise index
jobs so the process-wide reading becomes per-job by construction, or to keep
concurrency and make the measurement lock-scoped. Excluding the resident baseline
and adding the document encode batch are lower-risk and can land independently.

### Not investigated

The exact token-length distribution of the failing corpus's fragments was not
measured; the 2.7x figure is derived from the character bound, not tokenised.
Whether the `embedded-local` 6 GiB profile has the same unraisable-ceiling
problem on smaller cards was not exercised. Whether a slice of many forwards ever
peaks above one forward plus baseline - which would make per-forward capture
under-measure - was reasoned to be unlikely from the between-forward tensor
release but not measured; a job must in any case enforce the maximum across its
own captured brackets, not a single one.

## Sources

- `src/vaultspec_rag/job_dispatch.py:300`
- `src/vaultspec_rag/indexer/_codebase_indexer.py:449`, `:2378`
- `src/vaultspec_rag/indexer/_document_indexer.py:422`
- `src/vaultspec_rag/index_profiles.py:158`, `:168`, `:184`, `:194`
- `src/vaultspec_rag/memory_probe.py:154`, `:167`, `:182`, `:215`, `:236`, `:498`, `:600`
- `src/vaultspec_rag/embeddings.py:728`
- `src/vaultspec_rag/indexer/_streaming.py:316`, `:321`
- `src/vaultspec_rag/config.py:521`, `:545`, `:546`
- Live service `/metrics`, `server jobs`, and daemon log readings, 2026-07-23
  and 2026-07-24 (observational; not reproducible from this repository)
