---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S42'
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
     The S42 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Enforce hardware and backend profile admission at service job submission before GPU work and ## Scope

- `src/vaultspec_rag/jobs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Enforce hardware and backend profile admission at service job submission before GPU work

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Validate the configured code profile against immutable preflight measurements.
- Check backend, total RAM, and free disk before durable job creation.
- Revalidate managed attempts before model loading and GPU work.
- Preserve stable typed admission reasons through the HTTP jobs boundary.

## Outcome

Code job submission now fails before durable creation when its backend, host, disk, or source corpus is unsupported. Accepted work carries the exact preflight authority into dispatch, while generated-work ceilings remain enforced incrementally before queue admission.

## Notes

HTTP maps profile and corpus refusals to structured 422 responses and disk preflight failure to 507. A refused request leaves the canonical job manager empty.
