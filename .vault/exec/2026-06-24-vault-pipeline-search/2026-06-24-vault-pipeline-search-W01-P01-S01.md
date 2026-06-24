---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S01'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Author the graded-relevance rubric table keyed on intent x doc_type x status

## Scope

- `src/vaultspec_rag/tests/quality/rubric.py`

## Description

- Created the `tests/quality` evaluation-support package with a package docstring
  distinguishing it from test modules.
- Authored `rubric.py`: an `Intent` StrEnum (orientation, debugging, implementation), the
  active vs inactive ADR-status frozensets (unknown counts as active), and a declarative
  intent x role grade matrix resolved from the ADR D8 table.
- Exposed `grade_for(intent, doc_type, status, *, on_topic)` returning a 0-3 grade, with a
  `_role_key` helper that splits ADRs on active/inactive status and maps every other type
  directly; off-topic and unknown roles score 0.
- Fixed lint (StrEnum over str+Enum, sorted `__all__`); type-check clean.

## Outcome

The rubric is a pure, importable module. Verified by smoke test: orientation grades an
accepted ADR 3 and the implementing exec record 1 (the inversion the rework targets); a
superseded ADR drops to 1; debugging grades exec 3; off-topic is 0. `ruff` and `ty` pass.

## Notes

Grade ranges documented in the ADR (exec orientation "0-1", adr-inactive debugging "0-1")
were pinned to single integers (1 in both cases), recorded in module comments. No blockers.
