---
tags:
  - '#adr'
  - '#release-pr-identity'
date: '2026-09-29'
modified: '2026-10-18'
body_schema: 'body-v2'
body_hash: 'sha256:225f22c0654a8094b822a6f5b89cd721b7f2ae3a02a4ede9b6f5188cea4dbfa3'
related:
  - "[[2026-09-29-release-pr-identity-research]]"
  - "[[2026-09-21-automatic-merge-gate-adr]]"
  - '[[2026-10-09-automatic-merge-gate-autonomous-release-adr]]'
---

# `release-pr-identity` adr: `release pull requests are written by the release App` | (**status:** `accepted`)

## Problem Statement

Accepted 2026-10-18 under the fleet release-pipeline standard, which the
maintainer authorized for every repository under the account and which the
orchestrating session handed to this repository's custodian. It had been
rejected on 2026-09-29 on the premise that the default-token dispatch in
`2026-09-21-automatic-merge-gate-adr` produced the required check. That premise
is disproven: GitHub links a dispatched run's checks to no pull request. On
2026-10-17 release PR #596 carried only the held and withheld runs of its own
events, CodeQL and a dispatched gate the pull request never showed; the
required `Check: Merge gate (Linux)` stayed expected, and the release cut's
merge in run 39053510856 failed with "the base branch policy prohibits the
merge". `protect-main` has no bypass actors, so no actor could land it. An
earlier release shipped only through an administrator bypass since removed.

A pull request the default token opens or updates now starts its workflows only
after a maintainer approves them in the Actions tab, and the pull request's
checks never show that pending approval. Every release proposal therefore
carried two held merge-gate runs beside the dispatched gate that actually
produced the required check, and approving one started a duplicate full gate on
the same commit. The accepted `2026-09-21-automatic-merge-gate-adr` rests on the
opposite premise, that default-token changes start no runs. Evidence:
`2026-09-29-release-pr-identity-research`.

## Considerations

- Releases and tags must keep raising no workflow event, or Publish starts from
  its tag trigger as well as from its explicit dispatch.
- The release proposal must reach the one required gate automatically, once
  per head, with no hidden operator action.
- The credential should be short-lived, repository-scoped and independent of a
  person.
- release-please's labels are load-bearing, so a `labeled` event on the
  proposal cannot be avoided.

## Considered options

- **App token for the proposal, default token for releases, single-commit
  proposal, chosen.** The proposal's own events start the gate; the release
  chain is unchanged.
- **Keep the default token and dispatch, never approve.** Works, but leaves two
  held runs per cycle that read as a stalled release, and one approval doubles
  the gate.
- **A fine-grained PAT for everything.** Avoids approval, but binds releases to
  one person's long-lived credential and wakes the dormant tag and release
  triggers into duplicate Publish runs.
- **An App token for everything.** Same duplicate-Publish problem as the PAT.

## Constraints

- The release pull request, and every push to its branch, is written with a
  token minted from the release App, with Contents and Pull requests write on
  this repository only. No fallback to the default token.
- Tags and GitHub Releases are created with the default token, by the release
  cut and in a job separate from the proposal, so a broken App never blocks a
  merged release.
- Nothing but release-please writes the release branch, and nothing dispatches
  a merge gate or Dev Server run for it. The `uv.lock` project version is bumped
  inside release-please's commit.
- Amends `2026-10-09-automatic-merge-gate-autonomous-release-adr`: its
  release-branch dispatches are withdrawn; its proven cut and its reusable-call
  gate stand unchanged.

## Implementation

The proposal job in `.github/workflows/release-please.yml` mints the App token
with `actions/create-github-app-token`, pinned by commit, from the
`RELEASE_APP_CLIENT_ID` variable and `RELEASE_APP_PRIVATE_KEY` secret, and runs
release-please with that token and `skip-github-release`. The cut job keeps
creating the tag and draft release with the default token after its own proof.
`release-please-config.json` carries a TOML extra file for `uv.lock`. The
lock-refresh steps and both release-branch dispatches are deleted. The merge
gate keeps its reusable-call entry point, which the cut's proof uses, and its
Dev Server proof reads the newest run on the exact commit from any event. The
merge gate and the shared Dev Server workflow admit the App by the fleet's
trusted-author clause, which names the owner, collaborators and
`nevenincs-release[bot]`. The guards in
`dev/guards/test_ci_release_please_prs.py`,
`dev/guards/test_ci_fork_containment.py` and `dev/guards/test_ci_lanes.py`
hold the identity split, the single writer, the lock entry and the clause.

## Rationale

The App identity is the only option that removes the approval without also
waking the tag and release triggers, because it is applied to the proposal
alone. Folding the lock bump into release-please's commit is what makes the
proposal one head, so the pull-request gate runs once per head instead of
starting and being superseded seconds later. Both facts are measured in
`2026-09-29-release-pr-identity-research`; the dispatched check's missing
pull-request link is shown by #596 above.

## Consequences

- A release proposal gets exactly one full gate run per head, visible in its
  checks, with no approval step.
- Opening a proposal also raises one `labeled` verdict-only run; it measures
  nothing and may show red until the full run completes.
- The repository depends on the release App's installation and key; a missing
  or revoked key fails the `Mint the release pull request token` step by name.
- Reconsider if GitHub exempts default-token pull requests from approval, or if
  release-please gains native `uv.lock` support that makes the TOML entry
  redundant.
