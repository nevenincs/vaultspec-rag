---
name: gpu-discipline
---

# GPU discipline

## Rule

- Load torch through the single centralised loader. Never import it directly on
  a compute path.
- Keep service call paths torch-free: MCP server, service client, CLI
  service-control commands.
- Provision the GPU build only. Never accept a CPU wheel silently.
- Run GPU encoding on exactly one dedicated consumer thread that owns the GPU
  lock.
- Never add a second GPU consumer thread. Never use CUDA streams to parallelise
  compute on one device. Never encode inline on the pool-draining thread.
- Hold the GPU lock across forward calls only. Tokenisation, pair assembly,
  tensor post-processing, score conversion and storage I/O go outside it.
- Do CPU-only work in index workers. Never initialise CUDA in one.
- Create the chunk worker pool with `spawn`.
- Keep every `torch` import function-local in every module a worker can reach.
- Bound and liveness-guard every wait that shuts the consumer down.

## Why

- This project is GPU-only and never runs inference on CPU.
- Two compute-bound kernels serialise on one device regardless of streams. The
  only real parallelism is CPU-produce against GPU-consume.
- There is one GPU lock per process. Every millisecond held beyond the forward
  pass serialises every root.
- A spawn worker re-imports its whole chain. A module-scope torch import there
  initialises CUDA in every worker and reintroduces the subprocess CUDA crash
  class.
- Indexing holds the writer lock. An unbounded wait turns one stalled call into
  a wedged indexer.
- A bare install resolves torch from the public index, because the GPU pin is
  workspace-scoped and absent from published wheel metadata.

## How

- Good: a compute site calls the loader and uses what it returns. The loader
  raises on a CPU-only build, an absent GPU, or absent torch, with one message.
- Good: read-only probes that must tolerate a torch-free host keep a guarded
  function-local import and report no CUDA rather than raising. Only exception.
- Good: one consumer thread drains a bounded queue and is the only code touching
  CUDA; shutdown sends its sentinel only while the thread is alive, with a timed
  put and a bounded join.
- Good: build reranker pairs and apply the character cap before the lock; call
  predict inside; convert scores after release.
- Good: a fresh-interpreter test asserts importing the worker leaves `torch` out
  of `sys.modules`.
- Bad: a module-scope `import torch`, or a fresh inline CUDA-availability check
  on a compute path.
- Bad: wrapping result mapping, densification or an upsert in the locked block.
- Bad: constructing an embedding model, calling `torch.cuda.*`, or opening the
  store inside a worker.
