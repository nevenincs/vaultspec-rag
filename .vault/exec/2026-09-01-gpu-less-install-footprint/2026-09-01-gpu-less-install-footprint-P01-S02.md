---
tags:
  - '#exec'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:92bf85e395c45f9617c22425bdc274d9cfdf79245ecba04f929a690909ae9020'
step_id: 'S02'
related:
  - "[[2026-09-01-gpu-less-install-footprint-plan]]"
---

# Preserve actionable missing-compute remediation at the lazy inference boundary

## Scope

- `src/vaultspec_rag/embeddings.py and tests`

## Changes

- `M` `src/vaultspec_rag/embeddings.py`
- `A` `src/vaultspec_rag/tests/test_embeddings_dependencies.py`
- verify: `uv run --no-sync pytest src/vaultspec_rag/tests/test_embeddings_dependencies.py src/vaultspec_rag/tests/test_torch_load_centralized.py -q` -> pass
