---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
step_id: 'S23'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Add the local-mode identity sidecar under the per-root storage directory, and the backend-dispatching accessor pair every caller uses instead of either home

## Scope

- `src/vaultspec_rag/storage_identity.py`

## Description

Added the local-mode identity home and the backend-dispatching accessor pair.

This Step exists because of a correction found during execution: the manifest
hook that was to hold the identity runs in server mode only, so local mode - the
documented path for small and offline projects - would have had no record at all
and every local collection would have read as permanently `unverifiable`. The
authorizing decision was amended in place to state the two-home design before
this Step was written.

## Outcome

`storage_identity.py`: `load_identity` and `record_identity` dispatch on
backend, plus a per-root sidecar under the local storage directory written
atomically under a lock, merging rather than replacing.

Extending the manifest to cover local roots was the obvious alternative and was
rejected on safety. The survey classifies a namespace by matching manifest
entries against live server collections and reclamation acts on that verdict; a
local entry would match nothing and so would present as an unattributable
namespace to the one surface whose governing rule says it must never be handed
one. A conformance feature must not create a new class of namespace the
reclaimer cannot explain. A guard test asserts a local stamp writes no manifest
entry.

The module is a torch-free leaf - stdlib plus the schema definitions - so it
stays importable from a spawn worker's chain without pulling in CUDA. The store
imports it function-locally, which is what keeps the store, manifest, and
accessor free of an import cycle.

## Notes
Template evidence: intro_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78; template_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
