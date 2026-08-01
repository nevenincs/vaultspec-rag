---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:474f43ebbdc3515fb5dc85d6688f64edf4c1de83c23b0460f1dba435c94ae567'
step_id: 'S129'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Collapse the triplicated code-kind admission guard into one shared helper so the boundary invariant has a single owner

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Add `_require_rule_target(rule, expected, *, batch=False)` at
  `src/vaultspec_rag/indexer/_chunk_worker.py:116` as the single owner of the
  content-kind admission invariant.
- Replace the hand-rolled code guard in the scoped worker entry point with a
  call to the helper (`_chunk_worker.py:851`).
- Replace the hand-rolled code guard in the full-pass worker entry point with a
  call to the helper (`_chunk_worker.py:932`).
- Replace the hand-rolled code guard in the batch worker entry point with a call
  to the helper, passing `batch=True` (`_chunk_worker.py:1127`).
- Fold the fourth hand-rolled copy - the document guard in the document stream
  entry point - into the same helper (`_chunk_worker.py:690`).

## Outcome

The invariant has exactly one owner. Four entry points previously restated the
same rule with three separately maintained message strings; they now delegate to
one helper that decides admission and renders the message from one template.

The helper is fail-closed and its semantics are unchanged. It returns early in
exactly two cases: the rule is absent, which is not a boundary crossing because
the default source profile owns that decision upstream, and the rule's target
already equals the expected kind. Every other case raises, as before. No branch
was widened, no target was made permissive, and nothing was relaxed to
accommodate a test.

The scope extension to the fourth site was raised before it was taken and
approved. The three sites named in the Step row were the code guards, but the
document guard was a fourth copy of the same invariant; centralising three of
four would have left the boundary with two owners, which is the condition the
Step exists to remove.

The divergent message strings were resolved structurally rather than textually.
One template, rendering the worker name and expected kind, produces strings that
are byte-identical to the previous hand-written ones for all three cases: the
scoped and full code workers, the code batch worker, and the document worker.
Two consequences follow. An existing integration assertion that matches on the
code worker's message text continues to hold without being touched, and the
batch-versus-single distinction survives as a diagnostic signal instead of being
flattened into a single generic string. A single canonical message was achieved
at the level of the format, which is where the duplication actually lived, not
by discarding information the operator needs when reading a failure.

## Notes

Verification of this Step was not performed by its author. Responsibility for
running the suite sits with the harness operators, and the affected files were
handed to them together with the fixture reconciliation. What the author did run
is recorded in the sibling Step's record and is limited to one file.

The working tree was shared with a second author working concurrently on
unrelated Steps in the same phase. The files listed in Scope are disjoint from
that work, but a whole-tree diff at the time of writing is not attributable to a
single author and should not be read as the boundary of this Step.

No scaffolds, suppressions, or temporary shims were left in the source. The
source carries no reference to this record, the plan, or any Step identifier.
