---
tags:
  - '#audit'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:8fad43b328a14eadfe2f7eb0ccefdddddfe0be11b0b4da5f5633fdb1ac525a4e'
related:
  - "[[2026-09-08-incremental-publication-cost-adr]]"
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# `incremental-publication-cost` audit: `S60 canonical-proof audit verification`

## Scope

Reviewed the S60 implementation against the accepted publication-proof ADR and current
plan, with emphasis on atomic proof selection, open-receipt and revision fencing,
bounded backend and ledger reads, exact source and payload classification, strict
audit-verification authority, service-owned storage access, and the prohibition on
proof seeding, storage reconciliation, sidecar fallback, and publication-path widening.
The review covered the modified integrity, ledger, store, CLI, transport, route, and
focused test surfaces.

## Findings

### physical-point-identity | high | The audit can certify a point stored under the wrong backend id

`_classify_audit_page` in `src/vaultspec_rag/_index_integrity.py:645` derives the
logical point identity entirely from the payload and never reads the raw `id` returned
by `scroll_index_audit_content`. A backend row stored under any physical Qdrant id can
therefore copy an expected logical id and path into its payload and be counted as a
match. The supposedly exact fixture at
`src/vaultspec_rag/tests/test_index_integrity.py:716` demonstrates the gap: it assigns
the noncanonical value `physical:{point_id}` to every raw row id, while
`test_exact_backend_matches_one_atomic_canonical_snapshot` at
`src/vaultspec_rag/tests/test_index_integrity.py:779` still expects a consistent
verdict. Production writes derive the physical id through `_stable_id` at
`src/vaultspec_rag/store_catalog.py:839`, so ignoring that identity violates the ADR's
requirement to compare backend point identities with canonical evidence and permits a
false successful audit.

Re-review: partially addressed, still open. The scanner now delegates comparison to
the store-owned deterministic id function and correctly excludes mismatches from the
matched set, making them both incompatible and missing. However,
`scroll_index_audit_content` at `src/vaultspec_rag/store_catalog.py:445` converts every
raw Qdrant id to text before returning it, while `index_audit_point_id_matches` at
`src/vaultspec_rag/store_catalog.py:454` deliberately accepts only integer physical
ids. Thus every valid production point is rejected. The focused tests bypass the
composition error by returning integers directly from `_AuditStore` and calling the
matcher directly in the store test.

Final re-review: resolved. `scroll_index_audit_content` now preserves the raw
`record.id` at `src/vaultspec_rag/store_catalog.py:445`, and the store-owned matcher at
`src/vaultspec_rag/store_catalog.py:454` compares that integer directly with
`_stable_id(logical_id)`. A wrong, absent, textual, or otherwise noncanonical physical
id is excluded from membership matching and reported as both incompatible and missing.
The real-store composition case at
`src/vaultspec_rag/tests/test_index_integrity.py:963` exercises an actual
`VaultStore.upsert_code_chunks` through the raw scroll and exact auditor; it was proven
red with the stringifying adapter and green after raw-id preservation. Independent
re-review reran this composition case successfully.

### payload-schema-verification | high | Most malformed source payloads are accepted as compatible

`_audit_payload_identity` at `src/vaultspec_rag/_index_integrity.py:592` validates only
the logical id and path for code and vault rows, and adds only a content fingerprint for
document rows. It does not validate the remaining required fields or their types from
the canonical payload contracts at `src/vaultspec_rag/store_schema.py:146`,
`src/vaultspec_rag/store_schema.py:169`, and
`src/vaultspec_rag/store_schema.py:197`. Consequently a code point missing its content,
language, line bounds, domain, and locator fields can be reported consistent; the
minimal exact-match fixture already has that malformed shape. Equality between the
proof's payload-schema number and the current constant validates only the proof claim,
not the scanned backend payload. This leaves the explicit full audit unable to detect
the incompatible payload state it is intended to classify.

Re-review: resolved. The audit now derives required keys and field types directly from
the three canonical TypedDict payload contracts, recursively validates unions, lists,
dictionaries, and integer values without accepting booleans, and performs validation
before identity or proof matching. Unknown fields are intentionally ignored, preserving
additive payload compatibility. The focused cases exercise a missing code field, a
wrongly typed vault list, a boolean document ordinal, incomplete payload classification,
and document fingerprint disagreement. The validator adds no backend access or mutation.
The explicit additive-field case at
`src/vaultspec_rag/tests/test_index_integrity.py:856` reaches the same canonical
validator and remains compatible; independent re-review ran it together with the
real-store physical-id composition case and observed two passing tests. The final
reported module gates are 52 integrity, 72 store, 44 CLI, and 29 route tests, with
format, lint, type, and diff checks green.

No open findings. **Verdict: APPROVED.** The final implementation compares raw physical
point identity and complete current payload shape before proof membership, preserves
additive-field compatibility, and retains the previously approved atomic, bounded,
non-seeding service boundary.

## Recommendations

No blocking recommendation. Retain the store-owned physical-ID derivation, canonical
payload contracts, bounded page/candidate/path reads, and explicit non-seeding audit
authority as later proof consumers and backend-matrix tests land.
