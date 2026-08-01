---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:a36b2d0b7708ba5e5b8c89ae14948bc5077a34c3fdff9b3965dd9ecb63ceb4c6'
step_id: 'S02'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

# Admit root into the survey transport params and thread the optional root argument through the MCP survey client and the get_storage_survey tool surface

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Admit `root` into `_STORAGE_SURVEY_PARAMS` so the `get_storage_survey`
  admin tool encodes it onto the `/storage/survey` route path.
- Add the optional `root` argument to `survey_storage` in
  `src/vaultspec_rag/mcp/_admin_client.py`, documenting that the service
  computes the prefix and callers never derive the hash.

## Outcome

Both client adapters pass the parameter through to the one route; neither
computes anything. Ruff and basedpyright clean on the touched modules.

## Notes

The MCP server's narrowed 5-tool surface does not expose the survey as a
standalone MCP tool; the `get_storage_survey` tool name lives in the
serviceclient admin resolver, which is the surface the plan row names.
