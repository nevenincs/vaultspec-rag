---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S29'
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
     The S29 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Define a versioned extractor invocation envelope with canonical source identity, normalized options, configured version, target, and mode and ## Scope

- `src/vaultspec_rag/indexer/_preprocess_schema.py`
- `src/vaultspec_rag/indexer/_preprocess_config.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define a versioned extractor invocation envelope with canonical source identity, normalized options, configured version, target, and mode

## Scope

- `src/vaultspec_rag/indexer/_preprocess_schema.py`
- `src/vaultspec_rag/indexer/_preprocess_config.py`

## Description

- Define a frozen, versioned invocation envelope with canonical project-relative identities, normalized options, configured extractor version, target, and execution mode.

## Outcome

Command and entry-point extractors now receive one deterministic host-owned envelope.

## Notes

The envelope is delivered through a curated environment variable and can be loaded through the public schema helper.
