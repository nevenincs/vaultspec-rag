---
tags:
  - '#adr'
  - '#release-pr-identity'
date: '2026-09-29'
modified: '2026-09-29'
body_schema: 'body-v2'
body_hash: 'sha256:e09e4ead7364a373ba1c5f27a2798c4e4fa6f1a2dbbbdf41e40c08a300bf2121'
related:
  - "[[2026-09-29-release-pr-identity-research]]"
  - "[[2026-09-21-automatic-merge-gate-adr]]"
---

# `release-pr-identity` adr: `release pull requests are written by the release App` | (**status:** `accepted`)

## Problem Statement

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
- Tags and GitHub Releases are created with the default token, before the
  proposal step, so a broken App never blocks a merged release.
- Nothing but release-please writes the release branch, and nothing dispatches
  a second merge gate for it. The `uv.lock` project version is bumped inside
  release-please's commit.
- Amends `2026-09-21-automatic-merge-gate-adr`: its release-branch dispatch and
  the gate's reusable-call entry point are withdrawn; its automatic
  pull-request gate stands unchanged.

## Implementation

We will run release-please twice in `.github/workflows/release-please.yml`:
first with `skip-github-pull-request` on the default token, then hold the new
release and dispatch Publish, then mint the App token with
`actions/create-github-app-token` from the `RELEASE_APP_CLIENT_ID` variable and
`RELEASE_APP_PRIVATE_KEY` secret and run the proposal with
`skip-github-release`. `release-please-config.json` gains a TOML extra file for
`uv.lock`. The lock-refresh steps, the merge-gate dispatch and the merge gate's
`workflow_call` trigger are deleted. The guard in
`dev/guards/test_ci_release_please_prs.py` holds the identity split, the step
order, the single writer and the lock entry.

## Rationale

The App identity is the only option that removes the approval without also
waking the tag and release triggers, because it is applied to the proposal
alone. Folding the lock bump into release-please's commit is what makes the
proposal one head, so the pull-request gate runs once per head instead of
starting and being superseded seconds later. Both facts are measured in
`2026-09-29-release-pr-identity-research`. Accepted 2026-09-29 on the
maintainer's instruction to implement this design after the #558 diagnosis.

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
