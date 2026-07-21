---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S04'
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
     The S04 and 2026-07-21-service-job-control-plan placeholders are machine-filled by
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
     The Define immutable job specifications, canonical states, capabilities, revisions, attempt lineage, and structured outcomes using vaultspec-high-executor and ## Scope

- `src/vaultspec_rag/jobs.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define immutable job specifications, canonical states, capabilities, revisions, attempt lineage, and structured outcomes using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Define canonical operation, source, mode, observed-state, desired-state, resume-strategy, and outcome vocabularies.
- Add frozen specifications, capabilities, initiator, attempt-lineage, timestamp, progress, runtime, and resource snapshot types.
- Add immutable exact-ID job snapshots and structured command outcomes with JSON-ready serialization.
- Preserve every legacy record, persistence, callback, and background-dispatch function without behavior changes.
- Verify the type layer with Ruff, `ty`, strict BasedPyright, and existing job-registry behavior.

## Outcome

The service domain now has an immutable canonical resource representation for future
manager transitions and adapters. Its serialization exposes the accepted revision,
attempt lineage, desired and observed states, control timestamps, capabilities, runtime,
resources, progress, result, and stable outcome envelope while legacy consumers continue
to receive their existing dictionary records.

## Notes

All jobs unit behavior passed. The integration registry run completed 41 tests overall;
its two live-service cases could not enter the test body because the concurrently changing
shared tree lacked the unrelated `read_service_log` import required by service startup.
No S04 assertion failed. Concurrent branch activity required committing the production
type layer before this traceability record was attached.
