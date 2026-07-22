---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `code-document-index-boundary` audit: `S17 document storage schema`

## Scope

Reviewed the additive document collection descriptor, payload/index contract,
schema-version transition, and opt-in direct-consumer compatibility gate.

## Findings

No findings.

## Recommendations

Require the `document` domain explicitly at direct-consumer boundaries that
depend on document storage, while preserving legacy vault-only checks.
