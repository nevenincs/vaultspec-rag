---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S43'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Drive vaultspec-rag preprocess list/check/run-one against the toy project and capture output (D13)

## Scope

- `vaultspec-rag preprocess (manual)`

## Description

Drove the installed `vaultspec-rag preprocess` verbs against the toy workspace via
`--target`: `check` (OK, 2 rules, exit 0), `list` (Rich table showing both rules with
pattern/command/priority/on_error), `run-one corpus/annual_report.pdf` (status ok, toy-pdf
v1.0.0, 2 units), and `run-one --json` (full validated `PreprocOutput` with page anchors
and locators).

## Outcome

All three verbs behaved exactly as documented; the `--json` envelope carried the validated
output with `#page=` anchors and `locator.kind=page`.

## Notes

Real CLI execution (no pytest) against a real workspace - the authoring/debugging loop a
downstream consumer would use.
