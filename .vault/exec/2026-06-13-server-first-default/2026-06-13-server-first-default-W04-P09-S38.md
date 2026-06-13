---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S38'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# update the bundled RAG rule prose to describe server mode as the default backend and local-only as the explicit opt-out

## Scope

- `.vaultspec/rules/rules/vaultspec-rag.builtin.md`

## Description

- Reframe the "Run the server" section of the bundled RAG rule from the old explicit-`--qdrant` opt-in to the server-first default: `server start` defaults to the managed Qdrant server, `vaultspec-rag install` provisions torch/models/binary by default, and `--local-only` (or `VAULTSPEC_RAG_LOCAL_ONLY=1`, or `install --local-only` which persists the choice) is the first-class opt-out.
- Add `vaultspec-rag server doctor` (`--json`) as the dependency-readiness check.
- Regenerate the provider mirrors with `vaultspec-core sync` and re-bless the gitignored builtin snapshot so `spec doctor` stays current.

## Outcome

- The bundled rule now teaches server-first as the default; `spec doctor` reports `builtins: current` and all provider dirs `ok` after sync + snapshot re-bless.

## Notes

- The builtin's gitignored `_snapshots/` baseline is re-blessed to the new source content (the source is the intended prose), which is how `spec doctor`'s builtin check is kept green after an intentional rule edit on this branch.
