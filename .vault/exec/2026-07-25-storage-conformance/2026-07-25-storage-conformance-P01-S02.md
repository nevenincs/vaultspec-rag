---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
step_id: 'S02'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Add the per-collection identity record type and its manifest serialization, defaulting absent identity to unknown rather than to current values

## Scope

- `src/vaultspec_rag/storage_manifest.py`

## Description

Added the per-collection identity record - dense model, sparse model or its
absence, dense width, distance, both vector names, and the storage schema
generation - together with its JSON round-trip and the manifest fields that
persist it.

The type landed in `store_schema.py` rather than in the manifest as the Step's
scope clause anticipated. The manifest must construct the type, and the
backend-dispatching accessor must import both the manifest and the type; putting
the type in the manifest makes that a cycle. `store_schema.py` is the neutral,
torch-free leaf both already depend on, so it is the only placement that keeps
the accessor importable without one. The manifest fields themselves are in the
Step's declared scope as planned.

## Outcome

`CollectionIdentity` with `to_payload` / `from_payload`, and
`ManifestEntry.collection_identity` keyed by exact collection name, persisted
and reloaded through the existing atomic write.

`from_payload` returns `None` for any malformed or incomplete payload rather
than substituting defaults. Defaulting a missing field would manufacture exactly
the provenance the type exists to prove, and would turn absent evidence into a
silent pass - the failure this feature was written to remove.

## Notes

Template evidence: intro_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78; template_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
