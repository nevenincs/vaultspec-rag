---
tags:
  - '#audit'
  - '#gpu-admission-unreadable'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:b0379c972a0ee8e1aa20b161eb2ad2634b90fd2ddbfe7c6c7c4249748b92bdce'
related:
  - "[[2026-08-14-gpu-admission-unreadable-plan]]"
  - "[[2026-08-14-gpu-admission-unreadable-adr]]"
  - "[[2026-08-14-gpu-admission-unreadable-reference]]"
---

# `gpu-admission-unreadable` audit: `the unreadable-device refusal as landed`

## Scope

The verify pass over the landed unreadable-device refusal: the gate module
`src/vaultspec_rag/_gpu_admission.py`, its suite
`src/vaultspec_rag/tests/test_gpu_admission.py`, the renamed refusal renderer's
only other caller in `conftest.py`, and the three production consumers of the
verdict - `src/vaultspec_rag/_gpu.py`, `src/vaultspec_rag/_job_evidence.py`, and
`src/vaultspec_rag/server/_lifespan.py`.

Audited because the plan closed all three of its Steps with no verification
record against it, and because the change adds a refusal to a gate every model
load passes through: a defect here does not degrade a feature, it either refuses
work on a healthy card or keeps admitting onto a dead one, which is the fault the
change exists to end.

The review asked three questions. Whether the refusal is reachable in production
and not only over supplied values. Whether the fail-open the change narrows is
still intact for the transient case it was right about. Whether the rename of the
refusal renderer left anything pointing at the old name.

## Findings

### documented-failure-contract | low | the loader's own docstring named only contention among its refusals

`load_torch` is the single entry point every local-mode compute load passes
through, and its docstring enumerates the conditions it raises on. The change
added a second `RuntimeError` condition to that surface without extending the
enumeration, so the documented contract listed a card with no room and omitted a
card that has stopped answering. A caller reading it would have concluded the
unreadable case still reached the loader. Corrected on this branch; the
enumeration now carries both refusals.

### export-surface-completeness | low | two new public functions were absent from an otherwise exhaustive `__all__`

The gate module's `__all__` lists every one of its non-underscore names, so the
list is load-bearing as a statement of the module's surface rather than
decorative. `observe_unreadable_streak` and `judge_device_reading` were added
without being listed, which breaks that invariant - and the first of the two is
reached from outside the module, by the suite's isolation fixture. Corrected on
this branch.

### diagnostic-cadence-feeds-the-ledger | low | the daemon's own health polling advances the streak, at a rate no test pins

Every reading the process takes feeds the ledger, diagnostics included. The
verdict is what the jobs listing and the health payload publish, and
`_job_evidence.py` caches a device-load snapshot for five seconds, so a polled
daemon on a device that has stopped answering can cross the limit on diagnostic
readings alone, in roughly fifteen seconds, without a load ever being attempted.

This is the intended direction and the governing record names it explicitly as
the accepted weakness of counting rather than timing. It is recorded here because
the record reasons about it in prose and nothing asserts it: the real-time window
the limit spans is set by an observation cadence that lives in a different module
from the constant, and a later change to either moves it silently. No defect, and
no action beyond knowing it before the numeral is moved.

### parent-record-status | low | the governing parent decision still reads `proposed` after landing

`2026-07-29-gpu-admission-gate-adr` describes a gate that has been in production
since it was written, and this feature's own record carries the same status. The
status check reports clean against the taxonomy either way, and the sibling
records are split between the two forms, so this is a corpus-wide convention
question rather than anything this feature introduced. Left alone deliberately:
flipping one record inside a feature branch would make the corpus less consistent
rather than more.

### verified-no-finding | low | the three things most likely to be wrong here were checked and are not

Recorded because their absence is the substance of the audit. The refusal is
reachable in production, not only over supplied counts: the window's supplied
reading and its probed reading both route through the one judgement that consults
the ledger, and the suite drives that composition through a real lock rather than
re-deriving the predicate. The single-reading fail-open survives intact, asserted
at the boundary in both directions, so the change narrows the fail-open rather
than replacing it with the refuse-on-first option the record rejected. The
renderer rename left nothing behind - the one other caller moved with it, and no
reference to the old name survives anywhere in the tree, so no shim was left to
drift.

The probe the gate reads through never raises, which closes the one path that
would have bypassed the ledger: a driver refusing the memory query yields a
reading that reports presence and no figure, which is exactly what the ledger
counts, rather than an exception that would have been reported as an absent
device and never counted at all.

## Recommendations

Nothing blocking. The two defects found were repaired on the branch under audit
and need no follow-on work.

Before the tolerance constant is moved in either direction, measure the
observation cadence it will actually be exposed to rather than reasoning about
load attempts alone. The constant is a count and the cadence lives elsewhere, so
the real-time window it spans is a product of two figures that no single place
states.

The parent record's status is a corpus-wide question and belongs to a curation
pass over the decision corpus, not to this feature.
