---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:03a816bca0cd95dec86297959f958af6f6f0dc8f3659ec2254d9dbc7db981282'
step_id: 'S03'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Extract discovery and admission into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Extract the discovery and admission responsibility into its own collaborator
  module.
- Move the admission and preflight types out of the indexer entirely rather
  than aliasing them.
- Hold the indexer to consuming the collaborator through a single accessor.
- Verify behaviour preservation against the full unit suite.

## Outcome

The first seam is cut. Discovery and admission - tree scanning, ignore-rule
application, admissibility classification, admission counting and sampling, and
the preflight types - now live in a collaborator the indexer holds rather than
in a region of one class.

The indexer dropped from 3938 lines to 3294, and the collaborator is 498. Of the
377 lines removed, 36 came back as a larger import block, a discovery accessor,
and the delegating one-liners, for a net reduction of 341.

Every type and method definition moved; nothing was copied. The moved bodies
were diffed against their originals programmatically rather than by eye, and
every executable line is byte-identical, with the only differences a constant
rename and two docstring edits. The nine methods retained on the indexer are
delegating façades of four to twelve lines, each being a signature, a docstring,
and one call into the collaborator. No call site reaches an old code path,
because no old code path remains.

The admission and preflight types are re-exported from the indexer, and that is
deliberate rather than residue: roughly forty external call sites across the API,
jobs, dispatch, watcher, and server modules import them from their historical
home, and rehoming them would have turned a contained extraction into a
tree-wide import churn. The re-export is a name alias over a single definition,
not a second definition.

Four ignore-collection helpers were removed outright rather than moved. Their
docstrings claimed they were kept as methods so callers and tests could
monkeypatch them, and a repo-wide search across all file types found zero
callers of any kind.

Behaviour preservation holds. The full unit suite passes at 2568 tests against
the seamed tree, and the indexer, checkpoint, and ledger suites pass together.
No test assertion was weakened, skipped, or adjusted to accommodate the move,
which was the one hard constraint on this Step: a seam that requires changing an
assertion about indexing behaviour is a seam in the wrong place.

Gates on the extracted scope: lint clean, no absolute imports in the new module,
type check clean, citation gate clean. The new module carries no development
metastate.

## Notes

The single-GPU-consumer constraint is untouched. The collaborator owns no
encoding path, no lock, and no queue; the indexer retains orchestration and the
one in-process consumer it already had. Seams here are ownership boundaries, not
concurrency boundaries, and this one did not become the latter.

Two pieces of concurrent work in the same worktree complicated verification and
are worth recording, because neither is a defect in this Step.

Relocating the decorated types removed an import while their definitions still
stood, so for a window every module on that import chain failed at collection.
That transient break blocked a sibling Step's verification. The cause was
dispatching two executors into one worktree on the reasoning that they targeted
different files; different files still share an import graph.

Separately, a concurrent effort began removing the unreachable chunking helpers
and the second collect-into-a-list pipeline identified by the duplication sweep.
That work deletes three hundred lines from the same module and repoints the tests
that were the dead pipeline's only callers. Mid-flight it leaves the indexer unit
suite red, since those tests still reach symbols that have gone. It is not part
of this Step and its state is not attributed here.
