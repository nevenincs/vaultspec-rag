---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-06
related: []
---

# Audit: Config and Dependencies

Feature: config.py, pyproject.toml, __init__.py

## 2026-03-06 -- Review (Passes 17-28)

### config.py: Defaults Updated for GPU

VaultSpecConfigWrapper RAG defaults:

- `embedding_model: "Qwen/Qwen3-Embedding-0.6B"` (was nomic)
- `embedding_dimension: 1024` (was 768)
- `sparse_model: "naver/splade-v3"` (was bm42)

### pyproject.toml: Dependencies Updated

- Added: `sentence-transformers>=5.0`, `torch>=2.4`, `transformers>=4.51`
- Changed: `qdrant-client>=1.12.0` (plain, no fastembed extra)
- Removed: `fastembed>=0.4.0`
- `benchmark` marker used in bench_rag.py but not registered in markers list (cosmetic warning)

### __init__.py: Docstring Updated

Line 1-5: Now says "GPU-native embedding pipeline using sentence-transformers + Qwen3-Embedding-0.6B" (was "fastembed (ONNX)").

### Open Issues

- Task #46 \[LOW\]: config.py:24 still has `lance_dir: ".lance"` dead default.
