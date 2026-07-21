---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S01'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Add a pure-path runtime env classifier (installed-tool, uvx-ephemeral, project-venv, other) keyed on sys.prefix vs UV_TOOL_DIR and UV_CACHE_DIR shapes including archive-v0, with \_running_in_uv_tool_env delegating to it, plus a single constant-derived helper producing the escape-hatch command for a given interpreter and the durable receipt-carrying uv tool install command

## Scope

- `src/vaultspec_rag/cli/_gpu_errors.py`

## Description

- Add `RuntimeEnvKind` StrEnum (uv-tool, uvx-ephemeral, project-venv, other) with human labels.
- Add `classify_runtime_env` (pure path logic: archive-v0 or UV_CACHE_DIR ancestor means ephemeral; UV_TOOL_DIR ancestor or a `tools` parent means uv tool; `.venv`/`venv` means project venv) and `classify_interpreter_env` (walks Scripts/bin up to the env root).
- Add `gpu_escape_hatch_command(interpreter)` and `durable_tool_install_command()`, both deriving from `CU130_INDEX_URL` in `src/vaultspec_rag/torch_config/_constants.py`.
- Remove `_running_in_uv_tool_env` (its only caller now uses the classifier directly).

## Outcome

Committed as 8a857ad. ruff, basedpyright, and ty clean; covered by the S05 truth-table tests.

## Notes

The `tools`-parent heuristic is kept as-is from the removed predicate (no `uv` grandparent requirement) so existing detection behaviour is preserved; misclassification only changes which hint prints.
