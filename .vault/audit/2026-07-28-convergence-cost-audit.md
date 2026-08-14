---
tags:
  - '#audit'
  - '#convergence-cost'
date: '2026-07-28'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:afb9660fe4aca7fbfed89f5aa6bc4c64a390100e0371ca89fa1ac4a5d1e2e964'
related:
  - "[[2026-07-28-convergence-cost-plan]]"
  - "[[2026-07-28-convergence-cost-adr]]"
---

Verification of the stat-evidence rehash gate and the scoped-convergence retention
change, executed against the plan and its accepted decision record. Both changes landed
as `1bcde198`.

## Scope

The two behaviours the accepted decision authorised, and nothing beyond them:

- the stat-evidence rehash gate - reuse on an unchanged stat identity, refusal on a
  visible change, and the discard paths for a racy, corrupt, defective, or
  wrong-schema sidecar - across the code, document, and vault indexers;
- scoped convergence retention, including the interruption, mid-attempt-success,
  failure, crash-recovery, construction-over-pending, and cross-instance refresh
  promotion paths.

Evidence was taken from the gate and retry test modules, from three mutations applied
to the gate and one to retention, and from a full unit-tier run.

Out of scope: the observability gap the live incident exposed during verification. It
is recorded below because it happened during this pass, not because this change caused
it; it is grounded and decided in its own records.

## Findings

### gate-verification | low | Every gate behavior is test-proven, including failure directions

19 gate tests cover reuse, stat-visible change, racy refusal, corrupt and defective
sidecar discard, schema-version discard, prune, unwritable-sidecar tolerance, OSError
parity, and per-domain wiring for the code, document, and vault indexers. Reuse is
proven without mocks by swapping file content under an identical stat identity. Three
mutations - racy conjunct removed, validator made row-salvaging, reuse disabled - each
failed exactly the naming assertions and passed restored, in uninterrupted cycles.

### retention-verification | low | Scoped retention holds and every escalation path still fires

Interruption and mid-attempt-success retention are pinned by dedicated tests, and both
were proven failable by restoring the forced escalation. Failure, crash-recovery,
construction-over-pending, and cross-instance refresh promotion keep their original
assertions and pass unchanged. The full retry module passes: 29 tests.

### unit-tier-interference | low | Two Qdrant-supervision tests error only under parallel load

The full unit tier reports 3214 passed, 1 skipped, with 2 setup errors in
Qdrant-supervision tests that pass immediately when run alone; a live GPU daemon and
service load shared the machine during the tier run. Untouched by this change's diff;
tracked as environmental.

### incident-during-verification | medium | Live incident exposed a separate observability gap

During verification a vault index job froze at a slice boundary for over five minutes
under external GPU saturation with no surface reporting cause. Grounded and decided
separately: see the index-observability research and decision records; implementation
is dispatched.

## Recommendations

- Land the index-observability implementation so a starved encode pass, a backend
  fault, and a hang stop looking identical (decision already accepted).
- Extend gate evidence recording to full-index runs so the first incremental after a
  rebuild is warm; ownership dispatched to the hashing-throughput work.
- Re-run the two Qdrant-supervision tests in an isolated tier once to rule out an
  ordering dependency independent of machine load.
