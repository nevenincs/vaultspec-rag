---
tags:
  - '#exec'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:944bd071fd5836df70f485e400158387023d23d422e84f6d27f79d1d6ccb4b70'
step_id: 'S06'
related:
  - "[[2026-07-25-index-completeness-guard-plan]]"
---

# Prove the completeness warning can fail by suppressing the signal over a truncated index, observing the intended failure, restoring, and observing the pass

## Scope

- `src/vaultspec_rag/tests/test_cli_search_safety.py`
- `src/vaultspec_rag/tests/test_service_search_diagnostics.py`

## Description

- Add four CLI tests driving the real command against a stub service that
  returns a real wire envelope: warning with results, warning over an empty
  answer, silence when complete, and figures carried verbatim in JSON mode.
- Add two service-side tests pinning both directions of the emission: the block
  is present with its figures over a shortfall, and absent when breadth is
  unknown.
- Prove each direction can fail, and record both directions in the test
  docstrings.

## Outcome

Six tests, all passing, and the guards proven able to fail on the assertion
each names:

| Test                          | Mutation                          | Failure observed                                   |
| ----------------------------- | --------------------------------- | -------------------------------------------------- |
| warns over returned results   | suppress the CLI shortfall branch | missing `holds 4 of the 421 sections it published` |
| warns over an empty answer    | suppress the CLI shortfall branch | missing `holds 4 of the 421 sections it published` |
| service carries the shortfall | invert the emission guard         | `KeyError: 'shortfall'` on the block lookup        |
| service omits it when unknown | make emission unconditional       | `assert 'shortfall' not in state`                  |

Under the suppression mutation the empty answer reads "No source code results
found ... Indexed source code sections: 4" - precisely the silent false negative
the feature exists to stop, which is the clearest available evidence that these
tests watch the right thing.

The assertions name the figures, not the word "warning". A bare substring match
would pass on a warning that omitted the deficit, and the deficit is the part an
operator acts on.

## Notes

One candidate mutation was rejected rather than recorded as a proof. Inverting
the emission guard makes the omit-when-unknown test fail inside the production
call with a type error rather than on its assertion, which proves the branch
raises, not that the test is watching it. An unconditional-emission mutation was
used for that direction instead.

A second discarded candidate would have mutated the stub service in the test
file itself. That proves only that the stub is wired up, not that the guard
holds, so it was dropped rather than written down as evidence.
