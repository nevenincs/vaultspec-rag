---
tags:
  - '#audit'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-lint-defaults-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace lint-defaults with a kebab-case feature tag, e.g. #foo-bar.
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

# `lint-defaults` audit: `atomic write migration`

## Scope

Review the `JsonWriteOptions` migration for the atomic JSON publication path and
its real production callers before completing the first lint-defaults step.

## Findings

### options-regression-coverage | medium | Non-default serialization and durability choices lack direct coverage

The migration preserves the call-site values, but the atomic-write tests currently
exercise only default options. Add real filesystem coverage that proves `indent`,
`sort_keys`, `compact`, and `durable` still reach serialization and durable
publication through `JsonWriteOptions`.

### options-regression-coverage | resolved | Test claims now match observable behavior

The focused real-filesystem test proves non-default serialization and temporary-file
cleanup. It exercises the durable production path without claiming a flush guarantee
that cannot be observed without fault injection or patching.

## Recommendations

No further action is required for this migration.
