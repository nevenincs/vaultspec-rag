---
tags:
  - '#adr'
  - '#automatic-merge-gate'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:ebdb32c404181286d0079744822bc884297477fd8b20689b12b8988ed8eec5b1'
related:
  - "[[2026-09-21-automatic-merge-gate-reference]]"
---

# `automatic-merge-gate` adr: `automatic pull-request and release-branch proof` | (**status:** `accepted`)

## Problem Statement

The required merge check is produced only when a maintainer applies a hidden
label. A normal ready pull request therefore remains permanently `Expected`
after every push, and release-please pull requests cannot produce the check at
all because their default-token mutations do not start workflows. Merge safety
and release progress currently depend on manual repository bookkeeping.

## Considerations

- Ready pull requests must prove the exact head commit automatically.
- Draft iteration should avoid occupying the scarce full-suite runners.
- Release automation must validate its final generated branch head without a
  person adding labels or rerunning jobs.
- One aggregate required context must continue to cover every measuring job.
- The implementation should retain ecosystem parity with the working Core
  topology documented by `2026-09-21-automatic-merge-gate-reference`.

## Considered options

- **Automatic state-tiered gate, chosen.** Pull-request lifecycle events run
  the gate; ready state selects the full suites and draft state selects lint.
  Release automation dispatches the same reusable workflow on its branch.
- **Label-only gate.** Rejected because an undiscoverable manual action is a
  prerequisite for every merge and every new head commit.
- **Run the full suite on every draft push.** Rejected because it spends the
  Windows and Linux fleet on work the author has explicitly marked unfinished.
- **Separate release validation.** Rejected because a second implementation of
  merge readiness can drift from the required pull-request verdict.
- **Merge queue.** Rejected because the repository ruleset and ownership model
  do not provide one, while the pull-request gate already proves an up-to-date
  head.

## Constraints

- Main continues to require `Check: Merge gate (Linux)` with strict status
  checks; changing that external context is outside this decision.
- Fork pull requests cannot execute untrusted code on the self-hosted fleet.
- Default-token changes do not start downstream workflow runs, so the release
  path requires explicit Actions dispatch.

## Implementation

Make the merge gate the automatic pull-request CI owner. Trigger it for open,
reopen, synchronize, ready-for-review, and label events. Run lint on ordinary
same-repository PR events; run every full measuring job when the pull request
is ready, when `ci:full` optionally requests proof of a draft, or when another
workflow calls or dispatches the gate. The aggregate job succeeds only when
all required measurements passed for the current commit, including a prior
full proof on the same SHA for partial events.

Give the reusable workflow a ref input and check out that ref in every
measuring job. After release-please finishes all mutations of its release
branch, dispatch the merge gate with that branch as both workflow ref and
validation input. Preserve the existing lightweight CI workflow only for
non-gating accelerator schedules and manual hardware diagnostics. The exact
pattern is grounded by `2026-09-21-automatic-merge-gate-reference`.

## Rationale

The chosen topology makes repository state the input to CI policy: ready means
fully proven, draft means cheap feedback, and a bot-authored release head is
explicitly dispatched. It removes operator knowledge from the normal path
while retaining an optional escape hatch for proving a draft. Reusing the same
gate for releases preserves one implementation of the required verdict, as
demonstrated by `2026-09-21-automatic-merge-gate-reference`.

## Consequences

- Every ready pull request receives a real required verdict after each push.
- Release PRs validate their final generated commit automatically.
- Drafts receive lint feedback without consuming both full-suite runners.
- `ci:full` remains available for an exceptional draft proof but is no longer
  required for merging.
- Full suites will run more often than under a manual gate, increasing runner
  use in exchange for a reliable production merge boundary.
- Fork pull requests remain explicitly refused until an isolated execution
  design is adopted.
