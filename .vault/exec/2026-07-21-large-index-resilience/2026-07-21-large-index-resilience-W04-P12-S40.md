---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S40'
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
     The S40 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Define named managed-service and embedded-local profiles with benchmark-derived resource and corpus dimensions and ## Scope

- `src/vaultspec_rag/index_profiles.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define named managed-service and embedded-local profiles with benchmark-derived resource and corpus dimensions

## Scope

- `src/vaultspec_rag/index_profiles.py`

## Description

- Define closed managed-service and embedded-local profile names.
- Keep backend, RAM, disk, and corpus limits explicit and immutable.
- Partition source-code and document workload limits by typed index domain.
- Return stable typed refusal reasons for backend, host, disk, and corpus violations.

## Outcome

Index admission now resolves one named support contract with independent code and document dimensions. Unknown profiles and unsupported hosts fail closed through the shared job-error taxonomy.

## Notes

The profile contract landed in commit `4c9fe8cf`. The phase-boundary selection verified exact-limit admission and typed backend, RAM, disk, source, and generated-work refusal.
