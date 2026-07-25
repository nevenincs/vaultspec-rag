---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S09'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace index-resume-drift-race with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S09 and 2026-07-25-index-resume-drift-race-plan placeholders are machine-filled by
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
     The Route the drift signal to the drift owner so it supersedes the racing path and the run re-records it instead of aborting and ## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Route the drift signal to the drift owner so it supersedes the racing path and the run re-records it instead of aborting

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Catch the typed collision where one store mutation is recorded, ask the
  drift owner to supersede the racing path, and record the same units again.
- Re-raise the collision unchanged when its digests are equal, because that is
  a caller defect rather than a moving tree.
- Turn the recording helper into an instance method so it can reach the owner.
- Reproduce the reported failure as a test before fixing it.

## Outcome

The reported failure is fixed and reproduced. A generation carrying indexed
evidence for a path at one digest, handed units for the same path at another,
used to raise out of the recording call and fail the entire job. It now
supersedes the path and records the units, and the run continues.

The reproduction is a real one. Nothing on the path under test is doubled: a
real store holds real points, the real ledger raises the collision, and the
remedy deletes real identities. The only thing absent is the encode, which
this seam never performs - it records what an encode already stored.

The equal-digest case is deliberately left alone. Equal digests mean the
caller re-submitted content this generation already committed under new point
identities, which no amount of superseding fixes and which a repair would turn
into an endless silent republish. That branch re-raises, and a test proves it
still does.

The handler distinguishes the two by the drift predicate the collision type
carries rather than by its message, because every branch of the guard shares
one message and a message match would pass whichever fired.

Gates: lint clean, format clean, type check reports no diagnostics, and the
drift, checkpoint and ledger suites pass at 36 tests.

## Notes

The recording helper was static and reached through a partial. Making it an
instance method left the partial correct unchanged, because the bound method
already carries the instance.

The residual window between the pre-record check and the ledger insert is what
this handler exists for. It is exercised by handing the handler the genuine
exception the ledger raises, obtained by driving the guard directly, rather
than by racing two threads and hoping for the interleaving.
