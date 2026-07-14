---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S14'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Remove sandbox-backend reporting from the server routes preprocess pre-flight

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

- Update `_preprocess_preflight`'s docstring to the two-state mode; the JSON body (`config_present`, `rule_count`, `mode`, `hooks_will_run`) already carried no backend field.

## Outcome

Pre-flight reports `off` skips / `default` runs.

## Notes

None.
