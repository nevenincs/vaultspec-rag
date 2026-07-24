---
tags:
  - '#research'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
related: []
---

# `worktree-index-reuse` research: `worktree fork index reuse`

A new git worktree forked from an already-indexed branch recomputes every embedding on the GPU from scratch, turning a near-instant fork into an hour-class rebuild. This research grounds why that happens, surveys production reuse patterns, frames four candidate directions, and reports three spikes run on this box that settle the correctness and throughput questions. The evidence converges on exact-content-keyed reuse at the encode seam (reuse-by-point-id) as the option the ADR must settle; git-based divergence detection is evidenced as unsound.

## Findings

### Why a fork recomputes: namespace is path-keyed, point identity is content-keyed

The server-mode namespace is a blake2b hash of the normcased, resolved root PATH - `root_collection_prefix` returns `r{12hex}_` (`src/vaultspec_rag/_store_models.py:143-173`); all three collections (`vault_docs`, `codebase_docs`, `document_docs`) take the prefix (`src/vaultspec_rag/store_schema.py:62-113`), and the prefix-to-root manifest records the mapping for lifecycle classification (`src/vaultspec_rag/storage_manifest.py:1-26`). A new worktree is a new path, hence a new prefix, hence three empty collections, hence a full GPU rebuild. Nothing consults a sibling namespace.

Point identity, by contrast, is already exact-content-addressed and prefix-independent: a code chunk id is `{rel_path}:{ordinal}:{line_span}:{blake2b(content)}` (`src/vaultspec_rag/indexer/_chunk_worker.py:1310-1332` and `1367-1385`); the document scheme is `blake2b(normalized_source|locator_or_unit_ordinal|content_fingerprint)@v1` (`src/vaultspec_rag/store_schema.py:99-104`); the Qdrant point id is a deterministic sha256-to-63-bit integer of the string id (`src/vaultspec_rag/store.py:1664-1678`); payloads carry root-relative paths only. A byte-identical worktree therefore yields byte-identical point ids AND vectors in a differently-named collection. The GPU recompute is pure waste by construction.

### The encode seam is single and clean

All three slice paths (vault, code, document) funnel through `_encode_slice_vector_fields` (`src/vaultspec_rag/indexer/_streaming.py:299-350`): dense forward under `gpu_lock`, CPU transfer and sparse conversion outside it, vectors landing as plain lists on the chunk dataclasses before upsert. A per-batch resolve-before-encode hook slots in exactly there without touching any GPU rule (single consumer thread, lock wraps forwards only, chunk workers stay CPU-only and torch-lazy).

### Machinery a reuse key must fold in

Per-file blake2b digests drive incremental diffing via the meta sidecar (`src/vaultspec_rag/indexer/_code_meta.py:1-45`); config epochs stamp reserved sidecar keys, with the CONTENT epoch (preprocess invocation surface, `html_strip`, emitted-byte cap; `src/vaultspec_rag/indexer/_config_epoch.py:336-374`) invalidating vectors for unchanged bytes on chunking-config drift. Embedding model identity and dims: `DEFAULT_DENSE_DIM = 1024` for Qwen3-Embedding-0.6B, with the effective dimension config-driven (`src/vaultspec_rag/store_schema.py:77-80`). Any reuse decision must be gated on content epoch + model identity (including revision) + dims, or a stale well-formed vector is served - silent ranking degradation, the same failure class as scoring display snippets instead of content.

### Production patterns, and why the uv mechanism does not transfer

uv reconstructs venvs by hardlink/reflink from a file-per-artifact content-addressed cache (https://docs.astral.sh/uv/concepts/cache/). Qdrant vectors live inside collection segment files, not per-item objects: there is nothing to link, so any "reconstruction" pays a full upsert. Only the abstract lesson transfers: key reuse by content identity, recompute only misses. Hash-to-vector reuse is standard practice elsewhere: LangChain CacheBackedEmbeddings, LlamaIndex ingestion docstore upsert strategies (https://docs.llamaindex.ai/en/stable/examples/ingestion/document_management_pipeline/), Sourcegraph commit-delta incremental embeddings (https://docs.sourcegraph.com/cody/core-concepts/embeddings). Qdrant's own multitenancy guidance (https://qdrant.tech/documentation/manage-data/multitenancy/) recommends one collection per model with payload-partitioned tenants - relevant only to the deferred storage-dedup question. Bulk namespace copy reality: `init_from` is deprecated upstream and stripped by the embedded local backend (installed `qdrant_client/local/qdrant_local.py:95-112`); snapshots are server-only; the backend-neutral copy path is scroll-with-vectors then upsert.

### Spike 1 (run 2026-07-24): git identity is NOT byte identity

A fresh `git worktree add` of this repo's exact HEAD - `git status` clean, `git diff` empty, both 0.17 s - left 96 of 2,396 tracked files byte-DIFFERENT on disk (CRLF in the long-lived worktree vs LF in the fresh checkout; git's clean-filter normalization hides it); 2,300 byte-identical, 0 missing. Two refinements: the chunker normalizes newlines before hashing (`src/vaultspec_rag/indexer/_chunk_worker.py:391-402`), so chunk hashes, point ids, and vectors are identical across that CRLF pair - chunk-level identity is CRLF-immune; the raw-byte file-digest layer does differ on those 96 files, costing a cheap CPU re-chunk (digesting both full trees took 0.9 s), zero GPU. Git-based detection has further holes with no rescue: dirty trees, untracked/ignored-but-indexed files, preprocess-hook outputs (not in git), submodules, symlinks, LFS pointers, non-git roots. The existing blake2b digest layer subsumes git detection entirely - it hashes the actual bytes the indexer reads, post-smudge, post-preprocess. Git detection is at best a speed hint for a roughly 1-9 s stage, at worst a false-"same" source.

### Spikes 2-3 (run 2026-07-24, read-only against the live server): lookup throughput is a non-issue

Scroll-with-vectors over a green 4,813-point codebase collection: 2,438 pts/s (full-collection read approximately 2 s). Retrieve-by-id with vectors, 1,024 ids in 256-batches: 2,345 pts/s. Combined with real job history on this box (rebuild-class index jobs 2,935-4,495 s) and the prior measurement that chunking 112k chunks costs about 9 s while encode costs about 1,002 s (encode dominates roughly 100x), reuse turns an hour-class fork rebuild into roughly chunk-time + lookup + upsert - a 2-3 order-of-magnitude reduction. The read path is fast enough per-batch inside the consumer loop; GPU encode is confirmed as the dominating cost worth eliminating.

### Candidate directions

- A, namespace clone: donor-match heuristic then scroll-and-upsert wholesale. Smallest change, but the decision to clone is a corpus-level similarity judgment; donor-only stale points and donor meta must be reconciled. Medium risk.
- B, durable KV hash-to-vector cache: exact-content by construction, but a third on-disk copy of every vector (dense 4 KB + sparse roughly 1-4 KB per chunk, about 0.7-0.9 GB for this repo's 112k-chunk corpus before DB overhead), a new machine-global lifecycle surface outside manifest/survey/prune with no root attribution (the `unknown` class automated destruction must never auto-touch), and the full key-completeness hazard.
- C-prime, payload-partitioned shared collections (root-as-tenant): true dedup and payload-only forks, but falsifies the 1:1 prefix-to-root invariant the entire safety surface is built on (`src/vaultspec_rag/storage_ops.py` per-prefix delete guards and autoprune grace clocks), inverts grace semantics to per-membership refcounts, degrades local mode (payload filters unindexed there), and re-concentrates all roots' writes on one collection set against the lock-split lesson. A separate storage-dedup decision, not a GPU fix.
- Reuse-by-point-id (encode-seam read-through): before encoding a batch, retrieve-by-id with vectors from sibling donor namespaces, verify fetched payload content equals expected chunk content, adopt dense+sparse on a hit, GPU-encode misses, upsert into the root's own namespace as today. Exact AND verified; no corpus similarity judgment exists anywhere; donor selection affects only hit rate, never correctness; zero new on-disk state, so no GC, no autoprune extension, no lifecycle surface. Two independent analyses (spike-driven derivation and an adversarial review grounded in the project safety rules) converged on this option.

Under per-chunk exact keying no worktree-identity guarantee is ever needed: divergent content cannot be reused (it misses), identical content is verified before reuse, and the mechanism benefits any pair of roots with overlapping content - worktrees are simply the highest-hit-rate case (the live manifest holds 16 roots including two real worktree families).

### Not investigated

Fresh-namespace upsert + prealloc wall-time for a full corpus (the tax no encode-reuse option removes) - the proposed decision-settler prototype spike measures it; payload-bulk-update throughput; Qdrant tiered-multitenancy applicability to the pinned 1.18.2 server (moot while C-prime is deferred); vault-collection doc-stem-keyed specifics beyond scheme review.

## Sources

- `src/vaultspec_rag/_store_models.py:143-173` - path-keyed `r{12hex}_` prefix (re-verified 2026-07-24)
- `src/vaultspec_rag/store_schema.py:62-113` - collections, dims default, point-id schemes, segment geometry
- `src/vaultspec_rag/storage_manifest.py:1-26` - prefix-to-root manifest contract
- `src/vaultspec_rag/indexer/_chunk_worker.py:1310-1332,1367-1385,391-402` - chunk id construction, newline normalization
- `src/vaultspec_rag/store.py:1664-1678` - `_stable_id` sha256-to-63-bit point id
- `src/vaultspec_rag/indexer/_streaming.py:299-350` - the single encode seam
- `src/vaultspec_rag/indexer/_config_epoch.py:336-374` - content epoch knobs
- `src/vaultspec_rag/indexer/_code_meta.py:1-45` - digest sidecar + reserved epoch keys
- installed `qdrant_client/local/qdrant_local.py:95-112` - local backend strips `init_from`
- https://docs.astral.sh/uv/concepts/cache/
- https://qdrant.tech/documentation/manage-data/multitenancy/
- https://qdrant.tech/articles/multitenancy/
- https://docs.llamaindex.ai/en/stable/examples/ingestion/document_management_pipeline/
- https://docs.sourcegraph.com/cody/core-concepts/embeddings
- https://cursor.com/blog/secure-codebase-indexing
- Spikes 1-3 run 2026-07-24 on this box (throwaway worktree removed; all vector-store interactions read-only); numbers recorded above.
