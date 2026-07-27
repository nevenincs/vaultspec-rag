---
tags:
  - '#exec'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S08'
related:
  - "[[2026-06-01-module-split-plan]]"
---

# Split installation integration behavior domains into directly collected modules

## Description

### Scope

- `src/vaultspec_rag/tests/integration/test_install.py`

- Replaced the installer test monolith with nine direct behavior-domain modules.

- Extracted concrete install helpers and package-level fixture registration.

- Restored the five Windows junction and reparse safety scenarios identified by review.

## Outcome

The direct suite contains the original 102 test methods and passes 183 collected
cases without fixture-registration warnings. Ruff check, format check, and
whitespace validation pass.

## Notes

The audit initially found five lost Windows-only safety scenarios and late
fixture-plugin registration. Both were repaired and independently re-audited.

### History evidence

No committed history is available for this path. Source: git log --follow --format=%H -- path returned no commits.
