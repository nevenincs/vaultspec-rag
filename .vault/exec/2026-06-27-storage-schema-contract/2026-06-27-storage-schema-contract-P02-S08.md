---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S08'
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
     The S08 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Consume the schema index tuples in ensure_table and ensure_code_table instead of inline literals and ## Scope

- `src/vaultspec_rag/store.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Consume the schema index tuples in ensure_table and ensure_code_table instead of inline literals

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Replaced the inline KEYWORD/INTEGER field literals in `ensure_table` with iteration over `store_schema.VAULT_KEYWORD_INDEXES` and `VAULT_INTEGER_INDEXES`.
- Replaced the inline field literals in `ensure_code_table` with `store_schema.CODE_KEYWORD_INDEXES` and `CODE_INTEGER_INDEXES`, preserving the explanatory comments about node_type and the preprocessing locators.

## Outcome

The payload index sets are created from the single declared source; the P04 drift test asserts the live collection's indexed fields equal these tuples.

## Notes

None.
