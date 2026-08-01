---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:22b43298fd96dff5a74b21c659c0556c30413e60e0efd87a05216673ff72f6fc'
step_id: 'S57'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Confirm the scan-bounding intent of the retained-point lookup survives the correction, measuring rather than assuming

## Scope

- `src/vaultspec_rag/indexer/_run_ledger.py`

## Description

- Measure the retained-point lookup's scan behaviour before and after the
  predicate removal, by query plan and by timing against a growing generation.
- Add the index the bound actually depends on, at creation
  (`src/vaultspec_rag/indexer/_run_ledger.py:1554`).
- Create the same index on ledgers that predate it, without a schema-version
  bump (`src/vaultspec_rag/indexer/_run_ledger.py:1578`).

## Outcome

The bounding intent did NOT survive the predicate removal on its own, and
asserting that it did would have been wrong. Measuring is what caught it.

The candidate-point table is keyed with the generation first and the point
identity second, so a lookup by point identity alone cannot use that key. The
removed predicate was, incidentally, what made the key usable - which is why the
commit that introduced it saw a bound improve. With the predicate gone and no
other index, the query plan degrades to a full scan of the candidate table.

The timing confirms it rather than the plan alone. Against a generation of a
thousand entries a lookup takes about a tenth of a millisecond; against fifty
thousand it takes nearly four. That is thirty-one times the cost for fifty times
the data - linear in generation size, which is precisely the unbounded behaviour
the original commit set out to prevent, reintroduced by its own repair.

An index on the point identity restores the bound properly. The plan becomes a
keyed lookup, and the measurement goes flat: about fifty-six microseconds at a
thousand entries and fifty-eight at fifty thousand. The bound now rests on an
index, which is where a bound belongs, rather than on a predicate that happened
to make a composite key usable while quietly changing what the query meant.

The index reaches existing ledgers as well as new ones. The schema is built only
when a database is first created, so an addition placed there alone would never
have reached any ledger already in service - including the one whose index this
work is repairing. Bumping the schema version would have reached them, but by
rejecting them: the compatibility check admits only an exact version match, so
every current ledger would have been declared unsupported and rebuilt from
zero. An index is a pure read-path addition that changes no stored data and no
query result, so it is created idempotently on open instead, and the two paths
were verified separately - a fresh ledger carries it at creation, and a ledger
with it removed regains it on the next open with its version untouched.

## Notes

The scaling numbers come from a synthetic ledger built to the real schema and
exercised through SQLite directly, not from the production ledger and not from a
full index run. They establish the shape of the cost against generation size,
which is the question, but they are not an end-to-end indexing benchmark and
should not be quoted as one.

The original commit's stated concern was that a plain join would drive from
every indexed file state. That specific concern is unaffected here: the join
order it introduced is retained, and only the generation predicate was removed.
What the measurement adds is that the join order alone never carried the bound -
the key usability did.

No schema version was changed, so no ledger is invalidated and no rebuild is
triggered by this Step.
