---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S04'
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
     The S04 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Implement assert_compatible applying the version, dense-dimension, and dense-vector-name rules and ## Scope

- `src/vaultspec_rag/store_schema.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement assert_compatible applying the version, dense-dimension, and dense-vector-name rules

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

- Implemented `assert_compatible(descriptor, *, known_version, expected_dense_dim, dense_vector_name)` returning a `SchemaCompatibility` verdict.
- Encoded the three contract rules in order: newer-version degrades; missing dense vector name refuses; dense-dimension mismatch refuses; older/equal version with matching dim is compatible.
- Added the `SchemaCompatibility` TypedDict (`compatible`, `reason`) as the verdict shape.

## Outcome

The Python reference implementation of the consumer compatibility contract exists; the Rust consumer applies the same rules against the JSON descriptor. Used by the P03 exposure tests and documented in the P04 reference.

## Notes

A non-integer version is treated as incompatible (defensive against a malformed/old descriptor).
