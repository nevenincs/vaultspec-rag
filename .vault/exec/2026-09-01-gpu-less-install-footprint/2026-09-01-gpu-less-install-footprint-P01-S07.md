---
tags:
  - '#exec'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:c1a55b2a75bb44e3d4fe9474f0cdcb7681687f8c4f77805503e868d0c92e9c92'
step_id: 'S07'
related:
  - "[[2026-09-01-gpu-less-install-footprint-plan]]"
---
# Update tool and CLI remediation for the explicit GPU runtime

## Scope

- `GPU dependency diagnostics and tests`

## Changes

- `M` `src/vaultspec_rag/_gpu.py`
- `M` `src/vaultspec_rag/cli/_gpu_errors.py`
- `M` `src/vaultspec_rag/tests/test_service_env_preflight.py`
- `M` `src/vaultspec_rag/tests/integration/test_install_basics.py`
- `M` `src/vaultspec_rag/tests/integration/test_install_preview_modes.py`
- `M` `src/vaultspec_rag/tests/integration/test_install_uninstall_contracts.py`
- verify: `uv run --no-sync pytest src/vaultspec_rag/tests/test_service_env_preflight.py src/vaultspec_rag/tests/integration/test_install_basics.py src/vaultspec_rag/tests/integration/test_install_preview_modes.py src/vaultspec_rag/tests/integration/test_install_uninstall_contracts.py -q` -> pass
