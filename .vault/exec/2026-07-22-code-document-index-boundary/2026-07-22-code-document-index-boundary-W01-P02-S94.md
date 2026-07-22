---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S94'
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
     The S94 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Retain resolved routing when preprocessing execution is disabled and mark affected work stale without deletion or reclassification and ## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`
- `src/vaultspec_rag/indexer/_preprocess_glue.py`
- `src/vaultspec_rag/indexer/_codebase_indexer.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Retain resolved routing when preprocessing execution is disabled and mark affected work stale without deletion or reclassification

## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`
- `src/vaultspec_rag/indexer/_preprocess_glue.py`
- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Retain valid preprocessing rules when execution mode is off.
- Suppress worker context without erasing content ownership.
- Exclude disabled transforms from raw execution and surface them as stale work.
- Preserve published IDs, metadata, and cache state across scoped, unscoped, full, and requested clean reconciliation.

## Outcome

The preprocessing kill switch changes execution only. Matching paths keep their declared
owner, are never raw-reclassified, and retain published state until execution resumes or an
explicit membership policy changes.

## Notes

Static formatting, lint, type, and deletion-safety review passed. Real behavior verification
is consolidated in S95 at the phase boundary.
