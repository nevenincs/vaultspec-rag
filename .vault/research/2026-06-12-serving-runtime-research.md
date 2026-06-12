---
tags:
  - '#research'
  - '#serving-runtime'
date: '2026-06-12'
related:
  - "[[2026-06-12-service-concurrency-research]]"
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-06-05-qdrant-performance-adr]]"
---

# `serving-runtime` research: `serving language and runtime boundaries`

Decision-grade investigation of whether Python is the right implementation language
for the resource- and memory-intensive multi-project serving layer, or whether C++ or
Rust would be materially better - and for which layer. Commissioned while the
service-concurrency rework's adversarial gate was in flight, grounded in that
feature's measured numbers, with web research on the 2026 state of Rust embedding
runtimes, Qdrant deployment modes, ASGI servers, and free-threaded CPython.

## Findings

### Executive verdict

No rewrite. The measured bottlenecks are not "Python the language" - they are one
pure-Python library engine (QdrantLocal) and lock topology, both of which already
have native or architectural fixes that preserve the entire torch/sentence-
transformers stack. The heavy compute (CUDA encode/rerank, tree-sitter C chunking)
is already native and measures at 100% GPU utilization during index embed after the
lock rework; the Starlette/asyncio serving layer costs single-digit milliseconds
against 400ms-180s compute/store phases. A Rust/C++ serving layer would optimize
~1% of request latency while forfeiting the only mature Windows-native consumer-GPU
model runtime that serves Qwen3-Embedding + SPLADE + bge-reranker today (torch).
The correct windmill is Qdrant server mode (the Rust engine, zero business-logic
change, already an accepted escape hatch) plus the in-flight lock-narrowing
decisions. A full rewrite rewrites the cheap layer, cannot rewrite the expensive
one, and breaks the uv/PyPI single-developer distribution story on Windows.

### Layer-by-layer attribution

- Model inference (Qwen3 dense + SPLADE + bge rerank): ~0.55s encode + ~0.095s
  rerank warm; ~17 min embed for 112k chunks; GPU at 100% during index embed.
  Python tax ~0% - kernels are CUDA via torch; Python launches them. Remaining
  costs (batch-of-one query encodes, sequential model calls) are fixable in Python.
- Vector store (QdrantLocal): 137s mean qdrant phase under concurrency on the
  6.3 GB corpus; 15+ GIL-pinned minutes for an O(N^2) paged scroll; ~20s linear
  SPLADE scan over ~114k chunks. High Python tax - but library-internal: a
  pure-Python brute-force engine with no HNSW, no sparse inverted index, no payload
  pushdown, single-threaded, not thread-safe. The same product in server mode is a
  Rust engine swapped via `VAULTSPEC_RAG_QDRANT_URL` with zero business-logic
  change. Even here the fix is "stop running the toy engine," not "rewrite in Rust."
- Chunking (tree-sitter): parsing is C; the GIL is sidestepped by the spawn process
  pool. Settled.
- HTTP/async serving (uvicorn/Starlette/anyio): single-digit ms per request. The
  real serving-layer bugs were topology (blocking loopback calls on the event loop,
  shared thread limiter, loop-thread blocking) - all fixed in Python this feature,
  and none preventable by a language change (a tokio service deadlocks on a
  synchronous loopback call just as thoroughly).
- Orchestration/locking: the GIL amplifies contention (one CPU-pinned Python thread
  starves all threads - observed), but the primary cause was lock granularity, now
  reworked. Once Qdrant is a server, the long GIL-pinning scans vanish and the
  remaining Python-side work is lock-bounded, not GIL-bounded.

### What a Rust/C++ rewrite would buy and cost

Buys: milliseconds off a path dominated by 400ms-137s phases; no-GIL orchestration
threads that are mostly waiting on the GPU or store anyway; tens of MB of memory
against GBs in CUDA weights. Costs: the model stack has no Windows-viable native
equivalent for this exact trio. TEI (HuggingFace's Rust embedding server) supports
Qwen3 embeddings, SPLADE pooling, and rerankers with Ada Lovelace CUDA, but is
Linux/Docker-first with documented Windows build failures. candle/fastembed/ort
paths hit the same ONNX export blockage already settled as upstream-blocked for
this project, with SPLADE + reranker + flash-attn fp16 parity unproven.
llama.cpp-style runtimes have no SPLADE and no CrossEncoder. A Rust service binary
also reintroduces the per-platform release engineering the project rejected when it
turned down TorchServe/Ray/BentoML.

### The hybrid path, assessed for this project on Windows

- Qdrant server mode: adopt next. Single `qdrant.exe` Windows binary, no Docker.
  Replaces the measured worst offender with Rust HNSW + inverted sparse index +
  payload pushdown + concurrent reads behind an env var that already exists. The
  store is already backend-aware (no point-operation locks in server mode).
  Operational cost - supervising one child process - is squarely within the
  service-supervision machinery on this branch.
- TEI / ONNX encode offload: do not adopt now. Wrong side of the Windows/packaging
  constraints, and the encode path is already GPU-saturated; the win it offers is
  mostly recoverable in-process via micro-batching.
- Granian (Rust ASGI server): keep deferred to beta as previously decided. Windows-
  supported drop-in, but buys nothing measurable while serving overhead is
  single-digit ms; its value is operational, and swapping it now would pollute the
  saturation-benchmark baselines.

### What comparable systems do

The industry boundary matches this project's shape: Python owns orchestration and
policy; native code owns engines behind process or FFI boundaries. Qdrant itself is
the canonical case (Rust server, thin Python client, pure-Python local mode
explicitly a dev convenience). vLLM/SGLang are Python schedulers over CUDA kernels.
LanceDB and Chroma are native storage engines with Python product surfaces. TEI
shows what an all-Rust embedding server costs: constrained model menu, Docker-first
operations.

### Free-threaded CPython trajectory

CPython 3.14 made free-threading officially supported (non-default) under PEP 779.
PyTorch ships experimental cp314t wheels from 2.10.0; tokenizers and safetensors -
both on sentence-transformers' critical path - still lack free-threaded support in
recent ecosystem surveys, and tree-sitter bindings are unaudited under no-GIL.
Realistic testing horizon is late 2026-2027. By then the GIL problem this project
measured will already be gone: the GIL-pinning offender is QdrantLocal's scans,
removed by server mode. Keeping free-threading on the deferred list is correct.

### Migration ladder

- Now (this feature): finish the accepted concurrency rework and re-measure against
  the frozen baselines. No language work.
- Next feature: promote Qdrant server mode to the recommended topology for
  multi-agent / large-corpus deployments - supervise `qdrant.exe` as a child
  process, ship the server-mode collection schema (HNSW params, fp16 vectors,
  scalar quantization, Matryoshka 512d evaluation), keep local mode as the
  zero-dependency small-corpus default. Flip criteria per root: corpus over
  ~500 MB-1 GB of search data, or more than 2 concurrent agents, or any measured
  qdrant phase over ~2s. The 6.3 GB corpus is far past the line.
- At beta: revisit Granian (measured against the saturation harness); begin local
  smoke testing on CPython 3.14t as torch/tokenizers support matures.
- At 1.0, only if criteria trigger: native encode offload (TEI under WSL2, or an
  ort sidecar) only if multiple processes must share GPU models or saturated encode
  remains the cap with the GPU at 100% - at which point the fix is hardware, not
  language. A Rust rewrite of business logic never appears on the ladder: no
  measured failure mode points at it.

### Decision criteria summary

Stay on the current rung until the saturation harness shows: qdrant phase
dominating p95 - next rung is server mode; encode dominating with GPU under 100% -
lock/batching work; encode dominating with GPU at 100% - hardware, not software;
serving overhead over 5% of p95 - only then does a native serving layer enter the
conversation.

### Sources

In-repo: the service-concurrency research and ADR (frozen baselines, lock
inventory, settled constraints) and the store/config server-mode seam.

Web (retrieved 2026-06-12):

- https://github.com/huggingface/text-embeddings-inference and its supported-models
  documentation; Windows build failures tracked in issue 728.
- https://qdrant.tech/documentation/installation/ and the qdrant Windows-binary
  discussion (orgs/qdrant/discussions/2772).
- https://github.com/pytorch/pytorch/issues/156856 (Python 3.14 support),
  https://py-free-threading.github.io/tracking/ , the Quansight free-threading
  one-year recap, and the CPython free-threading HOWTO.
- https://github.com/emmett-framework/granian benchmarks and independent
  Granian-vs-uvicorn comparisons.
- https://crates.io/crates/fastembed , https://github.com/StarlightSearch/EmbedAnything ,
  https://github.com/huggingface/candle , and the Qwen3-Embedding-0.6B model card.
