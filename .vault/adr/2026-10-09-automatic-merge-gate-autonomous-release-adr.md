---
tags:
  - "#adr"
  - "#automatic-merge-gate"
date: '2026-10-09'
related:
  - "[[2026-09-21-automatic-merge-gate-adr]]"
  - "[[2026-09-30-release-standard-adr]]"
  - "[[2026-10-02-monitor-delivery-adr]]"
  - "[[2026-10-09-automatic-merge-gate-core-orchestration-reference]]"
  - '[[2026-09-29-release-pr-identity-adr]]'
supersedes:
  - '2026-09-21-automatic-merge-gate-adr'
modified: '2026-11-23'
body_schema: 'body-v2'
body_hash: 'sha256:53ff3eb7c870c2a0049c2a2ad2374f8fd76dfdda29ca0be8bf85af3a44776e7e'
---

# `automatic-merge-gate` adr: `Merge starts an autonomous verified release` | (**status:** `accepted`)

## Problem Statement

The release proposal could offer merge after only light lint, while its PR checks skipped. Merging did not start the release cut, and publication required another human review and rerun. Grounding: `2026-10-09-automatic-merge-gate-core-orchestration-reference`.

## Considerations

Authorized 2026-10-09: the maintainer requested the flow be fixed using Core orchestration, emphasized real Merge Gate proof before release PR merge, and explicitly selected "Release PR merge is the only human action". This authorizes automatic cut initiation and replacement of the independent manual release-pin review.

The draft-first release standard, native four-target and accelerator proof, fork containment, pinned toolchain binaries, and split OIDC/deploy credentials remain binding.

## Considered options

- Full proposal proof, automatic merged-candidate cut, and workflow-bound artifact attestations: chosen. Human approval is the release PR merge; all subsequent work is mechanical.
- Preserve manual cut and catalog review: rejected because it requires additional human actions.
- Trust live checksums alone: rejected because a checksum uploaded beside an artifact supplies no independent provenance.

## Constraints

Release Please dispatches full checks after the final proposal branch write. A light or skipped result cannot authorize a release proposal. The required aggregate reuses only the full exact-SHA proof. Held bot PR checks are released automatically after that proof.

A maintainer merge starts candidate selection automatically. Full exact-commit checks and both accelerator tiers must pass before tag creation; the release cut proof amendment of 2026-10-26 below states how a version-only release head meets the first of these. Candidate, cut, or required publication handoff failures report failure; no normal transition requires dispatch by a person. Manual dispatch remains recovery only.

Artifact provenance replaces the human catalog-review stop. Only immutable public archives that passed native offline/browser proof are attested, in an isolated job with no repository checkout or contents write. Verification enforces repository, signing workflow, exact tag ref and source commit before archive inspection/extraction; executable hashes come from that authenticated archive and are checked immediately before execution. Toolchain provisioning continues to use reviewed committed binary pins.

## Implementation

Adopt Core's push-driven candidate/cut topology and full proposal dispatch. Replace the manual pin catalog owner with a single workflow-bound provenance verifier used by draft admission, package-index admission and public acquisition. Keep wheel/sdist identity, checksum completeness, native evidence and draft-first publication.

This supersedes the manual-cut/light-release-branch and held-run constraints in `2026-09-21-automatic-merge-gate-adr`. It amends only the release-product provenance and human review handoff in `2026-10-02-monitor-delivery-adr`; independently reviewed committed pins remain required for provisioned compiler/runtime tools. `2026-09-30-release-standard-adr` remains unchanged.

## Rationale

The maintainer's merge approves the release source and workflow. GitHub/Sigstore attestation binds final artifact bytes to that reviewed repository/workflow/source identity without requiring a second maintainer action. Checksums and archive manifests remain consistency checks, with provenance verification supplying independent signing identity.

## Consequences

One human release action remains. Release PRs wait for real full checks. Build/publication failures leave a draft and report failure. Old releases without attestations fail the new public acquisition verifier; they are not silently admitted from live checksums. Attestation availability and the admitted runner fleet become part of the release trust boundary. Administrator bypass remains a separate repository setting and is not changed by workflow code.

## Ready pull-request proof, amended 2026-10-13

Authorized 2026-10-13: the maintainer requested that CI jobs actually run on pull requests, that the causes of skipping and failures be fixed, and that normal CI require less maintenance.

Every ready same-repository pull request from an admitted author must automatically run full lint, both supported Linux interpreter suites, Windows correctness, and the dependency audit on opening, reopening, synchronization, and readiness. A fresh head receives fresh proof; manually dispatching a full run or cycling a label is recovery, never a normal prerequisite. Draft and untrusted-code admission remain unchanged.

Light lint, skipped suites, and a successful partial dispatch cannot authorize the required merge check. An unrelated label can preserve only the newest completed verdict on the same head after confirming that all five full measuring jobs passed. A newer failed or cancelled proof cannot be replaced by an older green result. The full job condition is shared by full lint and the correctness suites to prevent per-job policy drift.

This replaces the ordinary ready-PR light-only synchronization policy retained from the superseded 2026-09-21 decision. Release proof, accelerator admission, and the external required check name remain unchanged. Windows correctness uses an isolated hosted VM with child-process headroom; dedicated accelerator runners continue to serve hardware proof.

Grounding: `.github/workflows/merge-gate.yml` jobs `lint`, `tests`, `tests-windows`, `dependency-audit`, and `gate`; `dev/guards/test_ci_lanes.py`; PR #604. At head 897a7b24, PR run 38378550261 passed light lint while every full measuring job skipped, even though full dispatch 38378599399 failed seven Windows tests. That is insufficient merge evidence. At head 13eca2c0, automatic PR run 38385969699 admitted every full measuring job without a label or dispatch.

## Authorized CI enforcement amendment

Amended 2026-10-13: the maintainer explicitly required fixing CI failures,
verifying every trusted ready PR head in full, and preventing workarounds.
Foreign-fork and untrusted-author PRs run no checks and cannot merge.
This supersedes the prior light-dispatch and human-label admission exceptions,
and the held-bot-PR approval step. Trusted release automation still dispatches
full proof of its own generated branch after the final write.

Every trusted ready PR update runs full lint, both Linux Python versions,
the Windows correctness suite, dependency audit and the three CodeQL languages.
A skipped untrusted aggregate uses a different context from the required check,
so it cannot satisfy protection. No light input or job can authorize merge.
Manual accelerator CI selects both macOS and CUDA by default; macOS suite and
setup failures are gating. Hardware remains in its trusted schedule, dispatch
and release lanes. The administrator bypass is removed from protect-main.
GitHub automatic CodeQL setup is retired when the guarded replacement is deployed.

The provenance correction keeps the exact certificate identity, repository,
tag, source and signer digests, while removing the mutually exclusive
signer-workflow flag. Windows verification compares actual owner SID and protected
ACL semantics, resolves canonical paths, and refuses image metadata from exited
processes. Tests retain the real Windows handles needed to prove that refusal.

Unrelated-label successes preserve the existing full-proof chain on the same SHA. The gate walks only successful preservation runs until it reaches complete measured proof; an intervening failure, cancellation, incomplete measurement or unreadable job record terminates the chain.

## Release proposal identity amendment, 2026-10-18

Amended under the fleet release-pipeline standard authorized by the
maintainer. The release-branch dispatch of the merge gate is withdrawn: a dispatched run's checks attach to no pull request, so
the required check never reported on release PR #596 and the cut could not
merge it. The release App writes the proposal in one commit, as
`2026-09-29-release-pr-identity-adr` decides, and the proposal's own
pull-request events run the full gate. Every other constraint
above stands.

## Release cut proof amendment, 2026-10-26

Amended on the operator's explicit instruction to stop re-running the full
pull-request suites in the release gate. The cut no longer calls the merge gate
on the release head. That head differs from its parent only by Release
Please's version files, and the parent is a main commit whose merge-gate push
run already measured every suite, so re-running them repeated about 2.5
runner-hours per cut on the single Linux build host.

The cut's gate job now satisfies "full exact-commit checks" by proof rather
than repetition. It requires the release head to change only
`.release-please-manifest.json`, `CHANGELOG.md`, `pyproject.toml`, `uv.lock`
and `docs/installation.md`, and in `pyproject.toml` and `uv.lock` only the
version line. It requires the parent's newest merge-gate run started by a push
to have succeeded: the weekly schedule's audit-only run carries the same
aggregate check name, so a check verdict alone does not prove the suites. It
re-runs the dependency audit on the release head, because advisories can be
published against the unchanged lock between the merge and the cut. Both
accelerator tiers still prove the release head itself before any tag exists,
and the provenance constraints above are unchanged.

Grounding: `.github/workflows/release-please.yml` job `prove-gate`;
`dev/guards/test_ci_release_please_prs.py`;
`tools/binaries/tests/test_release_workflow.py`. Release run 40271581654
re-ran the full gate on 669966ead, a version-only head over 388bdcb96, whose
push gate had already passed.

## Proof reuse amendment, 2026-10-30

Amended on the operator's explicit instruction to stop repeating measurement
the tree has already passed, and to land this directly on the default branch.
A scope job in the merge gate now decides what is left to measure, and any
unclear answer measures in full. A landed commit whose tree equals a merged pull
request's head, where that head's newest proof passed all eight measuring jobs,
reruns only the dependency audit and code scanning. A version-only change over a
parent whose push gate passed runs no suite, on the release proposal and on its
landed commit; the cut still audits the lock and runs both accelerator tiers.
The full-proof-per-ready-head rule holds for every pull request except the
release App's proposal.

Jobs that only read the API and wait on other runs (scope, verdict, candidate
selection, parent proof, release result) move to GitHub-hosted runners, so a
waiting job cannot hold a fleet slot it is waiting on. This extends the
exception this record already grants the Windows suite. The runner-placement
rule in `dev/ci_contract.py` is not gated and still reports these jobs.
Workflow schedules are removed. The merge gate is no longer callable as a
reusable workflow, and the light lint target is deleted. The administrator
bypass stays in use for direct landings, which contradicts the removal recorded
above; such a commit has no same-tree pull-request proof and so measures in full.

Grounding: `dev/gate_scope.py`; `.github/workflows/merge-gate.yml` job `scope`;
`dev/guards/test_gate_scope.py`.

## Hosted measurement amendment, 2026-11-23

Amended on the maintainer's explicit instructions of 2026-11-23: move every job
that needs no accelerator to GitHub-hosted runners, finish a pull request's
measurement in under fifteen minutes, keep in the accelerator lane only tests
that need the physical accelerator, and remove the frontend lifecycle check
from the repository and from merge readiness.

Lint, both Linux interpreter suites, the Windows suite, the dependency audit
and code scanning run on hosted runners, all at once. The suites are cut into
shards by test file, three per Linux interpreter and six on Windows, so the
slowest shard is what a pull request waits for; every file belongs to exactly
one shard and each sharded job runs every index. The required aggregate names
each of those jobs and passes only when all of them did. This supersedes the
self-hosted placement of the measuring jobs, and widens the hosted exception
this record granted the waiting jobs and the Windows suite to every job that
needs no accelerator.

The `integration` tier means a test that needs the physical accelerator
through a real loaded model. A test that uses real tools, processes or the
network without one belongs to the accelerator-free lane and runs in the
hosted shards.

Merge readiness no longer reads any workflow other than the merge gate.

Grounding: `.github/workflows/merge-gate.yml` jobs `lint`, `tests`,
`tests-windows`, `dependency-audit`, `code-scanning` and `gate`;
`src/vaultspec_rag/tests/_shards.py`; `dev/guards/test_ci_shards.py`;
`dev/gate_scope.py`. Run 45206919914 measured a pull request in nine minutes
on hosted runners, against hours queued on one self-hosted host.
