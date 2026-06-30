---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-30'
step_id: 'S09'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Add server start --qdrant and --qdrant-auto-provision consent flags translated to daemon env, hard-failing with the exact install command when the binary is absent without consent

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`
- `src/vaultspec_rag/cli/_process.py`

## Description

- Add `--qdrant/--no-qdrant` and `--qdrant-auto-provision` to `server start`;
  `_ensure_qdrant_binary` fails fast with the exact `server qdrant install` command
  when the binary is absent without consent, and provisions inline (reporting version
  and path) when consent was given.
- Translate the tri-state qdrant flag to `VAULTSPEC_RAG_QDRANT_SERVER` in
  `_service_child_env` / `_spawn_service`; unset leaves operator env untouched,
  matching the watcher-flag precedent.

## Outcome

Start-path guard verified by the persona pass (P05): absent-binary start exits 1
with the install command; consented start provisions then boots server mode.

## Notes

None.
