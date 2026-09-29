---
tags:
  - '#research'
  - '#release-pr-identity'
date: '2026-09-29'
modified: '2026-09-29'
body_schema: 'body-v2'
body_hash: 'sha256:3a0299310739bfeb9d7591556cf8fb4119f773668778f3796694d12cfea2a991'
related:
  - "[[2026-09-21-automatic-merge-gate-adr]]"
---

# `release-pr-identity` research: `why release pull requests stall and how their identity fixes it`

The 0.5.3 release pull request (#558) sat with its merge gate queued while the
Actions tab asked a maintainer to approve runs the pull request's checks never
listed. The question is what requires that approval, whether the gate needs it,
and which identity and branch shape give a release pull request exactly one
automatic gate run. The evidence shows the approval is a GitHub platform rule
for default-token pull requests, the existing dispatch already produced the
required check, and an App-written single-commit proposal removes both the
approval and the duplicate run.

## Findings

### Default-token pull requests now start workflows only after approval

Since a GitHub change announced 2026-06-11, a pull request that
`github-actions[bot]` opens or updates starts its `pull_request` workflows in the
`action_required` state until someone with write access approves them
(https://github.blog/changelog/2026-06-11-bot-created-pull-requests-can-run-workflows-if-approved/).
Before that change such events started nothing, which is the premise of the
accepted `2026-09-21-automatic-merge-gate-adr` constraint "Default-token changes
do not start downstream workflow runs". The community thread confirms it also
applies to same-repository branches and that a PAT or GitHub App token avoids it
(https://github.com/orgs/community/discussions/199292).

The repository's fork approval policy reads `all_external_contributors`
(`gh api repos/nevenincs/vaultspec-rag/actions/permissions/fork-pr-contributor-approval`);
the bot-created rule applies regardless of it.

### Every release cycle produced two held runs and one dispatched gate

`release-please.yml` at `74bdf17e` opened the pull request, pushed a separate
`uv.lock` commit, then dispatched `merge-gate.yml` on the branch. For #558 that
gave `pull_request` run 36582582116 on `e70a5ce9` (held), dispatched run
36582605194 on `89e15697` (ran at once), and `pull_request` run 36582615591 on
`89e15697` (held; approved by the maintainer as attempt 2). The run history of
the release branch shows the same held pair on every release pull request back
to 2026-09-18, each flipping from `action_required` to `failure` when its pull
request closed. A held run has no jobs, so it adds no check run and never
appears in the pull request's checks list.

### The held runs were never needed, and approving one doubled the queue

The ruleset `protect-main` requires only `Check: Merge gate (Linux)` from
integration 15368 (GitHub Actions) on the head commit, which the dispatched run
provides. Approving 36582615591 started a second full gate on the same commit.
With one online Linux x64 runner (`gw-workstation-linux-docker-x64` offline),
the duplicate's lint and audit ran ahead of the dispatched run's lint, which
waited 19 minutes for a runner. Two gates on one commit also race: the newest
completed `Check: Merge gate (Linux)` decides the merge box.

Ruled out: the `pypi` and `copilot` environments carry no protection rules, and
the ruleset's `require_extra_approval_for_unattributed_changes` did not fire on
#558 (review decision empty; both commits attribute to `github-actions[bot]`).

### Tags and releases must stay on the default token

`publish.yml` still declares `push: tags` and `acquisition.yml` declares
`release: published`; both are inert only because the default token creates the
tag and release (`.github/workflows/acquisition.yml:28`). A tag created by any
other identity would start Publish from its tag trigger in addition to the
explicit dispatch in `release-please.yml`. `googleapis/release-please-action`
`v4.4.1` (commit `5c625bfb`) exposes `skip-github-release` and
`skip-github-pull-request` and runs releases before pull requests
(`src/index.ts` `main`), so the two writes can take two identities in two steps
without changing its order.

### The lock bump fits in release-please's own commit

The lock refresh commit `89e15697` changed one line: the project's own
`version` in `uv.lock`. `release-please@17.11.2`'s `GenericToml` updater with
jsonpath `$.package[?(@.name.value=='vaultspec-rag')].version` produced a file
byte-identical to that commit's `uv.lock` when run locally against `74bdf17e`.
The `.value` segment is required: the plain `@.name` filter matched nothing.
A single-commit proposal removes the second push, the second gate run it
started, and the checkout, uv setup and push steps.

### The App identity brings a label-event verdict run

release-please labels its pull request `autorelease: pending` after opening it,
and the labels are load-bearing: it finds open and merged proposals by them
(`release-please@17.11.2` `build/src/manifest.js` `findOpenReleasePullRequests`,
`findMergedReleasePullRequests`). Under an App token that label raises a
`labeled` event, which `merge-gate.yml` handles by running only its verdict job
against the newest completed full run on the same commit. It measures nothing
and costs one short job; it cannot be removed without dropping `labeled` from
the gate's triggers, which `ci:full` depends on.

### Alternatives

- Keep the default token and never approve: the dispatched gate suffices, but
  every cycle leaves two held runs an operator must know to ignore, and one
  approval doubles runner load.
- A fine-grained PAT, as `vaultspec-dashboard` uses (`RELEASE_PLEASE_TOKEN`):
  avoids approval but ties the release to one person's long-lived credential,
  and passing it for releases too would wake the dormant tag triggers.
- A GitHub App token for the pull request only: short-lived, repository-scoped,
  and independent of any person.

Not investigated: whether GitHub later offers a repository setting that exempts
`github-actions[bot]` pull requests from approval, as it does for Copilot.

## Sources

- https://github.blog/changelog/2026-06-11-bot-created-pull-requests-can-run-workflows-if-approved/
- https://github.com/orgs/community/discussions/199292
- https://github.com/googleapis/release-please-action/blob/5c625bfb5d1ff62eadeeb3772007f7f66fdcf071/src/index.ts
- `release-please@17.11.2` `build/src/updaters/generic-toml.js`, `build/src/manifest.js`
- `.github/workflows/acquisition.yml:28`
- `.github/workflows/release-please.yml` at commit `74bdf17e`
- Commits `e70a5ce9`, `89e15697` on `release-please--branches--main--components--vaultspec-rag`
- Workflow runs 36582582116, 36582605194, 36582615591
