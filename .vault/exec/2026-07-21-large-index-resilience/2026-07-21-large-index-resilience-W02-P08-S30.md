---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S30'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace large-index-resilience with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S30 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Invalidate incompatible checkpoints on model, schema, content, membership, preprocessing, and configuration drift and ## Scope

- `src/vaultspec_rag/tests/test_config_epoch.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Invalidate incompatible checkpoints on model, schema, content, membership, preprocessing, and configuration drift

## Scope

- `src/vaultspec_rag/tests/test_config_epoch.py`

## Description

- Exercise the canonical generation signature against model, dimension, embedding-schema, payload-schema, content-epoch, membership-epoch, preprocessing, and pipeline-configuration drift.
- Require each incompatible signature to create a distinct generation and invalidate the prior active attempt before reuse.
- Retain the existing content and membership escalation matrix over real resolved policy snapshots.

## Outcome

Checkpoint reuse now has a closed verification matrix across every content- or storage-shaping identity required by the accepted compatibility contract. No incompatible attempt can authorize skipped work.

## Notes

The complete config-epoch and signature suite passed 31 tests. Ruff and ty passed for the changed test module.
