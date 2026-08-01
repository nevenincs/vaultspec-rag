---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:9be641cfcc2b632c6e799b0d0fca403b06bf9d1b2eceb2b35570beaad62968cf'
step_id: 'S132'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Reconcile the readiness response shape and empty-query validation ordering with the shipped support-profile and degraded-reason fields

## Scope

- `src/vaultspec_rag/tests/test_readiness.py`
- `src/vaultspec_rag/tests/test_search_quality_fixes_unit.py`

## Description

- Add the shipped support-profile and degraded-reason fields to the exact-set
  readiness assertion and assert the derivation that binds degraded reasons to
  the non-ready dimensions (`src/vaultspec_rag/tests/test_readiness.py:151`).
- Refresh the readiness facade docstring, which still enumerated the pre-schema
  response shape (`src/vaultspec_rag/api.py:1042`).
- Carry a human-readable message on the unknown-source-type rejection so the
  400 matches every other rejection on the route
  (`src/vaultspec_rag/server/_routes.py:125`).
- Carry the same message on the clean route's identical rejection
  (`src/vaultspec_rag/server/_routes.py:1648`).
- Retarget the empty-query fixture to the canonical wire spelling
  (`src/vaultspec_rag/tests/test_search_quality_fixes_unit.py:106`).

## Outcome

The readiness half resolved in favour of the code, the validation half against
it, and neither verdict was the one the failure text suggested.

On readiness, the two fields are deliberate. History settles it: the commit that
exposed document generation readiness added them, and the earlier commit that
added the storage-schema descriptor added its field and updated this same
exact-set assertion in the same change. The assertion is the boundedness
contract for the report, and the convention is that a deliberate addition
updates it. The later commit simply missed that half. The assertion was
refreshed rather than loosened, because an exact set is the only form that
keeps readiness from accreting into a general health console - the property the
surrounding class exists to defend. A derivation assertion was added alongside
it, binding the degraded reasons to the details of the non-ready dimensions, so
the two views in the report can never disagree. The facade docstring was
describing a response shape two commits stale and now matches.

On validation ordering the shipped order is correct and was kept. The source
type is the request's addressing: it selects which domain the query is even
against, and the decision requires it parsed as a closed enum with unknown
values rejected as structured errors. Checking it before the query's contents is
the right order, and reordering to satisfy a fixture would have inverted a
contract to accommodate a stale spelling. The fixture was posting a legacy alias
to a canonical service route, which that route is correct to refuse.

The genuine defect was underneath, and it was the missing-key error rather than
the status code. The unknown-source-type rejection built its envelope from the
error kind and the structured payload but omitted the message, while every other
rejection on the same route carries one - as does the transport's envelope for
this very error. A caller could not read a reason from the one rejection most
likely to need explaining. Both occurrences were fixed, not just the one the
fixture reached, because leaving the second would have knowingly kept an
identical defect one route away.

## Notes

Both touched test modules were run targeted by the author and passed. The server
route module and the source-type module were run as collateral checks against
the envelope change and passed. The full suite and the static gates were not run
by the author.

The reindex route's equivalent rejection was read and left alone: it routes
through the shared job-error helper, which already supplies a message, so it did
not carry the defect.

The readiness verdict rests on commit history rather than on any statement in
the decision record, which does not name the readiness response shape. If the
intent behind exposing those fields was ever narrower than the report-wide
addition that landed, this record is the place that assumption would be wrong.
