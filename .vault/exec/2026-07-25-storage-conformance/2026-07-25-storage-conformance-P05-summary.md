---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# `storage-conformance` `P05` summary

## Description

Closes the feature: the gate set green, and the delivered work reviewed against
the decision that authorized it.

The gate step had already run once and is not re-opened here. What this closeout
adds is the gate it missed. The earlier run enumerated ruff, ruff format, type
checking, and the citation gate, found them clean, and recorded a clean sweep.
The complexity gate was not in that list and had been failing since this
feature's first implementation commit, where per-collection identity parsing was
added inline to the manifest loader and pushed its cognitive complexity past the
threshold. Extracting the per-record parse returns it to green. A closeout that
names its gates individually will keep missing whichever one it does not name.

The review found seven of the decision's eight implementation clauses
implemented where it put them, and one delivered short: the storage survey
reports the stamped dense model where the decision asks for the per-collection
verdict and the whole stamped identity. That is the single plan verification
criterion not met. It is left open rather than patched, because a verdict needs a
live geometry read the decision confines to the ensure cache, and the survey holds
no store instance - closing it means a new seam between the daemon's verdict cache
and the survey, which is a decision rather than an edit.

Two further gaps are recorded rather than closed: a nonconforming collection's
readability is proven by a successful store open rather than by a search
returning results, and one plan criterion asks for reclamation behaviour the
decision does not authorise and that would exempt every pre-upgrade namespace
from reclamation permanently.

Verification for this phase's own change. Gates: ruff check and format clean,
`ty` clean over the package, basedpyright reporting no errors, warnings or notes
on every changed file, citation gate clean, and the complexity gate green for the
first time since this feature began. The storage surface passes at 113 tests
across the manifest, identity, survey, ops, conformance-surfacing and
verdict-parity modules; the storage integration files pass at 20 of 21, and the
whole unit selection passes at 2683.

The one integration failure was settled, not assumed. An unwaited-reconcile
timing test failed with an HTTP read timeout under concurrent load, then passed
alone in four seconds and as its own six-test group. Its path reads no manifest
and the test predates this branch, so nothing here is reachable from it. That is
the second consecutive closeout of this feature to make this determination on a
different test, which the audit records as structural rather than incidental.

The unit figure is not compared against the number the earlier gate step
recorded. That run used a different marker selection than this one - the
deselected counts differ - so the two totals are not the same measurement, and
subtracting them would manufacture a delta. What is asserted is that this run
reported no failures and that the phase added nine tests.

- Created: `.vault/audit/2026-07-25-storage-conformance-closing-review-audit.md`
- Modified: `src/vaultspec_rag/storage_manifest.py`
