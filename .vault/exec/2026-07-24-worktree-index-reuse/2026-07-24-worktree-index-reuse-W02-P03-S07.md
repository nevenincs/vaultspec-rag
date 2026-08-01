---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:31a1b6a9ef7582cfe277604870d6d80b3c1bed9115cf60a99079682a00f2bf93'
step_id: 'S07'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# add the default-on reuse off-switch knob to config with env override, and thread it to the indexer entry points

## Scope

- `src/vaultspec_rag/config.py`
- `indexer wiring`

## Description

- Add the `INDEX_REUSE` env member (`VAULTSPEC_RAG_INDEX_REUSE`) to the `EnvVar` enum, grouped after the worker-thread pool knobs.
- Register `index_reuse_enabled` in `_ENV_OVERRIDE_MAP` against that env member so it resolves through the shared bool env-override path (`env_val.lower() in ("1", "true", "yes")`).
- Add the `index_reuse_enabled` default (`True`) to `_RAG_DEFAULTS`, with a comment stating the constraint directly: default-on encode-seam vector reuse, off disables every donor lookup and restores encode-everything baseline.
- Extend `test_config.py`: default-is-True test, parametrized falsey/truthy env-override tests mirroring the existing `watch_enabled` cases, and a reset_config pick-up test asserting a fresh singleton reflects the new env value.
- Run ruff check, ruff format, pytest, basedpyright, and ty on the two touched files.

## Outcome

Encode-seam vector reuse now has a default-ON off-switch: `config.index_reuse_enabled` (bool, default `True`), env override `VAULTSPEC_RAG_INDEX_REUSE`. When falsey the knob resolves `False`; the seam-integration step consumes it later to disable all donor lookups. Config-surface only - no indexer/store wiring in this change.

Verification: `pytest src/vaultspec_rag/tests/test_config.py` 121 passed (13 new index_reuse cases). ruff check and format clean; basedpyright 0 errors/0 warnings; ty (`--python-platform all`) all checks passed.

## Notes

- This Step's plan row also names "thread it to the indexer entry points"; that wiring (`indexer/_streaming.py`, `store.py`) is owned by sibling steps (S08/S09) and other agents and was deliberately left out of this change per the assigned scope. The knob is the surface those steps consume.
- The initial reset_config test asserted a stale-until-reset read; env is resolved live per attribute access in `_resolve_rag_default`, so that premise was false. Corrected the test to bind what reset_config actually guarantees: a distinct fresh singleton reflecting the changed env.
- No CLI flag added (config + env is the surface for this step).
