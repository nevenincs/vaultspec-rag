# Indexing and retrieval internals

This page explains how vaultspec-rag turns vault documents and source files
into a searchable index, and why each part of the retrieval path is shaped the
way it is. This page is for operators who want to understand the trade-offs
behind the defaults, tune performance, or diagnose index health. For the
commands that drive indexing and search, see the
[search and index guide](search-and-index.md). For the system-level picture,
see the [architecture overview](architecture.md).

## Overview

Every indexed item is stored as two complementary vectors in
[Qdrant](https://qdrant.tech):

- A **dense** vector (1024 dimensions, float32) captures semantic meaning in a
  continuous space, so a query matches conceptually related text even when the
  words differ.
- A **sparse** vector (SPLADE vocabulary weights) captures term-level
  importance, so exact and rare terms stay discriminative the way keyword search
  expects.

Dense retrieval is strong on paraphrase and weak on rare tokens; sparse
retrieval is the inverse. Keeping both is what lets one query satisfy both kinds
of intent.

At query time, both representations of the query are computed, and the results
from each channel are merged by reciprocal rank fusion. This is a rank-based
blend that rewards items ranked highly by either channel without needing the two
score scales to agree. A cross-encoder reranker then refines the final ordering.
A cross-encoder reads the query and a candidate together rather than comparing
precomputed vectors. For vault documents, a graph-aware score boost applied after
reranking promotes documents that are well-connected in the wiki-link graph.

## Models

vaultspec-rag loads three models on CUDA. Each one is paired below with the
reason its bounds and toggles are set the way they are; pure tuning numbers live
in the [configuration knobs](#configuration-knobs) table.

### Dense encoder - `Qwen/Qwen3-Embedding-0.6B`

The dense encoder is
[`Qwen/Qwen3-Embedding-0.6B`](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B),
loaded through `sentence-transformers` on CUDA in fp16. It produces
1024-dimensional, L2-normalised embeddings.

Documents and queries are encoded asymmetrically because the model was trained
that way. Document encoding calls `encode` with no prompt; query encoding calls
`encode` with the query prompt, which prepends the model's instruction prefix.
Using the matching representation on each side is what keeps query and document
vectors comparable.

Text is truncated to 8000 characters and the sequence length is capped at 2048
tokens before encoding. The cap is deliberate: it stops the model from
allocating its full 32k context window, which would inflate attention buffers
on a variable-length corpus and waste VRAM for no recall gain.

If `flash_attn` is installed, the model loads it as `flash_attention_2` for
faster attention; otherwise it falls back to standard attention with no loss of
correctness, so the dependency stays optional. An experimental ONNX backend
(`dense_backend=onnx`) exists for environments with a compatible onnxruntime
build, but it is opt-in and falls back to torch on any load failure - torch
remains the supported default.

### Sparse encoder - `naver/splade-v3`

The sparse encoder is
[`naver/splade-v3`](https://huggingface.co/naver/splade-v3), a BERT-based SPLADE
model that maps text to a sparse vector over its vocabulary. It runs on CUDA in
fp16 through `sentence-transformers`.

SPLADE is also asymmetric: `encode_document` runs for indexing and `encode_query`
runs for queries, mirroring the dense encoder's split for the same reason. The
model's native 512-token sequence length is left untouched - overriding it would
mismatch the model's position embeddings, so the sparse path truncates
internally instead.

The sparse channel can be turned off (`sparse_enabled=false`). When it is off,
hybrid search degrades to dense-only retrieval rather than failing, so a
dense-only deployment is a supported configuration, not a broken one.

### Reranker - `BAAI/bge-reranker-v2-m3`

The reranker is
[`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3),
loaded with a sigmoid activation so its scores lie in `[0, 1]` and read as
calibrated relevance rather than raw logits. It loads lazily on first use and is
shared across all searcher instances, because a second copy would duplicate
roughly 560 MB of VRAM for no benefit.

The reranker scores the full candidate content, bounded by the model's own
tokenizer at the 1024-token `reranker_max_length`, never a fixed-width display
snippet. Scoring real content is the point: a snippet would discard most of the
model's semantic capacity and bias ranking toward whatever happens to appear in
a candidate's opening characters. The reranker reads `(query, content)` pairs in
batches of 32; on CUDA out-of-memory it halves the batch and retries down to a
minimum of 1, so a momentary VRAM spike degrades throughput instead of aborting
the search. Reranking can be turned off (`reranker_enabled=false`), in which
case results are returned in fusion order.

## Vector store

The store keeps two collections, regardless of backend:

- `vault_docs` - one point per indexed vault document
- `codebase_docs` - one point per source-code chunk

Each point carries both a `dense` named vector (cosine similarity) and a
`sparse` named vector (dot product). Payload indexes - per-field indexes Qdrant
uses to filter without scanning every point - back the common filters: `doc_type`,
`feature`, `date`, and `tags` on vault documents; `path`, `language`,
`function_name`, `class_name`, and `node_type` on code chunks. A filtered search
hits the index instead of reading the whole collection.

### Hybrid search with fusion

Every search issues two Qdrant `Prefetch` sub-queries - one against the `dense`
vector and one against the `sparse` vector. Each retrieves four times the
requested limit so the fusion step has enough material to work with. Metadata
filters are applied to each prefetch individually, because a filter set only at
the top level would not constrain the sub-queries. The top-level query merges
the two channels with `RrfQuery(Rrf(k=60))`, the reciprocal rank fusion blend.
The sparse vector is sometimes absent - sparse disabled, or a document that
produced a zero-weight sparse vector. In that case the query falls back to
dense-only retrieval automatically.

### Backends and store-layer locking

The store runs against either the managed Qdrant server or the embedded on-disk
store, selected from `VAULTSPEC_RAG_QDRANT_URL`. When a URL is present it connects
to that server; otherwise it opens the embedded store. The daemon sets this
variable to its supervised child automatically, so server mode is the path you
get without configuring anything. The [backends guide](backends.md) covers
choosing between the two and operating the managed server.

Locking is backend-aware. The embedded store takes one reentrant lock per
collection plus a lifecycle lock for open, close, and collection create or drop,
because the collections are independent and a single store-wide mutex would
serialise unrelated searches. A second writer to the embedded store hits an
exclusive file lock and raises rather than corrupting the index. Server mode
takes no point-operation locks at all. The remote server handles its own
concurrency, so client-side locking there only caps throughput.

On a shared server, per-root namespacing keeps each project's collections apart:
a collection prefix derived from a short blake2b hash of the resolved project
path, applied only in server mode, so two roots indexed against one server never
collide. Optional vector quantization (`scalar`, `turbo`, or `product`) trades
some recall for lower VRAM and disk.

## Indexing pipeline

The pipeline is shaped around two hard constraints: tree-sitter holds the GIL
(global interpreter lock), and the project has one GPU. Each stage below exists to honour one of those.

The vault indexer scans every `.md` file under `.vault/` through core's
`scan_vault`, reads the frontmatter and H1 heading, and embeds the title and
body together. It records each file's blake2b content hash in `index_meta.json`,
so an unchanged file is skipped on the next run by comparing hashes alone. A
writer lock serialises concurrent `full_index` and `incremental_index` calls,
because MCP, CLI, and the automatic-update watcher can all trigger indexing at
once and must not race each other's metadata snapshots.

The codebase indexer walks the project tree with gitignore-aware pruning plus an
optional `.vaultragignore` file, and skips binary files and files larger than
10 MB - material that costs tokenizer time and adds no retrievable structure.
Where a tree-sitter grammar exists, an AST (abstract syntax tree) chunker splits
source into top-level declarations so a chunk is a function or class rather than
an arbitrary window;
formats without a grammar fall back to a structure-aware text splitter.

Chunking runs in a spawn-based, CPU-only process pool because tree-sitter holds
the GIL for both parse and traverse, so threads give no speedup - separate
processes do. The workers import only the chunking modules and never initialise
CUDA, which keeps the GPU free for encoding and avoids multi-second per-worker
startup. In auto mode the pool only activates once the total source size crosses
8 MiB, the measured point where parallelism starts to pay for its process
overhead; below that, chunking stays in-process.

Encoding runs on a single GPU consumer thread that owns the GPU lock and drains a
bounded queue the chunk producers refill. One thread is correct because a single
GPU has no compute-to-compute overlap to exploit - a second consumer would only
serialise on the streaming multiprocessors and GIL launch overhead. The real
parallelism is CPU-produce against GPU-consume, and that is exactly what the
queue captures. Each file's blake2b digest in `code_index_meta.json` lets
incremental runs re-chunk and re-embed only the files whose content changed.

### Incremental versus rebuild

Indexing is incremental by default: it hashes every file, skips the unchanged
ones, embeds new and modified content, and purges chunks for deleted files. This
is the right mode for everyday work - it touches only what moved and keeps the
GPU idle the rest of the time.

A rebuild drops and recreates the target collection from scratch. Reach for it
when incremental updates can't reconcile the index with reality: after a schema
change such as a new embedding dimension, or after a large-scale restructure
where content-hash bookkeeping no longer reflects the tree. A rebuild requires
naming the index type explicitly, so it can't wipe both collections by accident.
For the exact commands, see the [search and index guide](search-and-index.md).

When the resident service runs, a `watchfiles`-based watcher monitors `.vault/`
and tracked source and triggers a scoped incremental reindex for the changed
files after a debounce window. It is on by default; tune its timing rather than
disabling it when changes are noisy. See [automation](automation.md) for the
watcher in detail.

## Configuration knobs

A handful of knobs shape the chunking and encoding pipeline this page describes.
The [configuration reference](configuration.md) holds every variable with its
default and precedence; the ones specific to this pipeline are:

| Variable                                 | Controls                                                          |
| ---------------------------------------- | ---------------------------------------------------------------- |
| `VAULTSPEC_RAG_SPARSE_ENABLED`           | SPLADE sparse channel; off falls back to dense-only               |
| `VAULTSPEC_RAG_VAULT_CHUNK_CHARS`        | Character budget per vault chunk                                  |
| `VAULTSPEC_RAG_MAX_EMBED_CHARS`          | Character truncation limit per document before encoding           |
| `VAULTSPEC_RAG_INDEX_CHUNK_WORKERS`      | Chunk worker processes; auto-sizes by default, 1 forces serial    |
| `VAULTSPEC_RAG_INDEX_PARALLEL_MIN_BYTES` | Source-size threshold before the process pool activates           |
| `VAULTSPEC_RAG_RERANKER_MAX_LENGTH`      | Reranker token bound on candidate content                         |
| `VAULTSPEC_RAG_QDRANT_QUANTIZATION`      | Vector quantization: `scalar`, `turbo`, or `product`              |

For "my GPU is small" or "indexing is slow" tuning, see
[tuning for memory and speed](configuration.md#tuning-for-memory-and-speed).

## Where to go next

If indexing or retrieval behaves unexpectedly, the
[backends guide](backends.md) covers backend selection and the managed server,
and the [configuration reference](configuration.md) lists every knob. For more
help, see [support and help](../README.md#support-and-help).
