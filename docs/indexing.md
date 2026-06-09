# Indexing and retrieval architecture

This page describes how vaultspec-rag turns your vault documents and source
files into a searchable index and how each search query travels through the
pipeline to produce ranked results. It is aimed at operators who want to tune
performance, diagnose index health, or understand the trade-offs behind the
defaults.

## Overview

Every indexed item is stored as two complementary vectors in a local
[Qdrant](https://qdrant.tech) database:

- a **dense** vector (1 024 dimensions, float 32) that captures semantic
  meaning across a continuous space
- a **sparse** vector (SPLADE vocabulary weights) that captures term-level
  importance

At query time, both representations of the query are computed and the results
from each retrieval channel are merged by Reciprocal Rank Fusion (RRF) before
a CrossEncoder reranker refines the final ordering. A graph-aware score boost
applied after reranking promotes vault documents that are well-connected in the
wiki-link graph.

## Models

### Dense encoder — `Qwen/Qwen3-Embedding-0.6B`

The dense encoder is
[`Qwen/Qwen3-Embedding-0.6B`](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
loaded via `sentence-transformers` on CUDA in fp16. It produces 1 024-dimensional
L2-normalised embeddings.

- **Document encoding** calls `SentenceTransformer.encode` with no
  `prompt_name` (the model card confirms the empty string is correct for
  documents).
- **Query encoding** calls `SentenceTransformer.encode` with
  `prompt_name="query"`, which prepends the model's instruction prefix so the
  asymmetric query/document representation is used.
- Text is truncated to 8 000 characters before encoding and `max_seq_length`
  is capped at 2 048 tokens. This prevents the model from advertising its full
  32 k context window and avoids oversized attention buffers on variable-length
  corpora.
- If `flash_attn` is installed it is loaded as `flash_attention_2`; otherwise
  the model falls back to standard attention with no loss of correctness.
- An experimental ONNX backend (`VAULTSPEC_RAG_DENSE_BACKEND=onnx`) is
  available but opt-in. It requires `sentence-transformers[onnx-gpu]` in an
  onnxruntime-compatible CUDA environment and falls back silently to the torch
  backend on any load failure.

### Sparse encoder — `naver/splade-v3`

The sparse encoder is
[`naver/splade-v3`](https://huggingface.co/naver/splade-v3), a BERT-based
SPLADE model that maps text to a sparse vector over a ~30 k vocabulary.
It runs on CUDA in fp16 via `sentence-transformers.SparseEncoder`.

SPLADE uses asymmetric encode methods:

- `encode_document` is called for indexing
- `encode_query` is called for queries

The model's native `max_seq_length` of 512 tokens is not overridden; the
sparse path truncates internally and overriding it would cause a
position-embedding shape mismatch.

Sparse search can be disabled by setting `VAULTSPEC_RAG_SPARSE_ENABLED=0`
(config key `sparse_enabled`, default `true`). When disabled, hybrid search
falls back to dense-only retrieval.

### CrossEncoder reranker — `BAAI/bge-reranker-v2-m3`

The reranker is
[`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3)
loaded with `activation_fn=torch.nn.Sigmoid()` so scores lie in `[0, 1]`.
It is loaded lazily on first use and shared across all searcher instances to
avoid duplicate VRAM consumption (~560 MB).

The reranker receives a batch of `(query, snippet)` pairs and re-scores them.
Before sending results to the reranker the search pipeline fetches
`max(top_k × 4, 20)` candidates so there is enough material to re-rank.
Default `reranker_batch_size` is 32; the pipeline halves the batch size on
CUDA OOM and retries down to a minimum of 1.

Reranking can be disabled with `VAULTSPEC_RAG_RERANKER_ENABLED=0` (config key
`reranker_enabled`, default `true`). When disabled, results are returned
in RRF order.

## Vector store

The vector store is [Qdrant](https://qdrant.tech) running in **local embedded
mode** by default. Data lives at `.vault/data/search-data/qdrant/` relative to
the project root. Two collections are maintained:

- `vault_docs` — one point per indexed vault document
- `codebase_docs` — one point per source code chunk

Each point stores both a `dense` named vector (cosine similarity, 1 024-d)
and a `sparse` named vector (dot product, SPLADE). Payload indexes on
`doc_type`, `feature`, `date`, and `tags` (vault) and on `path`, `language`,
`function_name`, `class_name`, `node_type` (codebase) allow filtered search
without a full scan.

Optional scalar (INT8), turbo, or product quantization can be enabled with
`VAULTSPEC_RAG_QDRANT_QUANTIZATION` to reduce VRAM and disk at the cost of
some recall.

### Hybrid search with RRF

Every search call issues two Qdrant `Prefetch` sub-queries — one against the
`dense` named vector and one against the `sparse` named vector — each
retrieving `limit × 4` candidates. Metadata filters are applied to both
prefetches individually. The top-level query uses
`RrfQuery(Rrf(k=60))` to merge and re-score them. When the sparse vector is
absent (sparse disabled or zero-weight document) the pipeline falls back to
dense-only search automatically.

### Server mode

To route traffic through a running Qdrant server instead of the embedded
database, set:

```bash
export VAULTSPEC_RAG_QDRANT_URL=http://localhost:6333
export VAULTSPEC_RAG_QDRANT_API_KEY=your-api-key  # optional
```

Server mode removes the single-process local-file constraint and allows
multiple vaultspec-rag instances to share one Qdrant cluster.

## Indexing pipeline

### Vault document indexing

The vault indexer scans every `.md` file under `.vault/` using
`vaultspec_core.vaultcore.scan_vault`, extracts YAML frontmatter (type,
feature tag, date, related links), parses the H1 heading, and concatenates
the title and body as the embedding input.

Each file's content hash is stored in `index_meta.json` (default location:
`.vault/data/search-data/index_meta.json`). On the next run, files whose
blake2b hash is unchanged are skipped. A per-instance writer lock serialises
concurrent `full_index` and `incremental_index` calls so concurrent MCP, CLI,
and watcher triggers never race each other's metadata snapshots.

Encoding runs in configurable slices. Within each slice the dense and sparse
models encode the batch on GPU and the resulting vectors are upserted to Qdrant
before the next slice begins.

### Codebase indexing

The codebase indexer walks the project tree with `.gitignore`-aware pruning
plus an optional `.vaultragignore` file at the project root. It skips binary
files and files larger than 10 MB. Supported file types cover Python, Rust,
TypeScript/TSX, JavaScript/JSX, Go, Java, C/C++, C#, Ruby, shell, Kotlin, and
several data formats.

**Chunking.** For languages with a tree-sitter grammar, the AST chunker
extracts top-level declarations (functions, classes, implementations, traits,
etc.) as individual chunks. For formats without a grammar (YAML, TOML, JSON,
HTML, CSS, Markdown) a structure-aware `TextSplitter` is used instead.

**Process pool.** tree-sitter AST chunking is CPU-bound and holds the GIL for
both parse and traverse, so chunking runs in a `spawn`-based `ProcessPoolExecutor`.
Spawn workers import only the chunking modules and never initialise CUDA.
In auto mode (`index_chunk_workers=0`), the pool only activates when the total
source size exceeds 8 MiB (the measured serial/parallel crossover); below that
threshold or for a single worker, chunking runs in-process.

**Single GPU consumer thread.** Once chunks are ready they are fed through a
bounded `queue.Queue` to a single consumer thread that owns the GPU lock and
calls encode-and-upsert. There is no compute/compute overlap to exploit on one
GPU, and a second consumer thread would only serialise on the SMs and GIL
overhead. The consumer thread has a 300-second shutdown timeout; if it does not
terminate within that bound the run is aborted rather than hanging indefinitely
while holding the writer lock.

**Content-hash deduplication.** Each file's blake2b digest is persisted in
`code_index_meta.json`. On incremental runs, only files whose hash has changed
are re-chunked and re-embedded.

### Incremental vs rebuild

The default `vaultspec-rag index` run is incremental: it hashes every file,
skips unchanged ones, adds new chunks, and purges chunks for removed files.

`vaultspec-rag index --rebuild --type vault` (or `--type code`) drops and
recreates the target collection from scratch. Use this after schema changes
(e.g. a new embedding dimension) or after large-scale file restructures.
`--rebuild` requires an explicit `--type` to prevent accidentally wiping both
collections.

### Auto-reindex watcher

When the resident HTTP service is running, a `watchfiles`-based filesystem
watcher monitors `.vault/` for `.md` file changes and the project root for
source code changes. When changes are detected, the watcher triggers a scoped
incremental reindex for the affected files after a debounce window.

The watcher is on by default. Tuning knobs:

- `VAULTSPEC_RAG_WATCH_ENABLED=0` — disable entirely (pull-only service)
- `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS` — milliseconds to wait after the first
  change before triggering a reindex (default: 2000)
- `VAULTSPEC_RAG_WATCH_COOLDOWN_S` — minimum seconds between successive
  reindexes of the same source (default: 30)

Setting `debounce_ms` or `cooldown_s` to `0` means "no delay", not "disabled".

## Configuration knobs

The table below lists the knobs most relevant to indexing and retrieval
performance. Every row has an environment variable name and a default. All
values can also be set in the project config; the environment variable takes
priority over the config file.

| Environment variable                             | Default    | Purpose                                                       |
| ------------------------------------------------ | ---------- | ------------------------------------------------------------- |
| `VAULTSPEC_RAG_SPARSE_ENABLED`                   | `1` (true) | Enable SPLADE sparse channel; `0` falls back to dense-only    |
| `VAULTSPEC_RAG_RERANKER_ENABLED`                 | `1` (true) | Enable CrossEncoder reranking                                 |
| `VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE`             | `64`       | Slice size: documents encoded and upserted per Qdrant write   |
| `VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE`      | `8`        | Inner sub-batch for `SentenceTransformer.encode` (vault docs) |
| `VAULTSPEC_RAG_EMBEDDING_CODE_ENCODE_BATCH_SIZE` | `32`       | Inner encode sub-batch for codebase chunks                    |
| `VAULTSPEC_RAG_MAX_EMBED_CHARS`                  | `8000`     | Character truncation limit per document before encoding       |
| `VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH`         | `2048`     | Token cap on the dense model's sequence length                |
| `VAULTSPEC_RAG_INDEX_CHUNK_WORKERS`              | `0` (auto) | Chunk worker processes; `0` = auto, `1` = serial              |
| `VAULTSPEC_RAG_INDEX_PARALLEL_MIN_BYTES`         | `8388608`  | Auto-mode byte threshold before the process pool activates    |
| `VAULTSPEC_RAG_INDEX_CACHE_FLUSH_SLICES`         | `8`        | Flush the CUDA allocator every N codebase encode slices       |
| `VAULTSPEC_RAG_RERANKER_BATCH_SIZE`              | `32`       | CrossEncoder predict batch size (halved on CUDA OOM)          |
| `VAULTSPEC_RAG_QDRANT_URL`                       | _(local)_  | Qdrant server URL; unset uses local embedded mode             |
| `VAULTSPEC_RAG_QDRANT_QUANTIZATION`              | _(none)_   | Quantization: `scalar`, `turbo`, or `product`                 |
| `VAULTSPEC_RAG_WATCH_ENABLED`                    | `1` (true) | Watcher auto-reindex; `0` = pull-only service                 |
| `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS`                | `2000`     | Watcher debounce window in milliseconds                       |
| `VAULTSPEC_RAG_WATCH_COOLDOWN_S`                 | `30`       | Per-source reindex cooldown in seconds                        |
| `VAULTSPEC_RAG_DENSE_BACKEND`                    | `torch`    | Dense encoder backend; `onnx` is experimental and opt-in      |
