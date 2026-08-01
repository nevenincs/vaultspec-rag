---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:f942fe0d9c3e90fdf6ecb2370254f346b89cb6805cd6ddb33e8cb71818365aa1'
step_id: 'S130'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Reconcile preprocess and chunk-worker fixtures with the code and document admission boundary so document-targeted rules exercise the document path

## Scope

- `src/vaultspec_rag/tests/test_chunk_worker_parity.py`
- `src/vaultspec_rag/tests/test_preprocess_batch.py`
- `src/vaultspec_rag/tests/test_preprocess_worker.py`

## Description

- Route the extracted-unit assertion through the document worker and assert
  document payload fields
  (`src/vaultspec_rag/tests/test_preprocess_worker.py:75`).
- Route the extraction-status assertion through the document worker
  (`test_preprocess_worker.py:97`).
- Route the cache-hit assertion through the document worker
  (`test_preprocess_worker.py:118`).
- Add a test asserting both code entry points refuse a document-targeted rule
  (`test_preprocess_worker.py:108`).
- Retarget the blocking scheduler rule to the code kind
  (`src/vaultspec_rag/tests/test_chunk_worker_parity.py:249`).
- Retarget the fatal-abort rule to the code kind
  (`test_chunk_worker_parity.py:339`).
- Retarget the shared batch rule factory to the code kind
  (`src/vaultspec_rag/tests/test_preprocess_batch.py:318`).
- Retarget the spawn-counting context to the code kind
  (`test_preprocess_batch.py:508`).
- Retarget the shared counting rule factory to the code kind
  (`test_preprocess_batch.py:653`).
- Retarget the pool fail-policy rules to the code kind
  (`test_preprocess_batch.py:720`).
- Update the worker module docstring to describe the boundary it now exercises.

## Outcome

The fixtures now assert the boundary instead of tripping over it. The
reconciliation was not uniform, because the fourteen failures had two distinct
causes and only a per-file reading separates them.

In the preprocess worker module the fixture was already correct. Its rule
declares the document kind, which is the honest description of a hook that
extracts page units from an opaque binary source. The defect was on the calling
side: three tests took that correctly-declared document rule and drove it
through the code worker, then asserted code chunk fields on the result. Those
three now call the document entry point and assert document payload fields -
content, anchor, locator kind and value, source path, and extractor identity.
The rule itself was left untouched, because changing it would have destroyed the
only document-targeted fixture in the module to make a code-path call site
pass.

In the parity and batch modules the opposite was true: the rules were genuinely
mislabelled. Every one of those fixtures drives the code pool - the bounded
scheduler window and its refill behaviour, fatal abort propagation, batch group
dispatch, spawn counting, and cache reuse - and every one asserts code chunk
fields on the result. A document target on a rule whose only consumer is the
code batch worker described something the test never exercised. They now declare
the code kind, which the decision permits as an explicit route admitting
unconventional source. The two shared rule factories were changed once each,
which also covers the tests that pass those same rules to the batch runner
directly; that runner does not inspect the target, so those tests are unaffected.

One test was added rather than repaired. It asserts that both code entry points
refuse the document-targeted rule. This is the difference between fixtures that
no longer trip the guard and fixtures that assert the boundary: without it, the
module would exercise the document path and the code path but would never state
that the crossing is forbidden, which is the property the decision actually
requires.

No mock, stub, patch, fake, skip, or expected-failure marker was introduced, and
no production behaviour was weakened. The guard remains fail-closed; every
change here is to what the tests declare and which entry point they call.

## Notes

Verification is incomplete and the gap is stated exactly. The preprocess worker
module was run once by the author and reported seven passed. The parity and
batch modules were not run by the author at all; they are authored but
unverified, pending the harness operator's tally. No claim is made here about
the aggregate failure count, and the fourteen figure comes from the Step
assignment rather than from an observation made while writing this record.

Two assumptions are recorded because they are the most likely places for the
unverified work to be wrong. The first is that no test asserts a rule's target
value directly, which would make the retargeting visible as a new failure. The
second is that the retargeted rules genuinely have no document-path consumer;
this was established by reading every call site of the two shared factories, not
by execution.

The working tree was shared with a second author working concurrently on other
Steps in this phase. A verification run taken during that overlap covers a tree
with several Steps partly applied, so any tally from it is provisional and
cannot be cleanly differenced against the earlier baseline. This was flagged to
the coordinator before the handoff.

An earlier targeted run in this session was performed before an instruction
arrived limiting the author to authoring only; the remaining verification was
handed off rather than completed. No scaffolds were left in the tests, and no
test or source file references this record, the plan, or any Step identifier.
