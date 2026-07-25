---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S13'
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
     The S13 and 2026-07-25-index-resume-drift-race-plan placeholders are machine-filled by
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
     The Prove the upsert guard bidirectionally: permit the forbidden write, watch the test fail on its own assertion, restore, watch it pass, and record both directions and ## Scope

- `src/vaultspec_rag/tests/` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove the upsert guard bidirectionally: permit the forbidden write, watch the test fail on its own assertion, restore, watch it pass, and record both directions

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Break each guard in turn, run its test alone, watch it fail on the assertion
  it names, restore, watch it pass.
- Sharpen the non-drift rejection test after its first proof failed on the
  wrong assertion.
- Record both directions here, and comment each mutation at the assertion that
  catches it.

## Outcome

Four proofs, each one uninterrupted, each mutation restored before the next.

The reported failure. Reducing the recording helper to the bare ledger call -
the behaviour before this work - failed the reproduction test with
`RunLedgerIndexedPathCollisionError: cannot add upsert commit units after a
path is indexed: 'src/moving.py'`, which is the reported error verbatim.
Restored, the test passes.

The non-drift rejection. Removing the re-raise for equal digests failed the
test with `DID NOT RAISE RunLedgerIndexedPathCollisionError`. This one needed a
second attempt to be worth anything. The first version placed the replayed
unit at segment ordinal one, so the mutated code repaired the path and then
died on contiguous-ordinal validation: the test failed, but on an unrelated
ledger complaint rather than on the guard it exists to protect. Moving the
replay to ordinal zero makes a wrongly-permitted repair succeed, so the only
way the test can fail is the absence of the rejection. A comment at the
segment says so.

The retry bound. Making the budget predicate always report unspent failed the
deferral test on `deferred_paths == frozenset({'src/moving.py'})`, the exact
assertion the bound exists to satisfy.

The protected identities. Dropping the exclusion of the incoming mutation's
own point identities failed the preservation test on the remaining stored
identities, which came back empty against the expected single identity - the
remedy having deleted the content it was making room for.

After the last restore, the drift, checkpoint and ledger suites pass together
at 36 tests, which is the evidence no mutation outlived its proof.

## Notes

Every assertion proved here names a specific condition rather than a message.
The collision guard shares one message across its branches, so a message match
would pass whichever branch fired and would have proved nothing.

The remaining verification this Phase scopes - a live service against a
genuinely moving tree - was not run and is not attested here. It needs the GPU
and a running service, both of which are shared with other work.
