---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:2d81073fca283d0482e297f9c191214d5c5332b627781584037f534601b90bd6'
step_id: 'S02'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Remove the trust branch from load_preprocess_rules so rules resolve for any root, replacing the mode enforcement with the off kill switch and the unsandboxed escape hatch only

## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`

## Description

- Rewrite the loader's mode enforcement so it applies only the `off` kill switch: an empty config passes through, `off` returns an empty config with a debug log, and every other mode returns the resolved rules unchanged.
- Drop the trust-store import, the trust-all warning branch, and the trust-hash/`is_trusted` default branch entirely; the function no longer takes the root argument it used only to key the trust store.
- Update the `load_preprocess_rules` docstring to describe resolve-for-any-root plus the kill switch, and note that strict mode still bypasses the gate for `preprocess check`.

## Outcome

`load_preprocess_rules` resolves a root's rules with no trust check; only `VAULTSPEC_RAG_PREPROCESS=off` gates execution at the loader. Containment at the runner (the sibling workstream's sandbox) is now the sole security boundary. Ruff and basedpyright are clean on the module; the reworked unit suite passes.

## Notes

No sandbox logic was added here; the `unsandboxed` mode resolves rules identically to `default` at the loader and is consumed later by the runner.
