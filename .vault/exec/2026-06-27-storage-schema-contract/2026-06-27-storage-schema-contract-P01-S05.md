---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S05'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-schema-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S05 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Unit-test the descriptor shape and the compatibility helper across match and mismatch cases and ## Scope

- `src/vaultspec_rag/tests/test_store_schema.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Unit-test the descriptor shape and the compatibility helper across match and mismatch cases

## Scope

- `src/vaultspec_rag/tests/test_store_schema.py`

## Description

- Authored `test_store_schema.py` with `TestDescriptor` (version, collections, effective dense vector, payload-fields-match-TypedDicts, indexes-match-tuples, JSON-serialisable) and `TestAssertCompatible` (match, older-version, newer-version-degrades, dimension-mismatch-refuses, missing-dense-refuses, non-integer-version, live-descriptor-self-compatible).
- Added `test_store_schema_imports_no_torch`: a fresh-interpreter subprocess asserting `import vaultspec_rag.store_schema` leaves torch out of `sys.modules`, mirroring the index-worker and MCP lazy-import guards.

## Outcome

13 tests pass. The descriptor and compatibility helper are covered across match and mismatch cases, and the torch-free invariant is regression-guarded.

## Notes

No mocks/patches used; the descriptor reads real config. Pre-existing `pytest_durations` deprecation warning is unrelated.
