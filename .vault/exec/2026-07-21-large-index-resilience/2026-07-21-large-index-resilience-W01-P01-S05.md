---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S05'
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
     The S05 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Verify production configuration and deliberately low resource budgets through imported behavior and ## Scope

- `src/vaultspec_rag/tests/test_config.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Verify production configuration and deliberately low resource budgets through imported behavior

## Scope

- `src/vaultspec_rag/tests/test_config.py`

## Description

- Verify all seventeen resilience settings through production defaults, environment mappings,
  coercion, result types, interval boundaries, and cross-field constraints.
- Exercise exact-low RSS and CUDA ceilings through the production `MemoryBudget` API.
- Prove typed RSS precedence, first-failure latching, and allocated-versus-reserved CUDA
  enforcement.
- Prove configured RSS and CUDA observation failures fail closed in real site-disabled child
  interpreters.

## Outcome

The production configuration contract now has direct regression coverage for every new
setting, including all admitted endpoints and invalid values. Deliberately low resource
ceilings produce the intended typed outcomes, retain the first violating snapshot, and fail
closed when the operating-system or CUDA measurement source is unavailable.

## Notes

Independent review found one Medium gap in the first revision: the suite rejected values
outside the fractional intervals but did not prove acceptance of jitter `0.0` and `1.0` or
CUDA allocator fraction `1.0`. Those included endpoints were added without weakening the
existing rejection coverage.

Final review found no unresolved findings. The complete focused file passed with 106 tests;
an independent slice of 45 focused cases plus six explicit rejection-boundary cases also
passed. Ruff, formatting, ty, BasedPyright, prohibited-test-pattern, and diff checks passed.
