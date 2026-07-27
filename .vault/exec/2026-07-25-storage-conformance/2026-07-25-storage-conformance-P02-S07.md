---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
step_id: 'S07'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Add the three-verdict conformance evaluator over stamped identity and live geometry, feeding the existing compatibility comparator

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

Plan evidence: `2026-07-25-storage-conformance-plan` marks `P02.S07` closed for Add the three-verdict conformance evaluator over stamped identity and live geometry, feeding the existing compatibility comparator.

## Outcome

`evaluate_conformance` in the neutral schema leaf, returning a
`ConformanceVerdict` of `conforming`, `nonconforming`, or `unverifiable` plus a
`geometry_fatal` flag that separates the two failure modes sharing the
`nonconforming` verdict.

The version, width, and vector-name rules route through the existing
`assert_compatible` rather than being restated, so the two callers cannot drift.
The model comparison is this function's own, because it is the fact the
descriptor could never carry: `describe_storage_schema` reads the model from
live config, so it reports what the process is configured with and never what
built the vectors.

Built during `P01` as a consequence of placing `CollectionIdentity` in the same
leaf; closed here where the plan sequences it.

## Notes

Template evidence: intro_commit=1c1b0441e97f7423e71cd4e4fc0e3096126888bb; template_commit=1c1b0441e97f7423e71cd4e4fc0e3096126888bb:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
