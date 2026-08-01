---
tags:
  - '#plan'
  - '#issue-triage'
date: '2026-07-31'
modified: '2026-07-31'
body_hash: 'sha256:10a776e64ab51e08bdc84660469170c1ad689844bdb335157efa2edb658f6341'
tier: L2
related:
  - '[[2026-07-31-issue-triage-research]]'
  - '[[2026-07-25-non-destructive-index-publication-adr]]'
  - '[[2026-07-21-storage-prealloc-reclaim-adr]]'
  - '[[2026-07-25-index-resume-drift-race-adr]]'
---

# `issue-triage` plan

## Description

Work the eleven issues left open after the triage survey, plus the one pocket of genuinely stranded work the survey found. The authorizing research records the evidence for every row here; each Step below is traceable to a numbered issue in it.

**This plan is temporary and is meant to be deleted, not archived.** It exists to hold triage state while the backlog is worked down, and it carries no architectural weight of its own. Delete it once the rows are closed or re-homed onto the feature plans that own them; do not let it accrete into a standing backlog document, and do not cite it from anywhere that would outlive it.

**No ADR backs this plan, deliberately.** Scaffolding warned that the feature has no decision record, and that is accepted: triage sequencing is not an architectural decision. Three of the rows are themselves requests for a decision record, and those ADRs will govern the work they authorize rather than this document. Anything that turns out to need a decision leaves this plan and enters the pipeline at the ADR phase.

One finding shaped the sequencing and is worth restating: a PR that reads as merged is not evidence its commits are on the default branch. The stranded CI work merged into a branch that had itself landed thirty-three seconds earlier, so it shows green and delivers nothing. `P01.S01` is that recovery.

## Steps

### Phase `P01` - recover the stranded CI work

Bring PR 327's six workflow files onto main, where none of its seven commits currently land, and take the outstanding Python-pin work as a rider because both change the same workflow file.

- [x] `P01.S01` - Open a branch from main carrying the seven commits stranded on ci/health-remediation, and raise it as a fresh PR; `.github/workflows/`.
- [x] `P01.S02` - Pin the interpreter patch level so local and CI resolve one interpreter rather than a family; `.python-version`.
- [x] `P01.S03` - Derive the CI interpreter from the pin, replacing the four repeated version literals; `.github/workflows/ci.yml`.
- [x] `P01.S04` - Widen the interpreter conformance check from minor to patch granularity; `.github/workflows/ci.yml`.
- [x] `P01.S05` - State the one-per-line closing-trailer convention where the next PR author will read it; `.github/`.

### Phase `P02` - unblocked defect and hygiene work

The issues that need no decision before someone can start: a formatter crash class, a packaging call, orphaned artifacts under the git directory, and the one search signal from the silent-collapse family that is already scoped.

- [x] `P02.S06` - Route the three raw-payload formatter call sites through the canonical measurement reader; `src/vaultspec_rag/cli/_service_jobs_presentation.py`.
- [x] `P02.S07` - Refuse a non-finite duration or size at the formatter instead of rendering it as a small measurement; `src/vaultspec_rag/cli/_cli_format.py`.
- [x] `P02.S08` - Decide whether the wheel ships the test suite, and record the intent beside the existing package-data note; `pyproject.toml`.
- [x] `P02.S09` - Confirm no live code writes the acceptance index artifacts, then remove the orphaned copies; `.git/`.
- [x] `P02.S10` - Warn when a result set collapses to a single distinct path across a broad query; `src/vaultspec_rag/search/`.

### Phase `P03` - decision gates

The issues blocked on a human decision rather than on effort. Nothing here is startable as implementation until the named decision is made, and each row states which decision it waits on.

- [x] `P03.S11` - Obtain approval on the non-destructive index publication decision record, or record its rejection; `.vault/adr/`.
- [x] `P03.S12` - Wire the generation reclaim decision to a production caller once the decision record is approved; `src/vaultspec_rag/storage_reclamation.py`.
- [x] `P03.S13` - Author the decision record for the resumed-index drift race, naming the layer that owns detection and remedy; `.vault/adr/`.
- [x] `P03.S14` - Answer the five design calls blocking the remaining test-substitution sites; `.vault/adr/`.

## Parallelization

`P01` and `P02` are independent of each other and of `P03`, and can run concurrently.

Within `P01`, `S01` lands first and the rest follow it. `S02` through `S04` all change the same workflow file that `S01` restores, so starting them first would rebase that recovery onto a moving target; they are a natural rider once it is in. `S05` touches nothing the others do and can go at any time.

Within `P02` every Step is independent. `S06` and `S07` are the same defect approached from the call site and from the formatter, so one author should take both rather than two racing in one file. `S10` is the largest row here and is the only one carrying real design latitude.

Within `P03`, `S12` is hard-blocked on `S11`: the reclaim decision must not be wired to a production caller before the record authorizing it is approved, because the whole point of leaving it uncalled was refusing to close a step on code nothing runs. `S13` and `S14` are independent of `S11`, `S12`, and each other.

No Step in this plan needs the GPU, so none of it contends for the card.

## Verification

Each Step closes on its own evidence, not on the issue being closed:

- `P01.S01` - the seven stranded commits are ancestors of the default branch, checked by merge-base rather than by the PR reading as merged.
- `P01.S02` to `P01.S04` - a CI leg whose interpreter does not match the pin fails, demonstrated by pinning a value the runner does not have and watching the conformance step fail on its own assertion.
- `P01.S05` - the convention is stated where a PR author sees it before writing the body.
- `P02.S06` and `P02.S07` - a non-finite value in any of the named published fields renders as absent, and neither raises nor renders as a small measurement. Both directions proven: the guard broken, the test failing on the assertion it names, restored, passing.
- `P02.S08` - the wheel's contents match the recorded intent, whichever way the decision goes.
- `P02.S09` - no artifact remains, and a full test run does not recreate one.
- `P02.S10` - a query whose results all resolve to one path warns, and a query with normal breadth does not. The negative case matters as much as the positive one; a signal that always fires is noise.
- `P03.S11`, `P03.S13`, `P03.S14` - a decision record exists and is approved, or the decision is recorded as rejected with its reason. An unanswered question is not a closed Step.
- `P03.S12` - the reclaim decision has a production caller, and the three gates are exercised through it rather than directly.

The plan is complete when every Step is closed. Its final act is its own deletion: the plan is not done while the document still exists.
