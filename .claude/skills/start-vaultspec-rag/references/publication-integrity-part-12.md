# Durable publication and index integrity: evidence group s1-0163

Read this part when working with: [src/vaultspec_rag/tests/test_document_index_escalation.py](../../../../src/vaultspec_rag/tests/test_document_index_escalation.py).

This is static evidence. Implementation observations, documentation claims, and test expectations remain distinct; no tests were run. An imported dependency uninspected within this evidence group may be covered in another capability reference. All listed full-file ranges are covered; report-local dependency boundaries are not inventory gaps.

[Durable publication and index integrity](publication-integrity.md) provides module summaries, connections, and reconciled limitations.

## Capability summary

- This is a unit-test module for document-index audit refusal when publication evidence is absent, incompatible, or corrupt. Its opening comments state the intended failure scenario and audit boundary as documentation claims, not verified implementation behavior (lines 1-20).
- Test helpers construct the audit call and controlled SQLite ledger state. `_audit_without_storage` passes a callback that fails if storage is opened (lines 83-92); `_assert_document_rebuild_required` checks the top-level and document-domain refusal shape and a `--rebuild` remediation (lines 95-111).
- `_seed_document_proof` creates a full-run ledger generation and directly inserts a verified publication proof; `_insert_open_receipt` inserts a reserved receipt for corruption cases (lines 113-232). `_raw_ledger_connection` scopes raw SQLite connections and `_fingerprint` creates deterministic test identities (lines 69-81, 234-235).
- The module defines eight test functions, one parameterized over two incompatible-proof cases: missing ledger, missing proof, old ledger schema, receipt-index schema drift, proof collection/storage-schema incompatibility, proof ancestry incompatibility, corrupt open receipt, and malformed open receipt (lines 238-400). These are test expectations; the source alone does not establish that they pass.

## Interfaces and data flow

- The tested audit interface is `audit_index_sources(root_dir, PublicSourceType.DOCUMENT, RunAuthority.AUDIT_VERIFICATION, forbidden_store)`; the callback raises a pytest failure if invoked (lines 83-92). Tests expect a dictionary with `ok=False`, `partial=False`, top-level `status="rebuild_required"`, a failing document domain, a case-specific `error_kind`, and one remediation string containing `--rebuild` (lines 95-111).
- Test setup resolves the root, derives a ledger path, opens `RunLedger`, and in some cases uses raw SQLite transactions to seed or damage ledger tables and indexes (lines 65-81, 113-232, 267-307, 356-395). Assertions compare the SQLite contents before and after audit; the missing-ledger case compares the directory tree (lines 238-260, 267-307, 321-353, 356-400).
- Expected error kinds are `missing` for absent ledger/proof; `RunLedgerRebuildRequiredError` for an old schema or missing receipt index; `incompatible` for proof-key or generation-ancestry mismatch; and `corrupt_receipt` for mismatched or malformed open receipts (lines 246-400).

## Boundaries and dependencies

- Only the document audit path is represented. No successful audit, rebuild operation, backend read implementation, or other source type is exercised in this range (lines 83-111, 238-400).
- Import-derived, uninspected dependencies: [src/vaultspec_rag/\_index_integrity.py](../../../../src/vaultspec_rag/_index_integrity.py) (`audit_index_sources`); [src/vaultspec_rag/\_source_types.py](../../../../src/vaultspec_rag/_source_types.py) (`PublicSourceType`); [src/vaultspec_rag/store_schema.py](../../../../src/vaultspec_rag/store_schema.py) (collection/schema constants); [src/vaultspec_rag/\_store_writes.py](../../../../src/vaultspec_rag/_store_writes.py) (`workspace_volume_path`); [src/vaultspec_rag/indexer/\_index_schema.py](../../../../src/vaultspec_rag/indexer/_index_schema.py) (`DOCUMENT_EMBED_SCHEMA`); [src/vaultspec_rag/indexer/\_run_ledger_models.py](../../../../src/vaultspec_rag/indexer/_run_ledger_models.py) (ledger types/constants/path); [src/vaultspec_rag/indexer/\_run_ledger_runtime.py](../../../../src/vaultspec_rag/indexer/_run_ledger_runtime.py) (`RunLedger`); [src/vaultspec_rag/store_runtime.py](../../../../src/vaultspec_rag/store_runtime.py) (`configured_backend_identity`); and [src/vaultspec_rag/tests/\_sqlite_state.py](../../../../src/vaultspec_rag/tests/_sqlite_state.py) (SQLite comparison helpers). Their production behavior cannot be established from these imports.

## Evidence

- The docstring describes the intended failure mode: a sidecar may remain complete while its ledger parent is unavailable; audit should refuse before backend open and should not create, repair, or migrate proof. | [src/vaultspec_rag/tests/test_document_index_escalation.py:1-20](../../../../src/vaultspec_rag/tests/test_document_index_escalation.py#L1) | documentation claim
- Audit helper supplies document/audit-verification inputs and a forbidden-storage callback; output helper asserts the rebuild-required response shape. | [src/vaultspec_rag/tests/test_document_index_escalation.py:83-111](../../../../src/vaultspec_rag/tests/test_document_index_escalation.py#L83) | test expectation
- Ledger/proof setup uses a full-run signature and a verified publication proof; receipt helper inserts a reserved receipt with caller-selected parent revision. | [src/vaultspec_rag/tests/test_document_index_escalation.py:113-232](../../../../src/vaultspec_rag/tests/test_document_index_escalation.py#L113) | test setup
- Missing ledger and missing proof cases expect refusal without creating paths or changing/seeding the ledger. | [src/vaultspec_rag/tests/test_document_index_escalation.py:238-265](../../../../src/vaultspec_rag/tests/test_document_index_escalation.py#L238) | test expectation
- Old schema and missing receipt-index cases expect typed rebuild refusal while preserving prior SQLite contents. | [src/vaultspec_rag/tests/test_document_index_escalation.py:267-308](../../../../src/vaultspec_rag/tests/test_document_index_escalation.py#L267) | test expectation
- Collection, storage-schema, and proof-generation ancestry mismatches expect `incompatible` refusal before the storage callback and no ledger changes. | [src/vaultspec_rag/tests/test_document_index_escalation.py:310-354](../../../../src/vaultspec_rag/tests/test_document_index_escalation.py#L310) | test expectation
- Mismatched and malformed open receipts expect `corrupt_receipt` refusal with unchanged SQLite contents. | [src/vaultspec_rag/tests/test_document_index_escalation.py:356-400](../../../../src/vaultspec_rag/tests/test_document_index_escalation.py#L356) | test expectation
- The tests imply that audit refusal is intended to preserve durable state and avoid storage access for these evidence failures; this is inferred from the guards, not independently verified behavior. | [src/vaultspec_rag/tests/test_document_index_escalation.py:83-111,238-400](../../../../src/vaultspec_rag/tests/test_document_index_escalation.py#L83) | inference

## Uncertainty and follow-up

- To confirm actual audit behavior, inspect `audit_index_sources` and its ledger/proof validation path in [src/vaultspec_rag/\_index_integrity.py](../../../../src/vaultspec_rag/_index_integrity.py) and the relevant ledger/proof implementations under `src/vaultspec_rag/indexer/`; those files were outside this slice.
- To establish whether these expectations pass, the test module must be run; it was not run under this assignment.
