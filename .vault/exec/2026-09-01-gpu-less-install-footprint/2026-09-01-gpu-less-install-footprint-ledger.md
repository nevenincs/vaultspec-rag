---
tags:
  - '#exec'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:841f6b21c98784f9f2f724b3f72f13944f6df6c6b6ba6c8b5ad6502b278b886d'
related:
  - "[[2026-09-01-gpu-less-install-footprint-plan]]"
---

# `gpu-less-install-footprint` ledger

## Changes

- `S01` `M` `pyproject.toml`
- `S01` `M` `uv.lock`
- `S02` `M` `src/vaultspec_rag/embeddings.py`
- `S02` `A` `src/vaultspec_rag/tests/test_embeddings_dependencies.py`
- `S03` `M` `src/vaultspec_rag/tests/test_packaging_metadata.py`
- `S04` `M` `README.md`
- `S04` `M` `docs/installation.md`
- `S04` `M` `docs/backends.md`
- `S04` `M` `docs/mcp.md`
- `S05` `M` `.github/workflows/acquisition.yml`
- `S06` `M` `src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json`
- `S06` `M` `tools/binaries/build_pyapp.py`
- `S06` `M` `tools/binaries/tests/test_build_pyapp.py`
- `S06` `M` `tests/smoke_check.py`
- `S06` `M` `src/vaultspec_rag/tests/test_install_mode.py`
- `S07` `M` `src/vaultspec_rag/_gpu.py`
- `S07` `M` `src/vaultspec_rag/cli/_gpu_errors.py`
- `S07` `M` `src/vaultspec_rag/tests/test_service_env_preflight.py`
- `S07` `M` `src/vaultspec_rag/tests/integration/test_install_basics.py`
- `S07` `M` `src/vaultspec_rag/tests/integration/test_install_preview_modes.py`
- `S07` `M` `src/vaultspec_rag/tests/integration/test_install_uninstall_contracts.py`
