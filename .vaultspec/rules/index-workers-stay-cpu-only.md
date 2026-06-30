---
name: index-workers-stay-cpu-only
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
