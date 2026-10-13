# Vault Markdown indexing

Markdown body/metadata preparation, incremental hashes, replacement and deletion reconciliation. Checkpoints and publication proofs connect vault work to served generations.

Read when: vault chunks/payloads; metadata refresh; missing documents; hashes.

## Modules

| Module                                                                                                          | Responsibility                                                                                                                                                                         | Evidence                                |
| --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| [src/vaultspec_rag/indexer/\_vault_checkpoint.py](../../../../src/vaultspec_rag/indexer/_vault_checkpoint.py)   | Opens compatible vault generations, maps chunks to units, filters confirmed resume work and supplies mutation lifecycles and proof evidence.                                           | [s1-0159](gpu-model-runtime-part-04.md) |
| [src/vaultspec_rag/indexer/\_vault_fingerprint.py](../../../../src/vaultspec_rag/indexer/_vault_fingerprint.py) | Hashes raw bytes, normalized parsed bodies and indexed metadata to classify unchanged, metadata-only or body work; unsupported identity fails toward body work.                        | [s1-0159](gpu-model-runtime-part-04.md) |
| [src/vaultspec_rag/indexer/\_vault_incremental.py](../../../../src/vaultspec_rag/indexer/_vault_incremental.py) | Scans or scopes vault changes, stat-gates hashes, checks prior proof/storage and reconciles body encodes, ordinal-matched payload refreshes and confirmed deletions.                   | [s1-0159](gpu-model-runtime-part-04.md) |
| [src/vaultspec_rag/indexer/\_vault_indexer.py](../../../../src/vaultspec_rag/indexer/_vault_indexer.py)         | Serializes full/incremental vault operations, recovers publication, streams replacements before barrier/stale cleanup and allows collection geometry recreation only on clean rebuild. | [s1-0160](vault-indexing-part-01.md)    |
| [src/vaultspec_rag/indexer/\_vault_prep.py](../../../../src/vaultspec_rag/indexer/_vault_prep.py)               | Defines IndexResult and markdown document/metadata/chunk preparation with line/section/passages, ordered CPU splitting and broken-pool serial fallback.                                | [s1-0160](vault-indexing-part-01.md)    |

## Selective evidence parts

Choose the part for the files or behavior you need; do not load every part.

- [s1-0125](vector-store-part-04.md): test_store_schema_drift.py, test_store_schema_parity.py, test_store_writes.py, test_streaming_segments.py, test_substitution_discipline.py, test_textual_timer_cancel.py.
- [s1-0128](publication-integrity-part-10.md): test_vault_chunking_unit.py, test_vault_fingerprint.py, test_vault_metadata_subset.py, test_vault_payload_batching.py, test_vault_progress_phases.py, test_vault_readiness_publication.py, test_vault_run_liveness.py, test_vault_split_parallel.py, test_verified_import.py, test_watcher_admission.py, test_watcher_controller.py.
- [s1-0147](service-lifecycle-part-22.md): test_store_integration.py, test_targeted_reindex_integration.py, test_teardown_budget.py, test_vault_chunking_integration.py, test_vault_evidence_gate.py, test_vault_payload_fields.py, test_vault_search_adapter_parity.py, test_vault_true_incremental.py, test_watcher_config.py, test_watcher_content_admission.py, test_watcher_control.py.
- [s1-0159](gpu-model-runtime-part-04.md): \_stat_gate.py, \_streaming.py, \_streaming_types.py, \_support_budget.py, \_vault_checkpoint.py, \_vault_fingerprint.py, \_vault_incremental.py.
- [s1-0160](vault-indexing-part-01.md): \_vault_indexer.py, \_vault_prep.py.

## Connections

- [Durable publication and index integrity](publication-integrity.md): Full/incremental vault operations use compatible checkpoints, confirmed replacements/deletes and publication proofs. Evidence: s1-0159 preparation/streaming; s1-0160 full/incremental vault operations.

## Limits and reconciliations

Findings describe the inspected snapshot. External dependency internals and operational outcomes were not verified. Test assertions and recorded benchmark results do not establish a current passing run.

- External vaultcore/parser behavior and actual incremental/rebuild outcomes remain unverified.
- Vault telemetry observes without the code/document admission ceilings; metadata-only and body replacement operations differ.
