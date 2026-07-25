---
tags:
  - '#exec'
  - '#citation-gate-coverage'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S01'
related:
  - "[[2026-07-25-citation-gate-coverage-plan]]"
---

# Widen the dated-stem pattern to any dated kebab stem and citation-scan the tooling surface

## Scope

- `tools/citation_gate.py`

## Description

- Establish empirically that the docstring walk was never the defect: the AST
  visit already reports line one of every module, so module, class and function
  docstrings were all being scanned.
- Drop the document-type suffix requirement from the dated-stem pattern and
  require instead that the stem tail contain a letter.
- Walk the tooling surface for citations, not only for workstation-path leaks,
  keeping the gate's own source as the sole exemption.
- Thread the repository and tooling roots through the scan entry points as
  parameters defaulting to the live checkout.

## Outcome

The gate fails on a bare dated stem in any prose surface, and on a citation
anywhere in the tooling surface. The scan can be pointed at a throwaway tree, so
its red direction is demonstrable rather than merely asserted.

The reported symptom and the actual defect were different. The issue proposed
the module-docstring walk as the likely hole; a probe against the live file
showed the walk reporting the module docstring correctly, and the escape was
instead the pattern's requirement of a trailing `-adr`/`-plan` segment. A fix
aimed at the reported symptom would have shipped a green gate over an unchanged
hole.

## Notes

A second, unreported hole surfaced while confirming the first: the tooling
surface was walked for path leaks only, so a citation there was structurally
unreachable by the gate. It was harbouring one.
