---
tags:
  - '#exec'
  - '#cli-tree-overhaul'
date: 2026-06-07
modified: '2026-06-30'
step_id: S57
related:
  - '[[2026-06-06-cli-tree-overhaul-plan]]'
---

# cli-tree-overhaul W03 P06 S57

## Intent

Fix 10 test regressions introduced during Pyright type safety remediations in P05.

## Action

- Reverted the `import` logic change in `src/vaultspec_rag/tests/test_install_torch_config.py` which had caused `test_install_warns_when_hf_token_missing` to fail due to `ImportError`.
- Fixed flag formatting logic in `src/vaultspec_rag/search/_validation.py` to ensure it properly generated usage error strings.
- Updated 4 test assertions in `src/vaultspec_rag/tests/test_cli.py` to use the correctly formatted strings.
- Re-added the missing keyword arguments handling via `*args, **kwargs` in `mock_run_benchmark` in `test_cli.py`.
- Ran the test suite to ensure all regressions were addressed. 152 tests passed.
