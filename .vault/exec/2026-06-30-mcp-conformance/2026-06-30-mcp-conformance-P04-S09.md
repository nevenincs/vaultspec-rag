---
tags:
  - '#exec'
  - '#mcp-conformance'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S09'
related:
  - "[[2026-06-30-mcp-conformance-plan]]"
---

# Add outputSchema and structuredContent and a stable return shape to the search tools

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

Narrowed the search tools to one stable return shape.

## Outcome

A bare legacy hit list is wrapped under `results` (`_as_envelope`), so clients validate against a single dict shape instead of the prior `dict | list` union. A fully typed `outputSchema` model is a documented follow-up; the stable shape is the conformance-load-bearing change.

## Notes

Search tools now annotate `-> dict[str, Any]`.
