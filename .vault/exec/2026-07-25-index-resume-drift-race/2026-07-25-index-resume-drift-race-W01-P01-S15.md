---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S15'
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
     The S15 and 2026-07-25-index-resume-drift-race-plan placeholders are machine-filled by
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
     The Cover the drift-detection predicate with direct tests before it moves across a seam, since it currently has no test of its own and only its remedy is exercised and ## Scope

- `src/vaultspec_rag/indexer/_run_checkpoint.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Cover the drift-detection predicate with direct tests before it moves across a seam, since it currently has no test of its own and only its remedy is exercised

## Scope

- `src/vaultspec_rag/indexer/_run_checkpoint.py`

## Description

- Confirm by search and by grep that the drift predicate had no coverage, direct
  or indirect.
- Cover it with five tests against a real ledger on real SQLite, using the
  module's existing fixture.
- Determine the undocumented absent-path behaviour by reading the code rather
  than assuming it.
- Prove each test can fail, by a mutation targeting the specific clause it pins.
- Repair a pre-existing defect in the shared segment helper that the new tests
  exposed.

## Outcome

The predicate that decides which resumed paths have drifted is now covered, so a
seam can move it with a signal that its behaviour survived. Coverage was
genuinely absent beforehand: the only ledger-side tests exercise the primitive it
delegates to, not the predicate itself.

The five clauses pinned are that a drifted path is reported mapped to the digest
recorded when it was indexed rather than the digest observed now, that an
unchanged path is not reported, that a path with no indexed evidence is never
reported across three distinct shapes of missing evidence, that a fresh
generation reports nothing, and that an indexed path absent from the observed
digests is not reported.

**The absent-path clause is the one worth keeping.** It was undocumented, and
reading established that the lookup is scoped to the supplied keys, which is also
why the mapping subscript can never raise. That scoping is load-bearing rather
than incidental: the sole caller deliberately narrows to the paths this run
re-ingests, because re-opening anything else would drop its points without
republishing them. A refactor that widened the lookup to every recorded path
would therefore be silently destructive, and the mutation proving that clause
catches exactly this.

Each test was proven able to fail against a mutation aimed at its own clause -
mapping to the observed digest instead of the recorded one, inverting the
comparison, dropping the indexed-state filter, leaking scope beyond the supplied
keys, and inverting the iteration so unrecorded paths read as drift. Every
mutation produced the expected failure, and every file was restored and verified
byte-identical.

A pre-existing defect in the shared segment helper surfaced during the work: it
minted chunk identities independent of the path, so any test indexing two paths
in one generation collided on point ownership. Repairing the helper rather than
working around it in one test removes a trap that would have caught every future
multi-path test.

Gates: lint clean, type check reports zero errors, warnings and notes, citation
gate clean. Checkpoint, ledger, and indexer unit suites pass together at 140
tests.

## Notes

The predicate's docstring reads more strongly than the code supports. It
describes a fresh generation as reporting nothing, which is true only because a
fresh generation carries no recorded evidence; the predicate is scoped to a
generation, not to a resume, so a path indexed and then queried with a different
digest inside the same fresh generation is reported. The tests pin the honest
behaviour and do not encode the stronger reading. The docstring was deliberately
left unchanged, as amending it is a separate decision.

Verification of this Step was blocked for a period by a concurrent extraction in
the same worktree, which removed an import while relocating the classes that used
it and left the import chain broken. The failure appeared in these tests at
collection and was traced to that in-flight move rather than attributed here. The
underlying misjudgement was dispatching two agents into one worktree on the
reasoning that they targeted different files; different files still share an
import graph, and a half-finished move breaks collection for everything on that
chain.
