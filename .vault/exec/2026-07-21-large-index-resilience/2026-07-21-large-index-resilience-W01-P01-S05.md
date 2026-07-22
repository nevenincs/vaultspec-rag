---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S05'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

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
