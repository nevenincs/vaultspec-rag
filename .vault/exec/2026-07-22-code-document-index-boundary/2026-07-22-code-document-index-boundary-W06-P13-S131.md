---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:f429f9737a29603fdb8b13d514b666a8ae568a7a40bdd7b9dbef1cadb3898950'
step_id: 'S131'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Reconcile the search source-type rename across the CLI search contract and service diagnostics so one vocabulary spans adapter and route

## Scope

- `src/vaultspec_rag/tests/test_cli_search_safety.py`
- `src/vaultspec_rag/tests/test_service_search_diagnostics.py`

## Description

- Normalize the diagnostic index-state source through the closed source-type
  enum instead of stringifying whatever the caller passed
  (`src/vaultspec_rag/server/_routes.py:255`).
- Narrow that helper's parameter from `object` to the enum-or-string union so
  the permissive escape hatch is gone from the signature as well.
- Retarget the shared CLI search-request fixture to the canonical wire
  spelling (`src/vaultspec_rag/tests/_cli_helpers.py:217`).

## Outcome

One vocabulary now spans adapter and route, and the two failures that pointed
in opposite directions turned out to have opposite verdicts.

The route was wrong. The diagnostic helper accepted an untyped value and, for
anything that was not already an enum member, passed `str(...)` of it straight
into the response envelope. That is how a legacy spelling reached a caller
under a field the decision requires to be closed: the helper had no opinion
about the vocabulary at all, it merely echoed. It now parses through the shared
parser with aliases permitted, so a legacy input normalizes to the canonical
value rather than surviving as itself. Both production call sites already pass
validated values, so the parse cannot fail in practice; the change removes a
channel, not a behaviour anyone depended on.

The fixture was wrong in the other direction. The adapter already sends the
canonical spelling, because the transport resolves the caller's legacy spelling
through the same parser before building the payload, and the service contract
accepts canonical values only. A fixture asserting the legacy spelling on the
wire was therefore describing a request the adapter had stopped sending and the
route would have rejected. It now asserts the canonical value.

The underlying inconsistency was real and is what the two opposed failures were
reporting: the outbound boundary had been converted to normalize, the inbound
diagnostic had not. Aliases now live in exactly one place - the parser, at the
boundaries that opt into them - and no adapter or route re-spells a source type
on its own.

## Notes

Both touched modules were run targeted by the author and passed; the adjacent
source-type and CLI search modules were run as collateral checks and passed. The
full suite and the static gates were not run by the author and are the harness
operator's to report.

Other modules still construct result objects carrying the legacy label in a
different field - the result's own source label rather than the request's type.
Those were left untouched. They are a separate concern from this Step's request
vocabulary, they were not failing, and the decision addresses result labels
under its own heading.
