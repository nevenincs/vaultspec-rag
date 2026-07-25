---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S13'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-conformance with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S13 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Pair the conformance degradation with its rebuild remediation command in the existing degraded-family registry and ## Scope

- `src/vaultspec_rag/cli/_status_labels.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Pair the conformance degradation with its rebuild remediation command in the existing degraded-family registry

## Scope

- `src/vaultspec_rag/cli/_status_labels.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

A `conformance` family paired with `vaultspec-rag index --rebuild --type all`,
and the structured `nonconforming` signal added to the health payload so the
remediation is derived from the signal rather than parsed out of the prose.

Two things were corrected here after mutation runs contradicted the first
version, and both are recorded in the tests rather than quietly fixed:

Asserting that a conformance finding merely *appears* is inert. When a reason
pairs with no signal the renderer's unclaimed sweep appends the family's finding
anyway, so the family is present even when the wrong command is attached to the
conformance cause. The tests now assert which command lands on which cause.

The family ordering is defensive, not load-bearing. Reasons resolve in the order
the health author emits them, and the models reason is emitted first, so it
claims the `model` stem before the conformance reason is reached - no reachable
input distinguishes the two orderings. The comment at the registry now says
exactly that instead of claiming a protection no test can demonstrate. Ordering
is kept because it costs nothing and holds if either reason is reworded.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
