---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S16'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add a qdrant-binary provisioning step that delegates to the existing provisioner and maps its action onto the shared sync vocabulary

## Scope

- `src/vaultspec_rag/commands/_provision.py`

## Description

- Add `_provision_qdrant` delegating to the existing `qdrant_runtime.provision` and translating its `QdrantProvisionAction` onto the front door's vocabulary via `_map_qdrant_action`.
- Short-circuit on `local_only` (skip with the local-only/on-disk-store reason) and on the `qdrant` skip token, before any provisioner call.
- Supply a default detail line for created/updated/unchanged when the provisioner left its message empty, so a fetched binary reads as `downloaded` and a satisfied one as `verified ... already present`.

## Outcome

The qdrant step provisions the pinned binary by default and reports through the shared vocabulary, with `--local-only` and the per-dependency skip token both opting out cleanly. The provisioner's verify-before-execute security contract (committed-digest verify before extract, re-verify before exec, HTTPS host-pinned) is preserved untouched - this is a pure delegation that only translates the returned action.

## Notes

No Step bundles the binary; provisioning stays a runtime concern, honouring the pure-Python-wheel constraint. Idempotency is the provisioner's: a verified install is an `unchanged` no-op with zero network I/O, which the front-door tests prove by pre-seeding a verified install into a temp-isolated managed dir rather than downloading.
