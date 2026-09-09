---
tags:
  - '#audit'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:bc78a9f1cddba07123e57a5e13465ec7e28063322e36f7a7e495d6b91ce860b4'
related:
  - "[[2026-09-08-incremental-publication-cost-adr]]"
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# `incremental-publication-cost` audit: `S40 fail-closed proof audit`

## Scope

Reviewed the amended S40 scope, execution record, production snapshot changes, and
document escalation guards against the accepted canonical-proof decision. The review
covered same-snapshot proof ancestry validation, open-receipt classification,
non-mutating missing and old-schema refusal, audit non-seeding, and the prohibition on
fallback or migration authority.

## Findings

### receipt-error-classification | medium | Malformed receipt values escape the dedicated corrupt-receipt outcome

`_mutation_rows`, `_delta_rows`, and `_hydrate_receipt` in
`src/vaultspec_rag/indexer/_run_ledger_publication.py:293`,
`src/vaultspec_rag/indexer/_run_ledger_publication.py:367`, and
`src/vaultspec_rag/indexer/_run_ledger_publication.py:456` catch `TypeError` and
`ValueError`, but the shared persisted-column validators raise
`RunLedgerCorruptionError`. A current-schema open receipt whose persisted integer or
text column is malformed therefore reaches the audit boundary as
`RunLedgerCorruptionError` instead of the required `corrupt_receipt` reason. A runtime
probe with a non-integer `parent_revision` confirmed `rebuild_required` with
`error_kind` equal to `RunLedgerCorruptionError`. The guard at
`src/vaultspec_rag/tests/test_document_index_escalation.py:436` covers only a
well-formed receipt with a semantic parent mismatch, so it does not exercise malformed
persisted receipt data.

Resolved during review. Receipt hydration now translates persisted-column corruption
through the dedicated corrupt-receipt constructor, and a malformed integer-column guard
covers the exact result before storage opens. The escalation module passed with eleven
tests, and the existing valid-open-receipt audit guard passed independently, confirming
that ordinary publication contention remains a retryable conflict.

## Recommendations

No outstanding recommendations. The execution-record Scope is synchronized with the
amended plan.
