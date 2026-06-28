---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S15'
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
     The S15 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Author the storage-schema reference document with the field tables, version-bump policy, and consumer compatibility recipe and ## Scope

- `.vault/reference/2026-06-27-storage-schema-contract-reference.md` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Author the storage-schema reference document with the field tables, version-bump policy, and consumer compatibility recipe

## Scope

- `.vault/reference/2026-06-27-storage-schema-contract-reference.md`

## Description

- Scaffolded the reference via `vaultspec-core vault add reference` and authored the contract body: collection/namespacing, the vector table, the per-collection payload field lists, the server-mode payload indexes, the point-ID schemes, the version-bump policy, the runtime advertisement surfaces, the consumer compatibility recipe, the clean-reindex recovery, and the source/test map.
- Named `store_schema.py` as the single source of truth and the four test files that hold the guarantees.

## Outcome

The dashboard team (and any future direct-Qdrant consumer) has a machine-facing contract to build against, with the version-bump policy and the assert-before-read recipe spelled out.

## Notes

Authored, not generated (ADR D5); a generated-from-the-typed-definition reference is recorded as a possible later hardening.
