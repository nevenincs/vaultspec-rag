---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S07'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-namespace-hygiene with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S07 and 2026-07-14-storage-namespace-hygiene-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Integration-test the live daemon serving the cached survey after warmup and recomputing on fresh=true and ## Scope

- `src/vaultspec_rag/tests/integration/test_storage_survey_service.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Integration-test the live daemon serving the cached survey after warmup and recomputing on fresh=true

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`

## Description

- Add three live-daemon tests to `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`: freshness metadata present, cache served after warmup with stable `computed_at`, and `?fresh=true` recomputing then reseeding the cache
- Update `test_storage_survey_root_lookup_indexed_root` to query with `fresh=true`, matching the ADR's eventual-consistency contract for just-indexed roots

## Outcome

The warmup, cache, and recompute paths are exercised against a real daemon end to end.

## Notes

Run was deferred until the parallel session released the GPU (card was at 15.5/16.3 GB). Full module then passed: 11/11 in 409s, including the pre-existing envelope/root-lookup tests.
