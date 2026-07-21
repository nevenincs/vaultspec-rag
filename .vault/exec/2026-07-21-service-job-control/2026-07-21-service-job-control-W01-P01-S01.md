---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S01'
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
     The S01 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Define the thread-safe run-control token, checkpoint signals, protected spans, and no-control implementation using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/job_control.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define the thread-safe run-control token, checkpoint signals, protected spans, and no-control implementation using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/job_control.py`

## Description

- Define the runtime-checkable `RunControl` consumer protocol independently of progress reporting.
- Add dedicated `PauseRequested` and `CancelRequested` cooperative unwind signals.
- Implement a lock-guarded `RunControlToken` with reversible pause, absorbing cancellation, and immutable snapshots.
- Defer requests across nested indivisible spans and deliver them at atomic safe edges without masking application failures.
- Provide the singleton `NO_RUN_CONTROL` implementation for unmanaged callers.
- Verify imported production behavior across real threads and run Ruff, `ty`, and strict BasedPyright checks.
- Complete an independent safety and intent review with no actionable findings.

## Outcome

Indexing code now has a small thread-safe control contract that can observe pause and
cancellation only at explicit safe checkpoints. Protected spans cannot be interrupted
mid-mutation, cancellation cannot be weakened by a later request, and callers without a
managed job retain no-op behavior.

## Notes

Semantic discovery did not become ready within its command deadline, so live-code
grounding continued through targeted `rg` inspection of concurrency, progress, and
indexing exception boundaries. No data was mutated and no scaffold remains in production
code. The plan assigns durable unit-test coverage to `S03`; this Step used a direct
production-import concurrency probe rather than pre-empting that test Step.
