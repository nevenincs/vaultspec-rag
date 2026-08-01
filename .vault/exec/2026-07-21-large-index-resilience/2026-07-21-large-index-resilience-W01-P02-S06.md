---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:4139de29d42cebbd90de77e4f3d96626269e03407150bf91219d1a3e66bcba4f'
step_id: 'S06'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Transfer sparse document outputs to CPU immediately after forward completion and narrow caller lock spans

## Scope

- `src/vaultspec_rag/embeddings.py`
- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Slice sparse document encoding into bounded inner batches.
- Hold `gpu_lock` for one Sentence Transformers encode call per batch.
- Transfer the returned dense tensor to CPU immediately after lock release.
- Convert, coalesce, and map sparse results entirely on CPU before releasing each batch.
- Separate dense and sparse forward lock spans at both production streaming boundaries.
- Preserve input ordering, query behavior, the finite OOM ladder, and lazy imports.

## Outcome

Sparse document outputs no longer accumulate on CUDA across a whole slice. Every bounded
batch leaves the accelerator immediately after its encode call, and CPU transfer, sparse
conversion, result mapping, progress checks, and storage work no longer extend the global
forward lock. The existing single-consumer design and public document API remain compatible.

## Notes

The first one-line revision used Sentence Transformers `save_to_cpu=True`. Although that
bounded CUDA retention, independent review found a Medium architecture violation because the
library performed the transfer inside the caller-owned `gpu_lock`. The final revision owns
inner batching explicitly, requests an accelerator-resident dense result, releases the lock,
and then transfers and sparse-converts on CPU. The Step scope was expanded minimally to the
two `_streaming.py` call boundaries required to remove the outer sparse lock.

Final review found no unresolved findings. A real cached Sentence Transformers 5.6.0 CUDA
probe returned ordered sparse document results and a valid unchanged sparse query result.
Ruff, formatting, ty, BasedPyright, compile, lazy-import, AST contract, and diff checks passed.
The pre-existing `_OOMSparseModel` reduced-signature double is intentionally unsupported and
now fails its legacy unit case; `S11` must remove it and replace the claimed coverage with the
planned real CUDA behavior rather than adding a production fallback, skip, or xfail.
