---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S21'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S21 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
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
     The Add the exact canonical quiesce block to read-only service-state output by projecting the registry controller snapshot once and ## Scope

- `src/vaultspec_rag/api.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the exact canonical quiesce block to read-only service-state output by projecting the registry controller snapshot once

## Scope

- `src/vaultspec_rag/api.py`

## Description

Add the current controller snapshot to the canonical read-only service-state
projection. Render it once through `QuiesceSnapshot.as_envelope` beside the
existing project, watcher, and storage state.

## Outcome

Satisfied by `04660476`. The service-state payload carries the exact same
twelve-field controller vocabulary as health, with no duplicated state
derivation.

## Notes

The checked-in projection guard was inspected but not executed during this
acceptance. No service, RAG, CUDA, GPU, lint, or type-check command was run.
