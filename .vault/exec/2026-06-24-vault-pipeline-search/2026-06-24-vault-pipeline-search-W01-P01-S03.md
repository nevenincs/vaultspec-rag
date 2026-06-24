---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S03'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Enrich the synthetic corpus generator with status markers and pipeline-role edges

## Scope

- `src/vaultspec_rag/synthetic.py`

## Description

- Added a `status` field to `GeneratedDoc` and a `statuses` map to `CorpusManifest`
  (both additive; the existing public API and fields are unchanged).
- Added a `_make_title` helper rendering ADR-aware headings: the legacy `# ADR: ...`
  no-marker form for the first ADR (status `unknown`), the modern
  `# \`feature\` adr: \`...\` | (**status:** \`value\`)` form otherwise; non-ADR titles
  unchanged.
- Assigned ADR statuses deterministically (first ADR `unknown`, then cycling
  proposed/superseded/accepted) so all extraction paths have coverage.
- Added `_add_pipeline_edges` writing research<-adr<-plan<-exec and reference<-research
  lineage links on top of the density-based random edges.

## Outcome

The generator now produces all three real ADR heading formats and pipeline-role edges.
Verified by smoke test: a 24-doc corpus yields statuses {accepted, proposed, superseded,
unknown}, the legacy ADR renders `# ADR: ...` and the modern ones carry the status marker,
and pipeline edges are present. `ruff` and `ty` pass.

## Notes

Changes are additive, so existing synthetic consumers keep working; GPU integration tests
that assert needle membership are unaffected by the richer ADR headings. No blockers.
