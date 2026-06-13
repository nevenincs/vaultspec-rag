---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S39'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# update the start and install command help text to describe the server-first default and the local-only escape hatch

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Update the `server start` command-level help to state that it defaults to the managed Qdrant server backend (server mode) and that `--local-only` selects the on-disk store.
- The `--local-only` and reframed `--qdrant` option help (server mode is the default; `--qdrant` is redundant; `--local-only` is the first-class opt-out) already landed with W01.P03; the install command's opt-out help landed with W02.P05. This Step closes the start command's top-level help.

## Outcome

- `vaultspec-rag server start --help` now leads with the server-first default and names the `--local-only` escape hatch. `ruff`/`ty` clean.

## Notes

- `_service_lifecycle.py` is concurrently edited by another worker on the shared branch; the help-string change here is minimal and additive and was re-applied after a concurrent modification was detected mid-edit.
