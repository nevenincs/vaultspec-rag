---
tags:
  - '#exec'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:211feec644f92d88eef25f740d8acb64f23f207bede6adedbf8db4a1fe32f864'
related:
  - "[[2026-09-01-gpu-less-install-footprint-plan]]"
---
# `gpu-less-install-footprint` `P01` summary

## Changes

- `M` `pyproject.toml`
- `M` `uv.lock`
- `M` `src/vaultspec_rag/embeddings.py`
- `M` `src/vaultspec_rag/_gpu.py`
- `M` `src/vaultspec_rag/cli/_gpu_errors.py`
- `M` `src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json`
- `M` `src/vaultspec_rag/tests/test_install_mode.py`
- `M` `src/vaultspec_rag/tests/test_packaging_metadata.py`
- `A` `src/vaultspec_rag/tests/test_embeddings_dependencies.py`
- `M` `tools/binaries/build_pyapp.py`
- `verify:` `just lint type-strict` -> `pass`
