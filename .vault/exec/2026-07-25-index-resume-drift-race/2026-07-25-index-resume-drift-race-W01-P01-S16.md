---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S16'
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
     The S16 and 2026-07-25-index-resume-drift-race-plan placeholders are machine-filled by
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
     The Repair the test construction pattern that bypasses the indexer constructor, so a collaborator can be held as constructor state instead of rebuilt per access and ## Scope

- `src/vaultspec_rag/tests/test_indexer_unit.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Repair the test construction pattern that bypasses the indexer constructor, so a collaborator can be held as constructor state instead of rebuilt per access

## Scope

- `src/vaultspec_rag/tests/test_indexer_unit.py`

## Description

- Replace every constructor bypass in the indexer unit tests with real
  construction through a single scan-only helper.
- Repair the same pattern at the three sites outside the named scope that
  copied it, since one survivor is enough to keep the constraint in place.
- Capture the discovery collaborator at construction now that nothing depends
  on assembling an indexer attribute by attribute.

## Outcome

Fourteen sites in the unit tests, plus one each in the chunk-worker parity
tests, the preprocess batch tests, and the chunking benchmark, built an
indexer with `__new__` and then assigned a hand-picked subset of attributes.
That pattern is what forced the discovery collaborator to be rebuilt on every
access: a value captured in the constructor is simply absent on an object
whose constructor never ran, so the accessor had to reconstruct it from
`getattr` defaults each time.

All eighteen now construct for real, leaving only the embedding model and the
store unbound, which is honest because scanning and chunking touch neither.
The scan-only helper says so in its docstring, so the next reader knows which
two dependencies are deliberately absent rather than accidentally missing.

With that gone, the discovery accessor became constructor state and the
property disappeared. Discovery is now assembled once per indexer from the
same three inputs it always used, instead of once per call.

The step's scope named only the indexer unit tests. Repairing that file alone
would have left the pattern intact in three others and the constraint fully in
force, so the step would have delivered nothing. The extra three are the same
mechanical change.

Gates on the changed scope: lint clean, format clean, type check reports no
diagnostics, and the three affected suites pass at 151 tests.

## Notes

The chunk-worker parity and preprocess-batch helpers had docstrings
advertising the bypass as "the established unit-test pattern". Those were
rewritten rather than deleted, because an unexplained pair of unbound
dependencies invites the next reader to bind them.
