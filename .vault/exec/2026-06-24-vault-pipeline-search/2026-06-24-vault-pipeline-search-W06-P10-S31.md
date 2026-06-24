---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S31'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Reindex the real vault on the new code and capture orientation persona live-search testimonials

## Scope

- `.vault/audit/2026-06-24-vault-pipeline-search-live-testimonials-audit.md`

## Description

- Ran orienting-newcomer persona searches against a real GPU index of the existing project
  vault on the new code, capturing actual top-5 results with pipeline frontmatter.
- Surfaced finding F1 (HIGH): auto-generated `index/` documents were ranking first; ADR D6's
  exclusion had been enforced only as a rejected filter value, not at search time.
- Fixed F1 by dropping `doc_type == "index"` rows in the vault searcher before rerank, and
  added a regression guard to the intent-ranking harness.
- Persisted the run and the finding in the live-testimonials audit.

## Outcome

After the F1 fix the orientation personas get the accepted ADR at rank 1 for the concurrent
saturation, qdrant provisioning, and mcp client queries; index documents no longer surface.
One query ("decision on gpu lock scope") ranks the accepted ADR at rank 2 behind a tangential
research doc (F3, low/tuning). `ruff` and `ty` pass; the searcher fix is GPU-verified.

## Notes

The running service was on three-day-old code and its Qdrant child failed readiness on
restart (an infra flake, ports in TIME_WAIT), so the live searches were captured via the
in-process path on the new code against a hermetic copy of the real vault. Restarting the
service on the new code and reindexing is recommended as a follow-up. No code blockers.
