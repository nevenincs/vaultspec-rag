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
