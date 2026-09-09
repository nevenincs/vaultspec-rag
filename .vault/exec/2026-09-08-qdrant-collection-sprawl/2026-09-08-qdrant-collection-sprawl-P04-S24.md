---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:ec8a1066c167665cd8285c3a7effbd26201be3b4514058250ae5a44ae3053ba8'
step_id: 'S24'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a test proving ledger entries for absent collections are pruned and live entries are preserved

## Scope

- `src/vaultspec_rag/tests/test_generation_survey.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_generation_survey.py`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_generation_survey.py` -> `pass`

## Notes

Also updates the two pre-existing `TestGenerationStampAdvance` calls to pass the new
`live` argument the `S23` signature change requires; both land in the same commit as
that change. Broke the guard (reverted the live-membership filter to `dict(stamps)`),
ran the new test alone, watched it fail on the `"c_vanished" not in advanced` assertion,
restored, watched all 21 tests in the file pass.
