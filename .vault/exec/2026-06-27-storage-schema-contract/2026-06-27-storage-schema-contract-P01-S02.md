---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
step_id: 'S02'
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
     The S02 and 2026-06-27-storage-schema-contract-plan placeholders are machine-filled by
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
     The Declare the canonical KEYWORD and INTEGER payload-index field tuples per collection and ## Scope

- `src/vaultspec_rag/store_schema.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Declare the canonical KEYWORD and INTEGER payload-index field tuples per collection

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

- Declared `VAULT_KEYWORD_INDEXES` / `VAULT_INTEGER_INDEXES` and `CODE_KEYWORD_INDEXES` / `CODE_INTEGER_INDEXES` as the canonical per-collection index tuples.
- Matched the tuples field-for-field to the index sets currently created in `ensure_table` and `ensure_code_table`.

## Outcome

The index sets are declared once in the schema module; P02.S08 routes `ensure_table`/`ensure_code_table` to consume them, and the P04 drift test asserts the live collection's indexed fields equal these tuples.

## Notes

None.
