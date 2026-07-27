---
tags:
  - '#exec'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S07'
related:
  - "[[2026-06-01-module-split-plan]]"
---

# Split canonical process-probe guard domains into directly collected test modules and concrete shared helpers

## Description

### Scope

- `src/vaultspec_rag/tests/test_process_probe_canonical.py`

- Replaced the overlength collector with six behavior-domain guard modules.

- Extracted one concrete source-scan helper module.

- Recovered the bounded interrupted transfer without replacing the working file from Git.

- Removed the duplicate collector after the audit verified all test identities moved.

## Outcome

Focused collection reports 116 tests. The focused run passes 115 tests with one
platform-gated skip; Ruff check and format check pass for all replacement files.

## Notes

The original working copy contained uncommitted content beyond `HEAD`. Only two
verified missing transfer spans were reconstructed from read-only baseline text;
the audit verified that no test identity was lost.

### History evidence

No committed history is available for this path. Source: git log --follow --format=%H -- path returned no commits.
