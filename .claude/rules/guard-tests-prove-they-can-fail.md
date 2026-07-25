---
name: guard-tests-prove-they-can-fail
trigger: always_on
---

# Guard tests prove they can fail

## Rule

- Prove a guard test can fail before trusting it.
- Break the guard, run the test alone, watch it fail on the assertion it names,
  restore, watch it pass. One uninterrupted sequence.
- Never leave a mutation on disk across a pause or a handoff.
- Record both directions where the test's next reader will find them.

## Why

- A passing guard test proves the guard did not crash. Nothing more.
- It cannot tell a rejected forbidden thing from one that never reached the
  check.
- Coverage reporting success over a regressed path is worse than none. It
  consumes the attention that would have gone looking.

## How

- Require the failure to land on the intended assertion, not on an import or a
  collection error.
- Comment the mutation a narrow assertion catches. The next reader loosens an
  unexplained matcher.
- Assert the exact branch. A message shared by several branches passes whichever
  fires.
- Never relax a matcher or edit an expected string to make a guard test pass.
- Applies to guards, interceptions and negative assertions only.
