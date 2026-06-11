---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S01'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Implement the preprocess rule dataclass, tomllib loader, pathspec compilation, determinism sort, and error policy (D1, D2, D3)

## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`

## Description

Added `_preprocess_config.py`: a frozen, picklable `PreprocessRule` dataclass; a
`PreprocessConfig` matcher that compiles one `pathspec.GitIgnoreSpec` per rule and
exposes a deterministic first-match `match()` (rules pre-sorted by `(priority, order)`);
and `load_preprocess_rules(root_dir, strict=)` reading `.vaultragpreprocess.toml` with
stdlib `tomllib`. Validation enforces the D1 rule shape (pattern required, command XOR
entry_point, valid `on_error`, positive `timeout_s`) and the D9 command-only constraint
(entry_point rules dropped). Error policy per D3: malformed file or rule degrades to a
warning in the default mode; `strict=True` raises `PreprocessConfigError` for the
`preprocess check` verb.

## Outcome

Module complete and CPU-only (no torch import). ruff clean, basedpyright strict 0.

## Notes

Matching is parent-side (compiled specs not pickled); the matched `PreprocessRule` is
pickle-safe for threading into the spawn worker in W03.P05.
