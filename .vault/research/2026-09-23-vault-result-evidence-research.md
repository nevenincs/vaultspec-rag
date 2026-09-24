---
tags:
  - '#research'
  - '#vault-result-evidence'
date: '2026-09-23'
modified: '2026-09-24'
body_schema: 'body-v2'
body_hash: 'sha256:c577bdc03781e3bb900648ec1ce77195543c35c63da93963587d7234427a8337'
related:
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-06-26-storage-schema-contract-adr]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - "[[2026-03-06-gpu-only-rag-stack-adr]]"
---

# `vault-result-evidence` research: `passage evidence, locators and reranker cost in vault results`

Question: why do vault search hits rank the right record but fail to show or locate the
answer (GitHub issue #531), and which fixes restore answerable, locatable results without
regressing ranking or latency? Stakes: agents consume the snippet under a context budget;
a hit that names the right file but not the passage forces a full re-read. Conclusion from
the evidence below: three separable defects compound. The snippet is the first 200
characters of the winning chunk. No vault chunk stores a line span or heading. The
winning chunk itself misses the evidence in about a third of cases. A fourth,
independent defect dominates latency: the CrossEncoder runs in fp32 and takes about 95%
of a vault search.

## Findings

### The snippet is the chunk head; the accepted "matched passage" design never shipped

- Every vault hit's snippet is `content[:200].strip()` of the best chunk
  (`src/vaultspec_rag/search/_searcher.py:638`). Code and document hits use the same cut
  (`src/vaultspec_rag/search/_result_shaping.py:236`, `:301`).
- `group_chunks_by_document` documents the snippet as "the matched passage"
  (`src/vaultspec_rag/search/_result_shaping.py:117-119`); that is untrue of the code.
- `2026-06-12-service-concurrency-adr` D7 decided "snippet from the matched chunk, not
  the doc head", and D8 decided vault chunks embed `title + heading-path + chunk text`.
  The embed input is `f"{chunk.title}\n\n{chunk.text}"`
  (`src/vaultspec_rag/indexer/_streaming.py:584`). No heading path is computed anywhere
  in the vault path.

### Vault chunks carry no locator, although one is computable at index time

- `split_document` runs the markdown `TextSplitter` with zero overlap
  (`src/vaultspec_rag/indexer/_vault_prep.py:186-231`). `_merge_splits` keeps every
  separator, so chunks are contiguous verbatim substrings of the body
  (`src/vaultspec_rag/indexer/_chunking.py:111-139`).
- The body is frontmatter-stripped and `.strip()`ed before splitting
  (`src/vaultspec_rag/indexer/_vault_prep.py:390`, `:430`). File line numbers therefore
  need the body's starting line.
- The code path already locates splitter chunks verbatim and counts lines
  (`src/vaultspec_rag/indexer/_chunk_worker.py:1447-1496`). A chunk that begins with its
  separator starts with `\n`, so that routine reports the blank line before the chunk's
  first text line. This was found by reading the code and was not measured.
- The chunk payload has no span or heading field (`src/vaultspec_rag/store_schema.py:146-166`,
  `src/vaultspec_rag/_store_models.py:461-484`). Additive payload fields do not bump
  `STORAGE_SCHEMA_VERSION` (`2026-06-26-storage-schema-contract-adr` D1,
  `src/vaultspec_rag/store_schema.py:62-69`).
- The HTTP result model already has `line_start`, `line_end` and `section`
  (`src/vaultspec_rag/server/_models.py:28-94`). `SearchResult` has no `section`
  (`src/vaultspec_rag/search/_models.py:92-113`), so vault and code hits serialize it as
  null.
- A breadcrumb format for `section` already exists for document hits: `Finance > Q3`
  (`docs/preprocessing-hooks.md:183`).

### Reproduction on the live service

- Service from this worktree, release 0.4.35, RTX 4080 SUPER, against the vaultspec-core
  vault the issue measured (820 records).
- For the issue's query "why was an idle timeout rejected for orphaned stdio servers",
  `2026-07-16-mcp-stdio-lifetime-adr` ranks first. Its snippet opens with the first
  considered option, not the idle-timeout option, and `line_start`/`section` are null.
- The issue's stored scores (`typesafe-search-eval/results/rag*.score.json`):
  - hit@1 0.81 (dev, 21 answerable) and 0.72 (held-out, 18).
  - Gold evidence inside the snippet: 0/21 and 1/18.
  - A BM25 block-excerpt baseline on the same cases reaches 0.52 and 0.61.

### Passage selection inside the winning chunk saturates at that chunk's ceiling

Method (`proto_passages.py`, scratch):

- Re-ran the issue's 39 answerable cases through the service and rebuilt each top gold
  hit's chunks with the product splitter.
- Identified the winning chunk with `BAAI/bge-reranker-v2-m3`. It matched the service's
  snippet in 37/37 cases, so the replica is faithful.
- Split the chunk into fence-aware, heading-tracked paragraph passages: list items split
  out when oversized, small neighbours merged.

| Strategy (gold evidence in chosen passage)           | dev (n=20) | held-out (n=17) |
| ---------------------------------------------------- | ---------- | --------------- |
| Current snippet                                      | 0          | 1               |
| Winning chunk contains the evidence (ceiling)        | 14         | 11              |
| CrossEncoder, passage alone, cap 800 / 1400          | 13 / 13    | 8 / 9           |
| CrossEncoder, heading path + passage, cap 800 / 1400 | 13 / 13    | 8 / 9           |
| CrossEncoder, best two passages, cap 1400            | 14         | 11              |
| BM25 over the chunk's passages, cap 1400             | 13         | 8               |
| Section of the chosen passage matches gold, cap 1400 | 13         | 10              |

- Prefixing the heading path to the passage changed no pick.
- The cap mattered on one held-out case.
- BM25 trails the CrossEncoder by one case on held-out and needs no GPU.

### The winning chunk misses the evidence in about a third of cases; its runner-up sibling recovers most

Method (`proto_doc.py`, scratch): scored every chunk of the gold record with the
CrossEncoder, then selected passages within the top-N chunks by chunk score, cap 1200.

| Measure                                            | dev (n=20) | held-out (n=17) |
| -------------------------------------------------- | ---------- | --------------- |
| Evidence anywhere in the record                    | 20         | 17              |
| Evidence in the top-1 chunk / top-2 chunks         | 14 / 19    | 11 / 14         |
| Chosen passage holds evidence: within top-1 chunk  | 13         | 9               |
| Chosen passage holds evidence: within top-2 chunks | 15         | 11              |
| Chosen passage holds evidence: within top-3 chunks | 15         | 11              |
| Chosen passage holds evidence: whole record        | 14         | 10              |

- Whole-record selection is worse than top-2. More passages add distractors, and the
  chunk-level score is an informative prior.
- MaxP ranking (chunk score = best passage score) would pick a different chunk than the
  chunk reranker in 5/20 and 4/17 cases. Its effect on document ranking was not measured.
- Caveat: "top-2" here ranks all of the record's chunks. The product reranks only chunks
  inside its candidate window, which is `max(top_k * 4, 20)` chunks across all records
  (`src/vaultspec_rag/search/_searcher.py:694-696`). How often the evidence-bearing
  sibling falls outside that window was not measured.

### The reranker runs in fp32 and dominates search latency; fp16 is about 3x faster in service with identical rankings

- Service timing for a 10-result vault search: `rerank_seconds` 1.089 of
  `server_total_seconds` 1.140.
- The CrossEncoder is built without a dtype (`src/vaultspec_rag/search/_searcher.py:429-435`).
  The dense and sparse encoders load in fp16 (`src/vaultspec_rag/embeddings.py:693`, `:829`),
  as `2026-03-06-gpu-only-rag-stack-adr` specifies for the stack.
- `proto_fp16.py` (scratch): 39 cases, 40 real chunk pairs each, batch 32.

| Precision | mean ms / 40 pairs | top-1 doc agrees with fp32 | top-1 chunk agrees | gold hit@1 | gold MRR | max abs score delta |
| --------- | ------------------ | -------------------------- | ------------------ | ---------- | -------- | ------------------- |
| fp32      | 2166               | -                          | -                  | 22/39      | 0.719    | -                   |
| fp16      | 326                | 39/39                      | 39/39              | 22/39      | 0.719    | 0.0019              |
| bf16      | 325                | 39/39                      | 39/39              | 22/39      | 0.719    | 0.0255              |

- The scratch timings ran beside the live service on the same GPU, and the contention
  inflated fp32 more than fp16, so the scratch ratio (6.6x) overstates the gain.
- Measured in the service after loading the reranker in fp16 (commit `bd825c2f` plus the
  constructor change), same host, corpus and three queries, nine runs:
  - median `rerank_seconds` fell from 1.089 to 0.367 (about 3.0x);
  - median `server_total_seconds` fell from 1.140 to 0.43.
- Passage scoring cost about 21 ms per record in fp32 (~5 passages). At fp16 it falls to
  about 1-2 ms per passage pair.

### Existing indexes are not migrated automatically

- Nothing repopulates new per-chunk payload fields on unchanged documents. A GPU-free
  payload rewrite exists (`src/vaultspec_rag/indexer/_vault_incremental.py:419-452`,
  `src/vaultspec_rag/store_ingest.py:221-270`). It fires only when a document's
  metadata digest moves, and the stat-gate sidecar returns cached fingerprints for
  unchanged files.
- `vault_content_epoch` hashes only `vault_chunk_chars` and escalates a mismatch to a
  clean rebuild (`src/vaultspec_rag/indexer/_config_epoch.py:448-454`). Splitter or
  embed-input changes have no identity there.
- Bumping `VAULT_POINT_SCHEMA` (`src/vaultspec_rag/indexer/_index_schema.py:7`) makes the
  next incremental raise `RunLedgerCompatibilityError`
  (`src/vaultspec_rag/indexer/_checkpoint_common.py:257-266`). Code and document convert
  it to `full_reindex_required` (`src/vaultspec_rag/indexer/_codebase_indexer.py:1053-1059`);
  vault does not, which the `2026-09-07-explicit-reindex-authority-adr` taxonomy expects
  it to.
- Donor vector reuse verifies only `content` equality (`src/vaultspec_rag/indexer/_reuse.py:116-143`),
  not the embedding input. A title difference already escapes it. A heading-path embed
  input would widen that gap.
- A full vault rebuild of 820 records took 69 s on this host (service job `eface894`).

### Output surfaces that must move together

- CLI human rendering prefers `rerank_text`, then the file's lines at
  `line_start..line_end`, then `snippet` (`src/vaultspec_rag/cli/_render.py:314-351`).
  In-process vault hits print the whole chunk; service hits print the snippet. Once
  vault hits carry spans, service mode reads the span from disk.
- The in-process JSON path serializes with `asdict` (`src/vaultspec_rag/cli/_search.py:831`).
  It leaks `rerank_text`, which the HTTP model excludes, and omits `section`.
- The typesafe classifier sends `rerank_text`, never `snippet`
  (`src/vaultspec_rag/search/_typesafe_policy.py:122-133`). Snippet changes do not
  reach it.
- Docs that describe snippet or line fields: `docs/automation.md:48-70`,
  `docs/search-and-index.md:37-41`, `docs/examples.md:48`; docstrings at
  `src/vaultspec_rag/search/_models.py:68-71` and `src/vaultspec_rag/server/_models.py:49-52`.
- Tests that pin shapes or snippet text:
  - `src/vaultspec_rag/tests/integration/test_search_result_shape.py:88-165`
  - `src/vaultspec_rag/tests/test_store_schema_parity.py:72-114`
  - `src/vaultspec_rag/tests/test_vault_metadata_subset.py:74-87`
  - `src/vaultspec_rag/tests/test_typesafe_search.py:201-213`
  - `src/vaultspec_rag/tests/test_cli_search.py:1013-1090`

### Options and what the evidence favours

- **Snippet source.**
  - CrossEncoder passage scoring is the most accurate and reuses the loaded model. At
    fp16 its cost is small beside the chunk rerank.
  - BM25 is within one case, CPU-only and model-free.
  - Dense passage scoring needs passage vectors, which would multiply index size and
    encode cost. Rejected on cost.
  - MaxP ranking folds selection into ranking but changes document order unmeasured.
  - Smaller chunks remain a hypothesis: they change retrieval, and the issue did not
    test them.
- **Selection scope.** Top-2 chunks of the final record beats both the winning chunk
  alone and the whole record.
- **Bound.** Evidence sentences need a paragraph-sized window: 800-1400 characters
  performed alike, and 200 characters cannot hold most evidence sentences.
- **Precision.** fp16 is favoured: it is about 3x faster in service at no measured
  ranking change.
- The ADR must settle:
  - the snippet bound;
  - index-time versus query-time passage segmentation;
  - whether sibling chunks outside the candidate window are fetched;
  - the migration path for existing vault indexes (typed rebuild refusal versus payload
    refresh);
  - whether D8's heading-path embed input rides the same rebuild;
  - the fix for the donor-verification gap;
  - which evaluation gate guards evidence quality in-repo.

### Not investigated

- Chunk size or heading-aligned packing effects on retrieval.
- D8 heading-path embedding effects on ranking.
- Any corpus other than the vaultspec-core vault. This repository's vault has no
  evidence-labelled query set.
- fp16 on MPS hosts.
- Latency under concurrent load.
- Document-collection hits, which share the 200-character cut.

## Sources

- https://github.com/nevenincs/vaultspec-rag/issues/531
- `Y:/code/vaultspec-core-worktrees/typesafe/tmp/typesafe-search-eval/` (issue harness:
  `queries.json`, `heldout.json`, `run_eval.py`, `results/*.score.json`); local and
  untracked
- Scratch prototypes `proto_passages.py`, `proto_doc.py`, `proto_fp16.py`: session
  scratchpad, not committed
- `src/vaultspec_rag/search/_searcher.py:429-435`, `:482-488`, `:638`, `:694-696`
- `src/vaultspec_rag/search/_result_shaping.py:117-119`, `:236`, `:301`
- `src/vaultspec_rag/search/_models.py:68-71`, `:92-113`
- `src/vaultspec_rag/server/_models.py:28-94`
- `src/vaultspec_rag/indexer/_streaming.py:584`
- `src/vaultspec_rag/indexer/_vault_prep.py:186-231`, `:390`, `:430`
- `src/vaultspec_rag/indexer/_chunking.py:111-139`
- `src/vaultspec_rag/indexer/_chunk_worker.py:1447-1496`
- `src/vaultspec_rag/store_schema.py:62-69`, `:146-166`
- `src/vaultspec_rag/_store_models.py:461-484`
- `src/vaultspec_rag/embeddings.py:693`, `:829`
- `src/vaultspec_rag/indexer/_vault_incremental.py:419-452`
- `src/vaultspec_rag/store_ingest.py:221-270`
- `src/vaultspec_rag/indexer/_config_epoch.py:448-454`
- `src/vaultspec_rag/indexer/_index_schema.py:7`
- `src/vaultspec_rag/indexer/_checkpoint_common.py:257-266`
- `src/vaultspec_rag/indexer/_codebase_indexer.py:1053-1059`
- `src/vaultspec_rag/indexer/_reuse.py:116-143`
- `src/vaultspec_rag/cli/_render.py:314-351`
- `src/vaultspec_rag/cli/_search.py:831`
- `src/vaultspec_rag/search/_typesafe_policy.py:122-133`
- `docs/preprocessing-hooks.md:183`, `docs/automation.md:48-70`,
  `docs/search-and-index.md:37-41`, `docs/examples.md:48`
- `sentence-transformers` CrossEncoder `model_kwargs={"torch_dtype": ...}`
  (general-knowledge API; exercised by `proto_fp16.py`)
