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
supersedes:
  - '2026-09-21-automatic-merge-gate-adr'
modified: '2026-10-09'
body_schema: 'body-v2'
body_hash: 'sha256:1b406e09732406c70314824086d4349fd01eb9af2bdf10ae03a85b35f5ba17e4'
---

# `automatic-merge-gate` adr: `Merge starts an autonomous verified release` | (**status:** `accepted`)

## Problem Statement

The release proposal could offer merge after only light lint, while its PR checks skipped. Merging did not start the release cut, and publication required another human review and rerun. Grounding: `2026-10-09-automatic-merge-gate-core-orchestration-reference`.

## Considerations

Authorized 2026-10-09: the maintainer requested the flow be fixed using Core orchestration, emphasized real Merge Gate and Dev Server proof before release PR merge, and explicitly selected "Release PR merge is the only human action". This authorizes automatic cut initiation and replacement of the independent manual release-pin review.

The draft-first release standard, native four-target and accelerator proof, fork containment, pinned toolchain binaries, and split OIDC/deploy credentials remain binding.

## Considered options

- Full proposal proof, automatic merged-candidate cut, and workflow-bound artifact attestations: chosen. Human approval is the release PR merge; all subsequent work is mechanical.
- Preserve manual cut and catalog review: rejected because it requires additional human actions.
- Trust live checksums alone: rejected because a checksum uploaded beside an artifact supplies no independent provenance.

## Constraints

Release Please dispatches full checks and the canonical Dev Server workflow after the final proposal branch write. A light or skipped result cannot authorize a release proposal. The required aggregate reuses only the full exact-SHA proof and includes Dev Server success. Held bot PR checks are released automatically after that proof.

A maintainer merge starts candidate selection automatically. Full exact-commit checks and both accelerator tiers must pass before tag creation. Candidate, cut, or required publication handoff failures report failure; no normal transition requires dispatch by a person. Manual dispatch remains recovery only.

Artifact provenance replaces the human catalog-review stop. Only immutable public archives that passed native offline/browser proof are attested, in an isolated job with no repository checkout or contents write. Verification enforces repository, signing workflow, exact tag ref and source commit before archive inspection/extraction; executable hashes come from that authenticated archive and are checked immediately before execution. Toolchain provisioning continues to use reviewed committed binary pins.

## Implementation

Adopt Core's push-driven candidate/cut topology and full proposal dispatch. Include the canonical Dev Server dispatch's exact-SHA result in the required gate. Replace the manual pin catalog owner with a single workflow-bound provenance verifier used by draft admission, package-index admission and public acquisition. Keep wheel/sdist identity, checksum completeness, native evidence and draft-first publication.

This supersedes the manual-cut/light-release-branch and held-run constraints in `2026-09-21-automatic-merge-gate-adr`. It amends only the release-product provenance and human review handoff in `2026-10-02-monitor-delivery-adr`; independently reviewed committed pins remain required for provisioned compiler/runtime tools. `2026-09-30-release-standard-adr` remains unchanged.

## Rationale

The maintainer's merge approves the release source and workflow. GitHub/Sigstore attestation binds final artifact bytes to that reviewed repository/workflow/source identity without requiring a second maintainer action. Checksums and archive manifests remain consistency checks, with provenance verification supplying independent signing identity.

## Consequences

One human release action remains. Release PRs wait for real full checks and Dev Server proof. Build/publication failures leave a draft and report failure. Old releases without attestations fail the new public acquisition verifier; they are not silently admitted from live checksums. Attestation availability and the admitted runner fleet become part of the release trust boundary. Administrator bypass remains a separate repository setting and is not changed by workflow code.
