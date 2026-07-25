---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S11'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-conformance with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S11 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Cover the three verdicts with guard tests, and prove each fails against a deliberately conforming fixture and ## Scope

- `src/vaultspec_rag/tests/test_store_conformance.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Cover the three verdicts with guard tests, and prove each fails against a deliberately conforming fixture

## Scope

- `src/vaultspec_rag/tests/test_store_conformance.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Four end-to-end tests against a real local-mode collection - local Qdrant runs
in-process, so the create, the stamp, and the geometry read-back are all real
with no service or network - bringing the identity module to 14 tests.

The load-bearing one rewrites the stamp to a different model of identical width
and asserts the reopen reports `nonconforming` without raising. That is the
exact case no epoch, digest, or dimension check can see, reproduced against real
storage.

Mutation proofs:

| Mutation                        | Observed failure                              |
| ------------------------------- | --------------------------------------------- |
| geometry never refuses          | `DID NOT RAISE StorageGeometryError`          |
| any nonconforming refuses       | `StorageGeometryError` on the model-swap case |
| missing stamp scores conforming | `assert 'conforming' == 'unverifiable'`       |

Restored: `14 passed`. Regression check across the store-dependent modules -
store, preprocess store, index reuse, storage ops, donor candidates - `138 passed`.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
