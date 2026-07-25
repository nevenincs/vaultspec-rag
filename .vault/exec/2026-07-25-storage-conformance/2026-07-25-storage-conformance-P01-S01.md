---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S01'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace storage-conformance with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S01 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Record the pre-change suite baseline and the current manifest record shape so later regressions stay attributable and ## Scope

- `src/vaultspec_rag/tests/` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
