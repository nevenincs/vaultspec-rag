---
tags:
  - "#adr"
  - "#automatic-merge-gate"
date: '2026-09-21'
related:
  - "[[2026-09-21-automatic-merge-gate-reference]]"
  - "[[2026-09-29-release-pr-identity-research]]"
superseded_by: '2026-10-09-automatic-merge-gate-autonomous-release-adr'
modified: '2026-10-09'
body_schema: 'body-v2'
body_hash: 'sha256:ebdbbee60f587a808c9e53e08f7641519c056330c79e6f7d75a0686d4da7049b'
---

# `automatic-merge-gate` adr: `automatic pull-request and release-branch proof` | (**status:** `superseded`)

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
- Default-token changes start no downstream workflow run without a
  maintainer's approval, so the release path requires explicit Actions
  dispatch. The held pull-request runs on a release branch are redundant and
  stay unapproved (`2026-09-29-release-pr-identity-research`).

## Implementation

Make the merge gate the automatic pull-request CI owner. Trigger it for open,
reopen, synchronize, ready-for-review, and label events, and for every push to
main. A draft runs nothing and its aggregate job skips; a draft cannot merge,
and marking it ready runs the full gate on the same head. Opening, reopening,
or readying a same-repository pull request runs every full measuring job, as
does `ci:full`. A push to a ready pull request runs the light lint
(`just check-light`: ruff, TOML, markdown, workflow, absolute-import, nesting,
and docs-version dimensions) and the aggregate passes on it. A push to main
runs every full measuring job on the landed commit. The weekly schedule runs
the dependency audit alone. A dispatch runs the full gate unless it passes
`scope: light`; a workflow call runs the full gate.

Release Please runs from the merge gate's successful push run on main, with
`always-update` so its branch is rebuilt on main's newest green head, and with
releases skipped. After its lock refresh it dispatches the merge gate on the
release branch with `scope: light`. A release is cut only by dispatching
`.github/workflows/release-please.yml`: it proves the proposal head with the
full merge gate and both accelerator tiers through workflow calls,
squash-merges it with the default token, confirms the merged tree equals the
proven tree, has Release Please tag and release that commit, holds the
release as a prerelease, and dispatches Publish. A proposal merged by hand is
proven and tagged by the same dispatch.

Amended 2026-09-30: the cut no longer holds the release as a prerelease - the
release is created as a draft and published by the lane that proves it, as
`2026-09-30-release-standard-adr` rules.

## Rationale

The chosen topology makes repository state the input to CI policy: ready means
fully proven, draft means cheap feedback, and a bot-authored release head is
explicitly dispatched. It removes operator knowledge from the normal path
while retaining an optional escape hatch for proving a draft. Reusing the same
gate for releases preserves one implementation of the required verdict, as
demonstrated by `2026-09-21-automatic-merge-gate-reference`.

## Consequences

Amended 2026-09-30 for the user's authorized monitor tooling adoption:
`2026-09-30-monitor-tooling-adr` adds the canonical shared frontend-lifecycle
workflow as a supplemental check. The merge gate retains its required context
and owns Python validation plus frontend static checks. The shared lifecycle
workflow keeps its canonical name and trusted-author or human-label admission;
it does not change branch protection or release validation.

- Drafts consume no runner.
- A pull request pays for the full gate once when it opens or becomes ready;
  later pushes pay only for the light lint.
- Every commit on main receives the full gate after it lands. A regression can
  reach main, but Release Please does not refresh the proposal from a red main,
  and the cut proves the release head in full before it merges.
- Releases accumulate and are cut only on an explicit dispatch; merging the
  release pull request by hand does not publish anything.
- The release branch is proven by the light lint on each refresh, so the full
  suites run once per main commit rather than again per proposal refresh.
- `ci:full` remains available to prove any head on demand.
- Fork pull requests remain explicitly refused until an isolated execution
  design is adopted.

Amended 2026-09-30 on the maintainer's instruction: drafts run no checks, a
push to a ready pull request runs the light lint only, the full gate runs on
opening and again post-merge on main, Release Please proposes only after a
green main, and releases are cut by manual dispatch while pull requests
accumulate. This replaces the earlier rule that ready means fully proven on
every push and that drafts receive lint feedback.
