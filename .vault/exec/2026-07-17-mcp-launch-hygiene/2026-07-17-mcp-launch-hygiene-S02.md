---
tags:
  - '#exec'
  - '#mcp-launch-hygiene'
date: '2026-07-17'
modified: '2026-07-17'
body_hash: 'sha256:603a524d96f1f4ab52f9a6bb561e565aaa9380b9582a7abf4c22d9fdbc4daa68'
step_id: 'S02'
related:
  - "[[2026-07-17-mcp-launch-hygiene-plan]]"
---

# Make the ensure-mcp-extra step placement-aware: detect rag's existing declaration in the host pyproject, fall back to the declared mode, skip in tool mode, and thread the resolved placement from the install orchestrator

## Scope

- `src/vaultspec_rag/commands/_uv_sync.py`

## Description

- Add `_detect_rag_placement` (stdlib tomllib read of the host pyproject:
  runtime deps first, then PEP 735 groups; exact-name requirement match).
- Add the pure `_mcp_extra_add_command` matrix: existing placement wins,
  declared mode is the fallback (dev -> --group dev), tool mode skips.
- Thread `resolved.mode.value` from the install orchestrator into
  `_run_uv_add_mcp_extra`; tool mode reports `skipped-tool-mode` without
  shelling out.

## Outcome

ruff/basedpyright/ty green across commands/.

## Notes

None.
