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

- Apply optimistic revisions only when desired state changes; treat same-target retries as successful replays.
- Transition queued and live work through truthful pause, resume, and graceful cancellation states.
- Distinguish a retractable pause from a delivered unwind and requeue reconciliation without exposing a false paused state.
- Bind attempt start, control acknowledgement, and terminal completion to the exact task and attempt number.
- Preserve the first terminal writer, create linked retries for retryable outcomes, and restrict deletion to terminal history.
- Reject force termination explicitly while the thread runtime cannot provide it.

## Outcome

The manager now provides the complete revisioned lifecycle state machine. Pause and
cancellation acknowledge only through the unwind boundary, stale attempt callbacks cannot
rewrite newer work, and retries and deletion preserve immutable terminal history.

## Notes

Ruff, formatting, `ty`, and strict BasedPyright passed. All 49 focused unit tests passed,
and a real asyncio probe exercised immediate pause, pre-delivery resume, post-delivery
resume, cancellation acknowledgement, first-terminal-writer-wins, retry, and deletion.
