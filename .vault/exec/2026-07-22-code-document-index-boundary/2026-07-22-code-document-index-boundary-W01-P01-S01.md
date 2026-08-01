---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:2d4a61ee57af1c4406dd28d08f6185efd49585acb864ccb9a9d60aa4860ba4c6'
step_id: 'S01'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Define closed content-kind, admission-disposition, stable-reason, and source-profile-version types

## Scope

- `src/vaultspec_rag/indexer/_content_policy.py`

## Description

- Define stable code and document ownership tokens.
- Define stable explicit-route, source-profile, ignore, routing, size, binary, and probe
  disposition reasons.
- Version conventional and explicit-only source profiles independently from parser
  capability.
- Keep admission outcomes immutable and reject admitted paths without an owner.
- Verify the module with Ruff, Ty, basedpyright, and a real import and immutability probe.
- Audit generic architecture, import safety, scope, and one-owner intent.

## Outcome

`ContentKind`, `AdmissionReason`, `SourceProfileVersion`, and the frozen, slotted
`AdmissionDisposition` now form the dependency-free vocabulary for later policy Steps.
The formal review passed with no findings.

## Notes

No incidents or data loss. Focused classifier and configuration tests remain assigned to
their later plan Steps; S01 introduced no test doubles or production behavior beyond the
typed contract.
