---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S18'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S18 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Add document collection locks, upsert, delete, scroll, and count operations and ## Scope

- `src/vaultspec_rag/store.py`
- `src/vaultspec_rag/_store_locks.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add document collection locks, upsert, delete, scroll, and count operations

## Scope

- `src/vaultspec_rag/store.py`
- `src/vaultspec_rag/_store_locks.py`

## Description

- Add a dedicated document collection lock and deterministic multi-lock close order.
- Ensure document vectors and payload indexes independently from vault and code.
- Add document-native upsert, targeted delete, bounded scroll, ID scan, and count operations.

## Outcome

Local Qdrant operations serialize per document collection while server operations
remain backend-concurrent. Document lifecycle methods mutate only the document
collection and expose bounded administrative reads.

## Notes

Formatting, lint, and type checks passed. Real local/server Qdrant verification
is intentionally serialized at the phase boundary.
