---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S135'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Clear the redundant-cast type diagnostics blocking the lint gate

## Scope

- `src/vaultspec_rag/indexer/_resolved_policy.py`
- `src/vaultspec_rag/search/_result_shaping.py`
- `src/vaultspec_rag/server/_routes.py`

## Description

- Replace the set-membership tag test with a tuple-membership test so the
  container branches narrow the tag for both checkers, and drop the scalar-tag
  cast (`src/vaultspec_rag/indexer/_resolved_policy.py:209`).
- Introduce a typed locator-kind table and resolve the raw payload string
  through it, replacing the inline set guard and the locator-kind cast
  (`src/vaultspec_rag/search/_result_shaping.py:30`).
- Introduce a typed control-mode table and resolve the raw request string
  through it, replacing the inline set guard and the control-mode cast, keeping
  the existing rejection path intact (`src/vaultspec_rag/server/_routes.py:113`).
- Move the locator-kind and mapping imports into the type-checking block, where
  the new annotations need them.

## Outcome

All three diagnostics are cleared without a suppression, an ignore comment, or a
cast - but the first attempt was wrong, it regressed the gate, and the
correction is the substance of this Step.

The Step was framed as removing three redundant casts, and that framing was
false. One checker reported the casts redundant; the stricter checker the
project actually gates on could not narrow those values without them. Two
checkers, opposite verdicts, the same three lines. Deleting the casts satisfied
the first and produced three fresh argument-type errors at exactly the lines the
Step had just edited - three warnings traded for three errors. The author did
not catch this; the harness operator did, in verification. Nothing in reading
the code would have surfaced it, because the disagreement is between the
checkers rather than in the source.

Two tempting resolutions were rejected. Re-adding the casts would restore the
strict checker's green while reinstating the original warnings, relocating the
failure rather than fixing it and leaving the two checkers permanently in
conflict at these lines. Suppressing either complaint was forbidden outright and
would have been the precise decay this codebase has an effort hunting. The
remaining option, and the one taken, was to make the narrowing genuine so both
checkers follow it unassisted.

The operator's report contained the diagnosis for the first site. The reported
residual type was the scalar union plus the two container literals, meaning the
equality test against the mapping tag had narrowed while the membership test
against the container tags had not. The strict checker narrows membership
against a tuple or list literal but not against a set literal. Changing the
braces to parentheses is therefore not cosmetic - it is the difference between a
test the checker can follow and one it cannot. No runtime check was added there,
and deliberately so: the scalar thaw helper already raises on an unrecognized
tag, so the runtime guarantee the type expresses was present before this Step
and did not need restating.

The other two sites could not be repaired that way, because each subject is a
raw string arriving from untyped input rather than an already-typed union, so no
membership test can be relied upon to produce the literal type. Both now resolve
the raw string through a small table mapping each admissible value to itself,
declared as returning the literal type. The lookup yields the typed value or
nothing, an ordinary runtime check every checker follows without special
narrowing support. In the result-shaping module an unresolved kind returns no
locator, as before. In the routes module the resolution replaced the existing
membership guard, so an unexpected control mode still raises the same invalid
request error and still leaves the route with a 400 - confirmed by following the
code through the job error envelope and the outcome status mapping, where any
invalid-prefixed code other than an invalid transition maps to 400. The route
rejects the value; it does not merely narrow it. A client-supplied string is now
resolved into a literal type by a check that runs, never asserted into one.

That rewrite also improved the code beyond satisfying the checkers. At both
sites the admissible set had been an inline literal duplicating a type alias
with no enforced relationship between them, so the two could drift silently. The
table is now a single declared source of truth that the checker verifies against
the alias.

One intermediate edit added a lint suppression to silence a rule that would have
objected to an equality chain. It was removed within the same Step. A
suppression-free form existed and is the one that shipped.

## Notes

The general lesson, recorded because it will recur. A cast that one checker
calls redundant may be load-bearing for another, so a tool reporting a cast as
unnecessary is not by itself sufficient grounds to delete it. Confirm against
the checker the project gates on before removing, and when the two disagree, do
not pick a side and do not silence either: establish the type with a check the
runtime actually performs. That satisfies every checker, needs no suppression,
and is better code, because a type guaranteed by a real check is stronger than
one asserted by a cast. Checker-driven edits carry a second hazard visible here
too - both attempts touched the same three lines, so the regression landed
exactly where the Step had just claimed success.

The author ran neither type checker. Both the original defect and the diagnosis
that made the fix possible came from the harness operator, and the first attempt
shipped broken precisely because the author reasoned about narrowing from
declared types and control flow - sound for one checker, wrong for the other.
Any future claim from this author that a cast is redundant should be treated as
unverified until the gating checker confirms it.

Behaviour was verified rather than assumed after the rewrite, because two of the
three changes altered runtime control flow rather than only annotations. Every
canonical option tag was round-tripped through freeze and thaw with the list and
tuple distinction preserved, the locator helper was exercised with a valid kind,
an unknown kind, and a non-string kind, and the result-shaping, server-route,
policy, and desired-state modules were run - seventy-six tests, all passing. The
rejection path at the routes site was confirmed by reading the status mapping
rather than by issuing a request, which is the weaker of the two forms of
evidence and is named as such.

Re-verification of both checkers is the harness operator's and had not returned
when this record was written. The three argument-type errors should be gone with
no diagnostics in their place, no unused-import finding, and no redundant-cast
reappearing. The whole-project strict run reported eighty-seven errors in total,
of which only these three trace to files this Step touched; the remainder are
pre-existing or belong to other in-flight work and were left alone.
