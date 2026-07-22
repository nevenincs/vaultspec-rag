---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S16'
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
     The S16 and 2026-07-22-code-document-index-boundary-plan placeholders are machine-filled by
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
     The Implement collection-local document point identities from normalized source, native locator or unit ordinal, and content fingerprint and ## Scope

- `src/vaultspec_rag/indexer/_document_identity.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement collection-local document point identities from normalized source, native locator or unit ordinal, and content fingerprint

## Scope

- `src/vaultspec_rag/indexer/_document_identity.py`

## Description

- Normalize caller-provided source paths to safe project-relative POSIX identities.
- Prefer a native locator when present and fall back to unit ordinal deterministically.
- Hash normalized source, location, and content fingerprint into a versioned document ID.

## Outcome

Document points now have deterministic collection-local IDs that remain stable
across path separator spellings and unit reordering when a native locator exists.
The source-code point identity implementation was not changed.

## Notes

Formatting, lint, type checks, separator normalization, locator stability, and
content/location distinction probes passed.
