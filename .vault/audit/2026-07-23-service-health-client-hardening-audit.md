---
tags:
  - '#audit'
  - '#service-health-client-hardening'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:380a9d664a8f6236cc20a4de1e769d4a2d32f68c0a8adf235d35a51bd35b9c4c'
related:
  - "[[2026-07-22-service-health-client-hardening-adr]]"
  - "[[2026-07-22-service-health-client-hardening-research]]"
---

# `service-health-client-hardening` audit: `independent closing review — passed on revision`

## Scope

The mandatory closing review of the health-client hardening plan, recorded here for durability because the review itself ran in an ephemeral workspace. An independent reviewer with no authorship in the plan judged the three implementation commits and, after finding the plan's central claim false on the first pass, judged the revision that answered those findings.

The review is worth preserving in full because it is the second time in this effort that an independent pass falsified a claim the authors and the coordinator had all accepted, and the first time it did so by executing the failure rather than reasoning about it.

## Findings

### first-pass-fail-central-claim-falsified | high | The first review failed the plan by reproducing a crash the whole design was asserted to prevent

The plan's central claim was that moving the health call to a single owner cost zero contract change at the nine call sites. The first review disproved it in under a second. The new owner returned a non-object value when the health endpoint answered with a JSON body that was not an object, and every repointed site then treated that value as a mapping. Against a foreign responder on the target port, the stop verb emitted zero structured outcome envelopes and crashed - precisely the failure the broker-facing outcome rule exists to prevent, and precisely the property the plan's own guard test was written to assert but exercised only for the easy half of the input space. Two further high findings (a surviving credential-disclosure route through a proxy, and a red lint gate carrying a dead import the consolidation left behind) and two lesser ones (the contract test never committed, five identity tests reaching the live service) accompanied it.

### revision-closed-every-finding-verified-by-execution | high | The revision genuinely closed all five, confirmed by trace and execution rather than by its own description

The re-review passed the revision and recorded how each finding was checked rather than accepting the diff's account. The owner now guarantees a strict three-way contract - parsed object, structured error carrying the HTTP code, or the unreachable sentinel - with an explicit branch returning the sentinel for a parsed non-object, so no call site can receive a non-mapping; the reviewer confirmed the binding by executing both the old crashing path and the new guarded one. The credential route was closed by routing every request through one opener that neutralises the proxy environment, redirect refusal intact. The lint gate is clean on every plan file. The contract test is committed and drives the non-object body end to end, shown to fail if the fix regresses. The identity tests no longer reach the live service. No new high finding was introduced, and nothing in the delivered work describes the deferred stop-path identity check as made sound.

The durable lesson is the one already codified this effort: a guard test is not verification until it has been seen to fail for the intended reason, and a review that executes the failure is worth more than one that reads the fix.

## Recommendations

None outstanding for this plan; it is complete and its closing review passed. One item is deliberately carried out of scope rather than closed: the stop-path identity check remains self-referential, narrowed but not made sound by the redirect refusal. It has its own home and must be addressed there, and no work arising from this plan may describe it as fixed.

One observation for the broader effort, surfaced by the review's F5: unit tests were reaching the resident service at all, which the fix corrected only for the five it named. That is a pre-existing isolation gap almost certainly wider than those five, and it belongs to the test-marker and isolation sweep recorded elsewhere rather than to this plan.
