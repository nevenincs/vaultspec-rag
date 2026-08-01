---
tags:
  - '#exec'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:735d349eeed8d33993cfe411b0b95f4973ce52b4bc702c895a411d65c7a5a14d'
step_id: 'S04'
related:
  - "[[2026-07-25-index-completeness-guard-plan]]"
---

# Compute the published-versus-live completeness fact once on the code search path and carry it on the result envelope beside the indexed count

## Scope

- `src/vaultspec_rag/_index_breadth.py`
- `src/vaultspec_rag/api.py`
- `src/vaultspec_rag/server/_routes.py`

## Description

- Add the shortfall computation to the shared breadth leaf, returning the
  published and live figures rather than a flag so a renderer never re-derives
  the deficit.
- Settle the fact once on the code search path from the count that path already
  takes, so the check adds no store round trip.
- Carry it on the search response's index-state block as a conclusion with its
  figures, present only over a demonstrated shortfall.

## Outcome

Landed in `cfbff066`. A search response now states whether the index answering
it is demonstrably incomplete, and by how much.

Absence of the field means complete or unknowable, and the two are deliberately
indistinguishable to a consumer. A root written by a build that recorded no
breadth has nothing to compare against and must not read as incomplete for want
of evidence.

The empty-result branch carries the fact too. An empty answer over a truncated
index is the more dangerous case, because a confident absence is exactly what a
caller reads as proof that no such code exists.

## Notes

The authorising Step named the service module as the second site. It is not on
the search path - it owns the per-project context and searcher wiring, not
request handling - so the fact is carried in the server route that builds the
index-state block instead. The Step's scope was corrected through the owning
verb to name the file the work actually touched.
