---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S09'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Add related and status fields to SearchResult

## Scope

- `src/vaultspec_rag/search/_models.py`

## Description

- Added `status: str = ""` and `related: list[str]` (via `field(default_factory=list)`) to
  the `SearchResult` dataclass, importing `field`.
- Documented both attributes, noting they are empty for codebase results and that `status`
  is empty for non-ADR and legacy headings.

## Outcome

`SearchResult` now carries the two frontmatter fields the enriched results and the
status-aware prior depend on. Because the CLI serializes results via `asdict`, both fields
flow into `--json` automatically. `ruff` and `ty` pass.

## Notes

The fields are populated by the searcher mapping in S10. No blockers.
