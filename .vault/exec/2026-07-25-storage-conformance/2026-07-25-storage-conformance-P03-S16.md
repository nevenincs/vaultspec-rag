---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S16'
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
     The S16 and 2026-07-25-storage-conformance-plan placeholders are machine-filled by
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
     The Cover the degradation surfacing with a guard test, and prove it fails when the reason is dropped and ## Scope

- `src/vaultspec_rag/tests/test_server_routes.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Cover the degradation surfacing with a guard test, and prove it fails when the reason is dropped

## Scope

- `src/vaultspec_rag/tests/test_server_routes.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

## Outcome

Six tests over the health author and the remediation pairing.

| Mutation | Observed failure |
| --- | --- |
| health drops the conformance branch | `assert 'ready' == 'degraded'` |
| conformance family unregistered | `assert '--rebuild' in ''` |
| models family unregistered | `assert '' == 'models'` |
| finding built from an empty list | fails on the no-finding assertion |
| reason omits the collection names | `assert False` |

Restored: `6 passed`. Wider check across the identity, surfacing, serving-verdict
parity, and survey modules: `36 passed`.

Three mutation attempts stayed green before the tests were re-anchored, and each
exposed a real defect in the test rather than in the code. Two asserted family
presence, which the unclaimed sweep satisfies regardless; one asserted a family
ordering that no reachable input exercises. A guard test that cannot fail is
worse than no test, so the assertions were moved onto cause-to-command pairing,
which a mutation can actually break, and the ordering claim was withdrawn rather
than defended by an assertion that would always pass.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->
