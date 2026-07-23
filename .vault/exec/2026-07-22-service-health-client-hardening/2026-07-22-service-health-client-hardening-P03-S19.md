---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-23'
step_id: 'S19'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Remove the command-line probe's separate implementation once no call site depends on it, leaving at most a thin delegation to the single owner

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Delete the command-line probe implementation and its module export.
- Delete the redirect-refusing handler it owned, now that the transport owns one.
- Remove the probe from the package exports and the test-helper export list, and
  correct two module docstrings that described it.

## Outcome

The duplication is gone. One implementation of the health call exists, in the
service-client layer, and the symbol no longer resolves anywhere in the package.

The redirect handler went with it. That duplication was created deliberately in
the first Phase and recorded at the time as transient, on the explicit basis that
this Step would delete it rather than leave two. It did, which closes a loop that
would otherwise have depended on memory.

The precondition set for this Step - confirm nothing outside the enumerated sites
reaches the probe - found a consumer the plan had missed, recorded in its own
Step. Removal happened only after that consumer was repointed.

## Notes

Not executed by the author.

Two module docstrings referenced the probe and would have been left describing a
function that no longer exists; both were corrected here rather than deferred,
because a docstring naming a deleted symbol is the kind of small false statement
that survives for years. An unused JSON import went with the function that used
it, and the handler's deletion removes the last reason that module constructed
HTTP openers at all.
