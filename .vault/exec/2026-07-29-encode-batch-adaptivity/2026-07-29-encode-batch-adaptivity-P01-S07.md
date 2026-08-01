---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:86920c8842ac4208bd814d6370720b7c3730bb612592ae720491ef5a51dc641a'
step_id: 'S07'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# wire the new encode settings through the env-var schema map

## Scope

- `src/vaultspec_rag/config/_schema.py`

## Description

- add the `EnvVar` members in `src/vaultspec_rag/config/_types.py` and the `ENV_OVERRIDE_MAP` entries in `src/vaultspec_rag/config/_schema.py` for both encode knobs

## Outcome

Commit `8e0a4973`. Gates each exit 0; pytest 35 passed. Env-override probe returns 12000 / 3 under the new variables.

## Notes

Scope grew by `src/vaultspec_rag/config/_types.py`, structurally required by the map.
