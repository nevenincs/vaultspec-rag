---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S17'
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
     The S17 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Add the document collection, payload indexes, schema-version contract, descriptor entry, and direct-consumer compatibility behavior and ## Scope

- `src/vaultspec_rag/store_schema.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the document collection, payload indexes, schema-version contract, descriptor entry, and direct-consumer compatibility behavior

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

- Define the document collection name, payload fields, indexes, and ID scheme.
- Advertise document vectors and payload schema in the storage descriptor.
- Advance the schema generation and add opt-in domain requirements to compatibility checks.

## Outcome

Storage schema version 2 advertises an independently addressable document
collection. Older consumers fail safely on the newer generation, while newer
consumers can detect an older descriptor that lacks the required document domain.

## Notes

Formatting, lint, type checks, descriptor serialization, version refusal, and
required-domain compatibility probes passed.
