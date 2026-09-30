---
tags:
  - '#research'
  - '#sparseencode'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:599029820e46e0e1e5c8341ecbcd4afd197c756176c812a5248d0a43e2c72b01'
related: []
---

# `sparseencode` research: `ModernBERT sparse retrieval contract`

The requested public ModernBERT sparse replacement is SPARSEUP. Its upstream pooling and preprocessing differ from a conventional masked-language-model sparse encoder; preserving that contract and fencing older indexes are the migration's main requirements.

## Findings

### Public model and pinned implementation

Linkup-Platform/linkup-sparseup-embed-v1 is an ungated Apache-2.0 checkpoint. The public model API identifies revision `08314498d4f6a3a205b930ab9f27001404ea94b8`. It uses a 149M ModernBERT backbone. Source: https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1 and https://huggingface.co/api/models/Linkup-Platform/linkup-sparseup-embed-v1 .

### Representation semantics

The pinned model config has vocabulary width 50370. Its custom model applies logit shift 15, per-position top-12 threshold gating, masked max pooling and checkpoint-persisted vocabulary folding. Folded active vocabulary is smaller than output tensor width. Query/document prefixes are attended but excluded from pooling; evaluated lengths are 128/512. Ordinary ModernBERT masked-language-model loading with generic sparse pooling loses these semantics. Source: https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1/blob/08314498d4f6a3a205b930ab9f27001404ea94b8/config.json and https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1/blob/08314498d4f6a3a205b930ab9f27001404ea94b8/modeling_splade.py .

### Loader and dependency strategy

The published custom Sentence Transformers module discards loader kwargs and internally loads its model with remote-code trust. Outer revision, offline, dtype and attention settings therefore do not reliably govern the inner load. A direct adapter around the pinned upstream model can preserve its pooling while controlling loading and separating preprocessing from the locked forward call. Sentence Transformers 5.4.0 supplies the custom module's InputModule import path; Transformers 5.3.0 is the saved model version. Raising those floors conservatively avoids the old dependency contract. Exact earliest compatible Transformers version is untested. Source: https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1/blob/08314498d4f6a3a205b930ab9f27001404ea94b8/custom_st.py and https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1/blob/08314498d4f6a3a205b930ab9f27001404ea94b8/config_sentence_transformers.json .

### Performance and migration implications

The evidence favors reusing upstream preprocessing and forward pooling through a canonical adapter. Inference: length-homogeneous buckets, one pooled batch transfer and vectorized CPU sparse extraction avoid padding and per-term device synchronization. Reduced precision must be checked against full precision because gating is threshold-sensitive. Native ModernBERT SDPA is available without a mandatory FlashAttention dependency. Vocabulary IDs and weights differ from the existing sparse encoder, so mixing old document vectors with new queries is invalid. Source: pinned implementation above and https://huggingface.co/docs/transformers/model_doc/modernbert .

### Existing compatibility needs a sparse vocabulary fence

The existing model comparator reports sparse-model disagreement as nonconforming, while the ensure path raises only for geometry-fatal verdicts. It therefore observes the replacement but can still accept new sparse queries and writes against an older vocabulary at unchanged vector geometry. The breaking sparse upgrade needs a refusal at that canonical ensure seam; the existing dense-model degradation policy can remain. Sources: `src/vaultspec_rag/store_schema.py:809`, `src/vaultspec_rag/store_collections.py:440`, and `src/vaultspec_rag/store_runtime.py:165`.

### Measured CUDA behavior

The supervisor ran the pinned model on NVIDIA GeForce RTX 4080 SUPER with torch 2.14.0+cu130, Sentence Transformers 6.1.0 and Transformers 5.17.0. The adapter uses float32 and SDPA. Query/document parity against the upstream pinned implementation, single-versus-batch behavior, prefix/pooling masks, truncation, vocabulary folding and bounded CPU output retention passed in three real-GPU tests. Command: `.venv/Scripts/python.exe -m pytest src/vaultspec_rag/tests/integration/test_embeddings.py -k 'pinned_sparse_upstream_parity or sparse_document_slices_release_cuda_outputs' -q --report-log .pytest-tmp/sparse-gpu-events.jsonl`; 3 passed, 7 deselected in 61.86 seconds.

A separate borrowed-GPU measurement compared upstream original-order batching to `EmbeddingModel.encode_documents_sparse` length grouping. Both used the same loaded checkpoint, pinned tokenizer, float32/SDPA, document preprocessing, batch size 4 and CPU `_sparse_tensor_to_results` conversion. The new path additionally used the production forward lock. Output arrays matched at rtol/atol 1e-4 before timing. One dedicated consumer thread owned GPU work; the existing resident service was paused and resumed through its authenticated borrower protocol. No live index was modified.

Reproduction corpus: for each integer 0 through 7, append these four documents in order: the integer followed by `architecture decision vector database cache`, repeated 150 times; the integer followed by `quick query`; the integer followed by `retrieval search sparse tokenizer model`, repeated 140 times; the integer followed by `cake recipe`. Thus each original batch mixes long and short documents. Warm up each path twice; run seven measurement pairs, alternating which path runs first. Synchronize CUDA before starting and after each call, and reset peak allocation counters before each call.

| Path                    | Seven elapsed times (seconds)                                        | Median seconds | Documents/second |
| ----------------------- | -------------------------------------------------------------------- | -------------- | ---------------- |
| Upstream original order | 0.491545, 0.502617, 0.475410, 0.491756, 0.500361, 0.532144, 0.504521 | 0.500361       | 63.95            |
| Grouped adapter         | 0.401268, 0.385544, 0.394669, 0.386504, 0.421913, 0.386595, 0.391393 | 0.391393       | 81.76            |

Observed median speedup: 1.2784x, or 21.8% lower elapsed time, for this 32-document mixed-length corpus. Total peak allocated CUDA memory was 3163.60 MiB in both paths, including resident dense and sparse models. This comparison supports a batching improvement, not a memory reduction or an old-versus-new-model retrieval-quality claim. The standalone measurement command was `.venv/Scripts/python.exe .pytest-tmp/sparse-benchmark.py`; local JSON and log outputs are in `.pytest-tmp/sparse-benchmark.json` and `.pytest-tmp/sparse-benchmark.log`. It used the ordinary CLI borrower path; an initial attempt to use the pytest-only pre-isolation capture seam refused before GPU allocation and was corrected.

Float32 remains the default: parity and grouping performance are established without assuming a reduced-precision accuracy tradeoff. Apple MPS behavior was not measured on this CUDA host.

## Sources

https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1

https://huggingface.co/api/models/Linkup-Platform/linkup-sparseup-embed-v1

https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1/blob/08314498d4f6a3a205b930ab9f27001404ea94b8/config.json

https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1/blob/08314498d4f6a3a205b930ab9f27001404ea94b8/modeling_splade.py

https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1/blob/08314498d4f6a3a205b930ab9f27001404ea94b8/custom_st.py

https://huggingface.co/Linkup-Platform/linkup-sparseup-embed-v1/blob/08314498d4f6a3a205b930ab9f27001404ea94b8/config_sentence_transformers.json

https://huggingface.co/docs/transformers/model_doc/modernbert

`src/vaultspec_rag/store_schema.py:809`

`src/vaultspec_rag/store_collections.py:440`

`src/vaultspec_rag/store_runtime.py:165`
