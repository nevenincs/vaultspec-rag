---
tags:
  - '#audit'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:a5ced809aed0eb55b8f12325fd3318f2b93a37962a7135c0a78a65ecd9165625'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
  - "[[2026-07-29-encode-batch-adaptivity-adr]]"
  - "[[2026-07-29-encode-batch-adaptivity-audit]]"
---

# `encode-batch-adaptivity` audit: `final branch review before pull request`

## Scope

Independent final review of the complete feature branch (merge base `45b96e5b`
to tip `3803e868`, 37 files, +3382/-680) by a reviewer with no authorship in
any of the six merged lanes. Audited in priority order: encode OOM-path
correctness, GPU-lock discipline, whether the new input hardening silently
degrades any real production value, the three deliberately-unmerged lookalike
helper pairs, project-rule conformance, and faithfulness to the governing
decision. All 401 unit tests across the touched test files were run serially
under the CPU-only marker exclusion; all passed. No integration, quality, CUDA
or subprocess-GPU tests were run, no model was loaded, and no CUDA was touched.
Verdict: pass, with two medium and three low findings, none blocking merge.

This is the second review of this feature. The first covered the encode work
alone and is recorded separately; this one covers the whole branch including
the lanes that followed from the first review's findings.

## Findings

### encode-oom-path-correct | low | termination is provable, ordering and retention verified

Independently re-derived rather than accepted: the planner yields contiguous,
exhaustive, order-preserving buckets whose footprint is items times the padded
longest estimate. On a retry the completed prefix is untouched and replanning
starts at the failing bucket's start, so concatenated output order survives
every replan. Termination is provable because a planned multi-item bucket's
footprint is at most the current budget and the new budget is half that
footprint, so bucket size strictly decreases to the single-item floor, which
re-raises. The allocator flush occurs only inside the two OOM handlers.
Ceilings are lock-guarded, per-instance, and independent between the dense and
sparse paths.

### gpu-lock-discipline-clean | low | each bucket forward holds the lock and nothing else does

Both forwards hold the timed lock across exactly the forward; planning,
transfer, conversion, concatenation and storage all run outside it. The bucket
callback fires outside any hold and swallows its own exceptions, so a
reporting failure can never discard buckets already encoded. The single
consumer is preserved and no module-scope torch import appears in the diff. A
lock-asserting test double proves each bucket forward runs inside its own hold.

### hardening-refuses-nothing-real | low | every newly-refused input traced to its publisher

The reviewer re-traced every field reaching the hardened readers rather than
accepting the claim that none can be negative or non-finite. Timestamps, rates,
ratios, ages, utilisation figures and byte totals are non-negative by
construction; the remaining-seconds policy raises rather than returning a
negative; the two genuinely signed derivations keep their own clamping and are
pinned by tests that distinguish clamping from refusing; and the byte total is
an integer sum, so the count reader's float refusal is unreachable in
production.

### unmerged-lookalikes-are-load-bearing | low | each separation is pinned by a test a merge cannot satisfy

The capability readers answer opposite questions about an absent key, and the
pinning test asserts both answers on the same input, so no single
implementation could pass it. The nested-section reader's absent return
suppresses captioned blocks that would otherwise print as unmeasurable, and the
test asserts that return against the mapping reader's empty dictionary
directly. The envelope reader and the error extractor answer opposite questions
on the identical refusal input and are pinned the same way.

### sparse-oom-invisible-to-telemetry | medium | the per-job OOM counter is dense-only

The sparse encode path shares the planner and the token-denominated ceiling but
has no bucket callback seam, so a sparse OOM lowers the ceiling and retries
correctly while publishing nothing. Under a sparse OOM storm the rate-baseline
verdict correctly reports degraded, but the attached evidence carries a zero
OOM count and a healthy-looking budget, pointing the operator away from the
memory ceiling that caused it. Half-populated evidence is worse than none
because it actively misdirects. The governing decision specifies a per-job OOM
counter as part of encode-stage truth, and this leaves that half delivered.

### calibration-guard-requires-a-model-cache | medium | the guard errors rather than acquires on a cacheless host

The calibration guard loads the dense tokenizer cache-only without first
acquiring it, so on a host that has never cached the model it raises rather
than skipping or downloading. The unit lane runs on a self-hosted Linux runner
while GPU work runs on a separate Windows runner, so the cache is not
guaranteed. Every other model-dependent test in the suite acquires missing
snapshots first through a killable subprocess under an explicit deadline and
only then loads cache-only. Actioned in-branch by applying that established
pattern; a skip, a swallowed exception, or a marker hiding the test were all
ruled out, because this guard is the only thing pinning the chars-per-token
calibration against real tokenisation.

### presentation-renarrows-counted-fields | low | one field narrowed two ways across two surfaces

The encode budget line narrows counted quantities through the measurement
reader while the service-side evidence narrows the same fields through the
count reader. The divergence is only reachable against a foreign daemon
publishing a fractional count, which would render as a fractional item count.
Actioned in-branch alongside the calibration fix.

### oom-tainted-call-banks-a-recovery-success | low | a colliding call still credits the ceiling

A call that absorbed an OOM still banks a success at the ceiling on its
terminal path, so the recovery probe fires marginally early. Probing is bounded
either way. No action taken; recorded with the deferred low-severity set.

### pre-existing-decision-citation-in-a-test-docstring | low | not charged to this branch

A regression-test module docstring cites the decision-record directory. It is
present at the merge base and the branch only repoints one guard within that
module. Recorded rather than actioned, since fixing it would mean editing a
line this branch has no other reason to touch.

## Recommendations

- The sparse telemetry seam is filed as a follow-up rather than fixed here: adding
  it means changing the sparse encode signature and its call sites, which is
  wider than a review-response change should be.
- The calibration-guard fixture acquisition and the counted-field alignment were
  actioned in-branch, since both sit in code this effort authored and both are
  small and self-contained.
- The two remaining low findings are recorded here as their home and need no
  further action.
- The decision's one acknowledged blind spot - a collapse outlasting half a run
  drags the median down to itself and the verdict back to healthy - remains open
  and is a matter for an amendment to the governing record, informed by
  production telemetry from this change rather than by further analysis.
- Not examined, and stated so the gap is not mistaken for coverage: no live GPU
  corpus run was performed, so the token-budget change remains unverified against
  real hardware. That run is the natural first read of the telemetry this branch
  adds.
