---
tags:
  - '#adr'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - "[[2026-07-24-index-cuda-ceiling-research]]"
  - "[[2026-07-23-document-chunk-bounding-adr]]"
  - "[[2026-06-12-service-concurrency-adr]]"
---

# `index-cuda-ceiling` adr: `size the indexing CUDA ceiling to real device headroom and scope it per job` | (**status:** `proposed`)

## Problem Statement

Index jobs fail on `cuda_memory_ceiling` while the GPU is far from full, and the
failure cannot be cleared by the operator lever the error names. Grounded in
`2026-07-24-index-cuda-ceiling-research`: the ceiling is a hardcoded 12 GiB
profile constant that the config knob can only lower, it is enforced against a
process-wide allocation high-water shared across concurrent index jobs, the
resident models pre-consume ~3.5 GiB of it, and document embedding lacks a
dedicated encode sub-batch. A decision is needed now because the only thing
keeping the failing corpus indexing is a shared runtime env override that dies on
restart and slows every other index domain, so the service has no durable path to
indexing a document corpus.

## Considerations

- GPU forward passes are already serialised under one `gpu_lock`, so the true
  instantaneous demand is one forward plus the resident baseline, not the
  concurrent sum the process-wide high-water reports
  (`2026-07-24-index-cuda-ceiling-research`, `2026-06-12-service-concurrency-adr`).
- The ceiling is a safety mechanism against genuine device exhaustion; any
  loosening must leave a real backstop, and the `torch.cuda.OutOfMemoryError`
  adaptive backoff is that backstop.
- An operator-facing failure must be actionable in the direction it advises, per
  the spirit of `broker-facing-cli-outcomes-are-structured-and-idempotent`.
- The document-chunk-bounding work deferred two follow-ons this record now
  takes up: excluding the resident baseline, and deriving the ceiling from device
  capacity rather than a literal (`2026-07-23-document-chunk-bounding-adr`).
- The single dedicated GPU consumer thread and its lock discipline are fixed
  architecture and must not be reworked here.

## Considered options

Three independent axes; the record decides each.

Ceiling magnitude:

- **Derive the ceiling from real device capacity minus a headroom margin, and
  make the config knob authoritative (raise or lower).** A 16 GiB card gets a
  proportionate ceiling instead of a flat 12 GiB, and an operator can tune in
  either direction. Chosen.
- **Raise the hardcoded profile constant.** A one-line unblock, but re-freezes a
  device-independent literal that is wrong on the next card and preserves the
  one-way `min`. Rejected.
- **Remove ceiling enforcement, rely solely on the OOM backoff.** Simplest, but
  discards the pre-emptive guard that fails a job fast before it burns GPU on
  work that cannot fit, which the store-write-headroom philosophy values.
  Rejected.

Baseline treatment:

- **Exclude the resident-model baseline so the ceiling describes indexing
  headroom.** The budget then measures the work the job actually adds. Chosen.
- **Leave the baseline inside the ceiling.** Keeps the number simple but bakes a
  ~3.5 GiB permanent tax into a limit that reads as if it were all available to
  indexing. Rejected.

Per-job scoping:

- **Scope the peak measurement to the job by resetting and reading the allocation
  high-water inside the `gpu_lock` critical section that already serialises the
  forward.** Because the lock guarantees one forward at a time, a peak captured
  across the lock hold is that job's own demand, and no sibling can perturb it.
  Chosen.
- **Serialise index jobs so only one runs at a time.** Makes the process-wide
  reading per-job by construction, but discards the CPU-produce / GPU-consume
  concurrency the pipeline is built on and slows the common multi-domain
  reconcile. Rejected.
- **Give each concurrent job its own CUDA memory pool.** Torch's caching
  allocator is process-global; per-job pools are not a supported primitive
  without interfering with the single-consumer design. Rejected.

Document encode batch (compounding fix, not an axis of the core decision):

- **Add `embedding_document_encode_batch_size`, mirroring the code path, with a
  window-appropriate default.** Retires the shared-knob workaround. Chosen.

## Constraints

- The peak-measurement scope depends on the background memory-probe sampler
  thread not writing the same counters mid-critical-section; the research flags
  this as untested, so the implementation must confirm the lock-scoped reset and
  read are not raced by the sampler.
- Device-capacity query must tolerate a CPU-only or torch-absent host in the
  read-only probes that already run there, per
  `torch-loads-through-centralized-gpu-gate`; the ceiling derivation runs only on
  a real GPU compute path and must not force torch onto a service-client path.
- Chunking workers remain CPU-only; none of this may pull torch into a spawn
  worker (`index-workers-stay-cpu-only`).
- The `managed-service` and `embedded-local` profiles both encode a CUDA limit;
  the derivation must produce a sane value for the smaller-card `embedded-local`
  case, not only the 16 GiB development box.

## Implementation

The effective ceiling stops being `min(profile_constant, config_knob)` and
becomes a derivation from queried device capacity: total device memory minus a
reserved headroom margin, with the configuration value able to override in either
direction rather than only downward. The profile's CUDA figure becomes a floor or
a default rather than a hard cap. On a torch-absent or CPU-only host the compute
path that needs this value is not reached, so the derivation lives behind the
same GPU gate the encoders use.

The budget is constructed against indexing headroom rather than the whole device:
the resident-model baseline is sampled once after models load and subtracted, so
a job's ceiling is what indexing may add on top of the always-resident models,
matching the baseline contract the memory budget already documents.

Peak measurement moves inside the serialised critical section. The allocation
high-water is reset and read within the `gpu_lock` hold that already brackets the
forward, so the peak a job enforces against is the peak of its own forward, not a
since-reset maximum spanning sibling jobs. This removes the cross-job
contamination without serialising the jobs themselves - the producers still run
concurrently; only the GPU-touching measurement is lock-scoped, which it already
is for the forward it measures.

Document embedding gains `embedding_document_encode_batch_size`, defaulted low
enough for sequence-window-sized fragments and independent of the vault and code
sub-batches, so the runtime env workaround is retired and vault and code encoding
are no longer slowed by a document-driven reduction.

## Rationale

The knockout is that GPU forwards are already serialised
(`2026-07-24-index-cuda-ceiling-research`): once that is established, scoping the
measurement to the lock hold is strictly better than serialising the jobs,
because it removes the false contamination while keeping the concurrency the
pipeline was designed around. Serialising would pay real throughput to fix a
measurement artifact.

Deriving the ceiling from device capacity wins over raising the constant because
the constant is wrong the moment the hardware changes, and the live evidence -
a 12 GiB ceiling on a 16 GiB card failing jobs while 10 GiB sat free - is exactly
the device-independence bug a literal guarantees. Making the override
bidirectional restores the operator affordance the failure message already
promises.

Excluding the baseline and adding the document encode batch are lower-order but
follow the same principle: a job should be measured against, and sized for, the
work it genuinely adds.

## Consequences

Document corpora index on a durable configuration rather than a restart-fragile
env override, and a memory failure once again names work that genuinely demanded
the memory, restoring trust in the diagnostic. Operators on larger cards get
proportionate headroom, and the tuning knob works in the direction the error
advises.

The costs are real. Querying device capacity and subtracting a live baseline adds
two GPU-state reads to job admission, and a mis-derived headroom margin could
admit a genuine OOM - caught by the existing backoff, but as a slower failure than
a pre-emptive refusal. Lock-scoped peak measurement narrows the window in which
the background sampler may observe a transient, so metrics-side peak reporting may
read lower than before; that is a reporting change to note, not a regression.
Adding a fourth encode-batch knob grows the tuning surface, and the three
sub-batches (vault, code, document) will drift unless their defaults are chosen
against a shared rationale.

Two boundaries stay out of scope: the single-GPU-consumer and lock architecture
is unchanged, and search-path memory (the reranker cache) is not retimed here -
this record governs the indexing budget only.
