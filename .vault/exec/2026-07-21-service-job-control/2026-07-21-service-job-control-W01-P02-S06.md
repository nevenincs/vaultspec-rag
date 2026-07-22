---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S06'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S06 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Implement revisioned pause, resume, cancellation, retry, terminal deletion, first-terminal-writer-wins, and deterministic races using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/jobs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement revisioned pause, resume, cancellation, retry, terminal deletion, first-terminal-writer-wins, and deterministic races using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Add revisioned pause, resume, cancellation, retry, and terminal-deletion commands.
- Bind runtime ownership and observed-state acknowledgements to the exact task and attempt.
- Make cancellation absorbing and protect terminal state with first-terminal-writer-wins.
- Gate retry and deletion on complete runtime and execution-resource release.
- Serialize dispatch, control delivery, withdrawal, completion, and replacement races.

## Outcome

The durable job manager now exposes deterministic lifecycle transitions over immutable
snapshots. Stale revisions, tasks, and attempt generations cannot mutate replacement work;
pause withdrawal and delivery have one atomic ordering; cancellation cannot be reversed; and
terminal completion, retry, and deletion preserve resource-release and retention invariants.

## Notes

Independent review found two High defects: a stale dispatcher could claim queued work after a
pause committed, and a stale attempt generation could seize or release a replacement runtime.
Both were corrected with atomic dispatch-state gating and exact task-plus-attempt ownership.
Final review found no unresolved findings at any severity. Forty-nine focused tests, exact
production probes, two 200-iteration threaded race probes, Ruff, ty, BasedPyright, and diff
checks passed.

The legacy live-service registry tests were also attempted. Their 49 unit assertions passed,
but the live fixture stopped before job assertions because the Windows Qdrant process-image
witness exhausted its bounded inspection path. That fixture-level failure is separate from
this Step and remains visible for follow-up verification.
