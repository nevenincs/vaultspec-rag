---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
step_id: 'S24'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Cover the local sidecar round-trip and confirm a local root records no manifest entry

## Scope

- `src/vaultspec_rag/tests/test_storage_identity.py`

## Description

Covered the local sidecar round-trip, the sibling-preserving merge, and the
negative assertion that a local root stays out of the manifest.

## Outcome

Three tests in the shared identity module, all proved to fail against their
named mutations - see the table in the `S05` record, which carries the proofs
for every guard this Phase added rather than splitting them across two
records.

The absent-evidence test asserts two distinct things that are easy to conflate:
that an unwritten sidecar reads as `None`, and that a partial payload also reads
as `None` rather than being completed with defaults. The second is the one that
matters - defaulting a missing field is how absent provenance would quietly
become a passing verdict.

## Notes
Template evidence: intro_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78; template_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
