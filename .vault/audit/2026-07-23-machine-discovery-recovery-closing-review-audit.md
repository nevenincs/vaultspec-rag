---
tags:
  - '#audit'
  - '#machine-discovery-recovery'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:fe552a5948fcb658bc59e77660ae93074055d0ed281211ec4c460b9ae11936e7'
related:
  - "[[2026-07-21-machine-discovery-recovery-adr]]"
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# `machine-discovery-recovery` audit: `independent closing review — passed, two low follow-ups`

## Scope

The mandatory closing review of the machine-discovery-recovery plan, by an independent reviewer with no authorship in the work. Assessed the discovery pointer schema and reconcile flow, the machine-singleton lease and ownership, degraded-state handling, and the public contract document, against the decision record, the lifecycle-inertness rules, and the test-integrity mandate. Test integrity assessed by reading rather than execution, since the discovery tests can touch the live machine singleton and the GPU was in use. Verdict: PASS, with two low follow-ups that do not block closure.

## Findings

### model-sound-on-every-axis | none | Ownership, degraded-vs-absent, and reconcile all hold under independent check

Owner-only mutation is enforced, not merely asserted: publishing the discovery pointer requires the exact retained live lease - the process id equal to the caller and an open descriptor confirmed by fstat - and requires the payload's owner id to equal the lease owner. A non-owner cannot publish. Degraded and absent are correctly distinguished: a live holder with a missing, invalid, stale, or foreign pointer, or an unreadable probe, resolves to a typed degraded reason; only a non-positive holder reaches the status-file fallback, and the property that a degraded state never invites a second daemon is directly guarded by a test. The reconcile loop reads and reports only - it never writes, deletes, restarts, or terminates; the owner's own heartbeat is the sole repair path - is deadline-bounded, and early-exits when nothing holds the singleton. It is lifecycle-inert. The contract document matches the code on all three resolution states, five degraded reasons, three reconcile outcomes, and three sources.

### doc-citations-drift-silently | low | The contract doc cites code by path and line, which nothing keeps fresh

The document cites code locations by line number, and nothing gates those against the code - the citation gate shipped this session runs the other direction (code must not cite records). The citations are currently accurate, but line numbers rot as the files change. Maintainability, not correctness. Anchor to symbol names instead of line numbers.

### pid-less-pointer-resolves-ready | low | A pointer with an absent or non-integer owner id resolves READY with an unconfirmed owner, but is unreachable through the sanctioned publisher

The resolver's foreign-owner check only fires when the pointer's owner id is present, so a fresh pointer carrying an absent or non-integer owner id resolves to READY with an owner that was never confirmed. This is unreachable through the sanctioned publisher, which enforces an integer owner equal to the lease owner on write, so triggering it needs an out-of-band corrupted pointer. The cheap defensive fix mirrors the publisher's own invariant on the read side: reject an owner-less pointer as degraded rather than trusting it.

### reconcile-identity-check-is-the-template-the-health-plan-lacked | none | Informational: this plan's identity check is the correct model for the deferred health-client tautological-gate fix

Worth recording for a cross-plan follow-up. This plan's reconcile identity check confirms a three-way agreement - the operating-system lock holder, the published pointer, and the live health response - with the EXPECTED values sourced from the POINTER, not from the health response itself. It therefore cannot be satisfied by comparing a responder against its own answer. That is exactly the property the service-health-client stop-path identity check was found to LACK (its expected token came from the same health response it then compared against - a tautology). This reconcile check is a working template for the deferred health-client identity-gate fix, and the two should be linked when that follow-up is scheduled.

## Recommendations

Close the plan on this PASS plus the S25 lifecycle verification. The introduced work is sound on every reviewed axis - enforced ownership, correct degraded-versus-absent resolution, a lifecycle-inert read-only reconcile, and a faithful contract document.

The two low findings are worth a small follow-up but neither gates closure: anchor the document's code citations to symbol names so they do not rot, and reject an owner-less pointer defensively on the read side to mirror the publisher's write-side invariant. The second is unreachable through sanctioned code and the first is doc freshness, so recording them is sufficient if a follow-up is not scheduled now.

The informational finding is the one to carry forward deliberately: this plan's pointer-sourced identity check is the correct template for the deferred tautological-identity fix in the service-health-client plan. Link the two when that fix is scheduled - the pattern to copy is sourcing the expected identity from an independent record, never from the response being validated.
