---
tags:
  - '#exec'
  - '#service-release-compat'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S06'
related:
  - "[[2026-07-25-service-release-compat-plan]]"
---

# Document the enforced pin and the release field in the service discovery reference

## Scope

- `docs/service-discovery.md`

## Description

- State in the version-discriminator section that the pin is now enforced, and describe
  each refusal case: an unrecognised pair, a half-declared pair, and the tolerated
  pre-discriminator file.
- State that a live lock holder's refused pointer resolves degraded with its own reason
  rather than absent, and why.
- Add a release-compatibility section covering the new field, the three verdicts, why the
  unconfirmed verdict is distinct from the matched one, and why the verdict is a signal
  rather than a gate.
- Add the new field to the interface field table.

## Outcome

The document previously instructed consumers to pin on the pair and refuse a file they did
not understand while the project's own client code did neither. That instruction is now
matched by behaviour, and the document says which cases refuse and which are tolerated
rather than leaving the boundary to a reader's judgement.

The release section is deliberately explicit that the verdict never refuses a request, so
a future reader does not mistake the absence of a gate for an oversight and add one.

## Notes

The field table in this document was already behind its writers - several fields the
daemon publishes were undocumented before this change. Only the field this work adds was
documented; reconciling the pre-existing gap is separate and was not folded in.
