---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S08'
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
     The S08 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Separate conventional source admission from the parser and chunker capability registry and ## Scope

- `src/vaultspec_rag/indexer/_chunking.py`
- `src/vaultspec_rag/indexer/_content_policy.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Separate conventional source admission from the parser and chunker capability registry

## Scope

- `src/vaultspec_rag/indexer/_chunking.py`
- `src/vaultspec_rag/indexer/_content_policy.py`

## Description

- Verify the parser capability registry remains complete for explicitly admitted content.
- Verify the conventional source profile uses its own narrower extension vocabulary.
- Verify parser selection occurs only after the shared classifier admits a path.

## Outcome

Default code membership is independent from parser availability. Ambiguous text and schema
formats require explicit caller routing while explicitly admitted content still receives the
available parser or generic text fallback.

## Notes

Reconciled from production commit `b4145fc`; no additional code change was required.
