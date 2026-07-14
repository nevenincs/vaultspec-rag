---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S06'
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
     The S06 and 2026-07-14-storage-namespace-hygiene-plan placeholders are machine-filled by
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
     The Unit-test snapshot swap semantics, cached-list filtering, and freshness metadata alongside the routes tests and ## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Unit-test snapshot swap semantics, cached-list filtering, and freshness metadata alongside the routes tests

## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py`

## Description

- Add `TestSurveySnapshot` (cold read, publish/read roundtrip, whole-snapshot replacement) and `TestGatherStorageSurveyCached` (cache hit never opens a client, filters/limit on the cached list, fresh recompute republishes, cold-cache fallback) to `src/vaultspec_rag/tests/test_storage_ops.py`
- Isolate each test with a `cold_snapshot` fixture that monkeypatches the slot to `None`

## Outcome

8 new unit tests; the cache-hit test proves the walk is skipped by making `_fetch_surveys` raise. Full unit tier: 1363 passed. Commit 7ae79ca.

## Notes

None.
