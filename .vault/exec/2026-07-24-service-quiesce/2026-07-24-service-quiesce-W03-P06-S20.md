---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:6b9788596d8b1f0e2efac4f96e1aa7010ed0feaecac286fa1b73ee479995416a'
step_id: 'S20'
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
     The S20 and 2026-07-24-service-quiesce-plan placeholders are machine-filled by
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
     The Publish the canonical quiesce block through existing health, jobs, and lifecycle heartbeat cadence without adding a poller, duplicating controller computation, or importing GPU dependencies and ## Scope

- `src/vaultspec_rag/server/_lifespan.py`
- `src/vaultspec_rag/server/_routes.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Publish the canonical quiesce block through existing health, jobs, and lifecycle heartbeat cadence without adding a poller, duplicating controller computation, or importing GPU dependencies

## Scope

- `src/vaultspec_rag/server/_lifespan.py`
- `src/vaultspec_rag/server/_routes.py`

## Description

Project the current canonical controller envelope through the existing health
and jobs request cadence. Read one registry snapshot for each response and
reuse `QuiesceSnapshot.as_envelope` without a new poller or local lifecycle
recomputation.

## Outcome

Satisfied jointly by `04660476` and `9fc85828`. Health and jobs now publish the
same twelve-field quiesce block directly from the registry controller.
Checked-in CPU route guards cover running, quiesced, and resumed observations.

## Notes

The implementation adds no GPU dependency and no lifecycle polling loop. This
was static acceptance only; no runtime or static gate was rerun.
