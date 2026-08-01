---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
body_hash: 'sha256:3584dbef2e1b1784b71c250300c4b431d6ec15c9e3b82eb44ddc7092709fcd4e'
step_id: 'S01'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Record the pre-change suite baseline and the current manifest record shape so later regressions stay attributable

## Scope

- `src/vaultspec_rag/tests/`

## Description

Measured the pre-change suite so later regressions stay attributable, and read
the manifest record shape the rest of the Phase extends.

The first attempt produced no output: the run was piped through `tail`, which
buffers until the process exits, so progress was unreadable and the run appeared
dead. Re-run without the pipe. Recorded here because the same mistake will
otherwise be repeated at `P05.S21`.

## Outcome

Baseline on the CPU gate - the suite minus integration, quality, performance,
robustness, subprocess-GPU, and CUDA marks:

```
2643 passed, 712 deselected, 10 warnings in 559.59s (0:09:19)
```

Caveat, stated rather than hidden: this run overlapped the first edits of
`P01.S02`. Python binds modules at collection time, so the measured run
exercised the pristine tree, but the figure is a start-of-Phase reading rather
than a frozen-tree one. It is used only as a floor - the closeout run must meet
or exceed it, plus the tests this plan adds.

## Notes

Template evidence: intro_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78; template_commit=bb97c918472220397b2f4b63f5dfbd0549b70a78:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
