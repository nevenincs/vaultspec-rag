---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S37'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace large-index-resilience with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S37 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Expose ledger commit units, protected spans, and typed safety signals through the run-policy safe-point contract and ## Scope

- `src/vaultspec_rag/indexer/_run_policy.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Expose ledger commit units, protected spans, and typed safety signals through the run-policy safe-point contract

## Scope

- `src/vaultspec_rag/indexer/_run_policy.py`

## Description

- Expose labeled protected spans through the checkpoint-owned run policy.
- Check liveness and pending control at each protected-span entry and exit.
- Route clean publication and incremental replacement through the same authority that records ledger commits and finalization progress.
- Preserve typed no-progress and cooperative control signals without acknowledging inside indivisible mutations.

## Outcome

Ledger progress, storage retry budget, protected publication, and cooperative control now share one run-policy authority. Replacement spans defer control until their durable exit while ordinary bounded waits remain interruptible.

## Notes

The real-token run-policy suite passed 17 cases, including protected cancellation, deadline latching, bounded queue operations, cleanup delivery, and thread joins. Static type checking passed; the single style finding was corrected before commit.
