---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S27'
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
     The S27 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
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
     The Atomically publish metadata from ledger rows and preserve the last valid sidecar until replacement and ## Scope

- `src/vaultspec_rag/indexer/_code_meta.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Atomically publish metadata from ledger rows and preserve the last valid sidecar until replacement

## Scope

- `src/vaultspec_rag/indexer/_code_meta.py`

## Description

- Stream unique ordered ledger file states into a generation-specific temporary sidecar.
- Flush and fsync the complete JSON document before atomic replacement.
- Preserve the previous valid sidecar when iteration, validation, serialization, or replacement fails.
- Advance metadata publication only after the atomic replacement returns successfully.

## Outcome

Code metadata publication is atomic, row-streamed, generation-stamped, and retry-safe. Concurrent attempts use distinct temporary files, and an incomplete publication cannot replace or delete the last valid sidecar.

## Notes

The implementation landed earlier in the shared ledger integration and was reconciled here with P07 finalization. Real SQLite tests verified converged-row filtering, failure preservation, and overlapping atomic publications; the final P06 gate also exercised the integrated full and incremental paths.
