---
name: guard-tests-prove-they-can-fail
---

# Guard tests prove they can fail

## Rule

A test whose subject is a guard, an interception, or a negative assertion is not
considered verified until someone has observed it fail for the intended reason.
Break the thing it defends, watch it go red, restore, watch it go green - as one
uninterrupted sequence - and record both directions where the test's reader will
find them.

This is a new obligation rather than a description of existing practice; most
tests in this repository have never been through it.

## Why

A passing guard test tells you the guard did not crash. It does not tell you the
guard is reachable, that the assertion binds to the property it names, or that an
interception the test depends on still intercepts. Three failures of exactly this
kind surfaced in a single day's work.

A reranker's coverage passed while the code under test scored display snippets
instead of real content: the tests exercised the regressed path and reported
success. That is worse than absent coverage, because absent coverage invites
someone to look, while false coverage consumes the attention that would have
gone looking.

A set of tests patched a helper by package attribute, which worked only because
the code resolved that name at call time. Repointing the call to a bound import
would have left every patch inert - the tests would have called the real
implementation, taken an unreachable branch, and still passed, while no longer
testing the comparison they existed for.

An admission guard rendered three distinct refusals from one template. An
assertion matching the shared part of the message passed whether or not the
argument selecting the branch was still supplied; removing that argument left the
rejection intact and changed only the wording, so the test that existed to defend
the argument would not have noticed its removal.

In all three the green tally was worth nothing on its own, and in each case the
mutation took under a minute.

## How

- **Good:** before trusting a guard test, mutate the guard so the forbidden thing
  is permitted, run the test alone, and require it to fail on the assertion you
  expect rather than on any failure. Restore, re-run, require green. Do it in one
  sequence and never leave the mutation across a pause or a handoff - a weakened
  security check on disk is indistinguishable from a broken one to anyone who
  walks in.
- **Good:** record both directions in the artefact the test's future reader will
  reach - an execution record, or the commit body when there is no record. A
  proof that lives only in conversation is gone by the next reader.
- **Good:** when the assertion depends on something narrow - a specific message
  prefix, a patched symbol's binding site, an exact call count - say so in a
  comment, naming the mutation it catches. Otherwise the next reader loosens it
  as an over-specific match and silently restores the hole.
- **Bad:** accepting a green run as verification for a negative test. It cannot
  distinguish "the forbidden thing was rejected" from "the forbidden thing never
  reached the check".
- **Bad:** asserting only the shared part of a message that several branches
  render, when the test's purpose is to distinguish one branch from another.
- **Bad:** repointing, renaming, or reorganising a symbol that tests intercept,
  and treating the suite staying green as evidence the interceptions survived.
- **Bad:** adjusting an expected string or relaxing a matcher to make a guard
  test pass. A guard test failing on its message rather than on a missing
  rejection usually means the branch selector changed, which is the defect the
  test was written to report.

## Scope

The obligation is on guards, interceptions, and negative assertions - tests whose
subject is that something does not happen, or that a check fires. Ordinary
positive tests are outside it: their subject occurs, so a green run already
demonstrates the path was taken.
