---
tags:
  - '#exec'
  - '#vault-result-evidence'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:b6b3c31b8424a8d8e62ecf9d5001cb66a4a5a779177b34892047589acbedbb3f'
related:
  - "[[2026-09-23-vault-result-evidence-plan]]"
---

# `vault-result-evidence` ledger

## Changes

- `S04` `A` `src/vaultspec_rag/_markdown_passages.py`
- `S04` `A` `src/vaultspec_rag/tests/test_markdown_passages.py`
- `S04` `verify:` `fence guard mutation (fence detection disabled) fails on the section equality, restored passes` -> `pass`
- `S03` `M` `src/vaultspec_rag/embeddings.py`
- `S03` `M` `src/vaultspec_rag/service.py`
- `S03` `M` `src/vaultspec_rag/search/_searcher.py`
- `S03` `M` `src/vaultspec_rag/tests/test_adr_regression.py`
- `S03` `M` `.vault/research/2026-09-23-vault-result-evidence-research.md`
- `S03` `M` `.vault/adr/2026-09-23-vault-result-evidence-adr.md`
- `S03` `verify:` `service vault search median rerank 1.089s->0.367s, total 1.140s->0.43s` -> `pass`
- `S01` `A` `src/vaultspec_rag/tests/quality/evidence_queries.toml`
- `S01` `verify:` `self-check: 36 gold spans present and unique at the frozen ref, offsets within 5 chars, 20 beyond 3000 chars` -> `pass`
- `S01` `by:` `vaultspec-standard-executor`
- `S02` `A` `src/vaultspec_rag/tests/integration/test_vault_evidence_gate.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/_frozen_corpus_evidence.py`
- `S02` `M` `src/vaultspec_rag/tests/quality/metrics.py`
- `S02` `A` `src/vaultspec_rag/tests/quality/evidence_baseline.json`
- `S02` `verify:` `ruff+basedpyright on gate files` -> `pass`
- `S05` `M` `src/vaultspec_rag/indexer/_vault_prep.py`
- `S05` `M` `src/vaultspec_rag/indexer/_chunking.py`
- `S05` `M` `src/vaultspec_rag/indexer/_chunk_worker.py`
- `S05` `M` `src/vaultspec_rag/indexer/_vault_checkpoint.py`
- `S05` `M` `src/vaultspec_rag/indexer/_index_schema.py`
- `S05` `M` `src/vaultspec_rag/_store_models.py`
- `S05` `M` `src/vaultspec_rag/store_schema.py`
- `S05` `M` `src/vaultspec_rag/store_catalog.py`
- `S05` `M` `src/vaultspec_rag/tests/test_store_schema_parity.py`
- `S05` `M` `src/vaultspec_rag/tests/test_vault_metadata_subset.py`
- `S05` `M` `src/vaultspec_rag/tests/test_vault_chunking_unit.py`
- `S05` `M` `src/vaultspec_rag/tests/test_vault_checkpoint.py`
- `S05` `verify:` `ruff+basedpyright on touched files` -> `pass`
- `S06` `M` `src/vaultspec_rag/search/_searcher.py`
- `S06` `M` `src/vaultspec_rag/search/_result_shaping.py`
- `S06` `M` `src/vaultspec_rag/search/_models.py`
- `S06` `M` `src/vaultspec_rag/tests/test_vault_chunking_unit.py`
- `S06` `M` `src/vaultspec_rag/tests/test_document_result_shaping.py`
- `S06` `M` `src/vaultspec_rag/tests/test_typesafe_search.py`
- `S06` `M` `src/vaultspec_rag/tests/integration/_frozen_corpus_evidence.py`
- `S06` `M` `src/vaultspec_rag/tests/integration/test_vault_evidence_gate.py`
- `S06` `M` `src/vaultspec_rag/tests/quality/evidence_baseline.json`
- `S06` `verify:` `unit and adapter tests (384) and resident GPU integration (30)` -> `pass`
- `S05` `M` `src/vaultspec_rag/cli/_status_labels.py`
- `S05` `M` `src/vaultspec_rag/tests/test_cli_service_status.py`
- `S05` `verify:` `live status on the pre-bump vault index names 'vaultspec-rag index --rebuild --type vault'` -> `pass`
- `S07` `M` `src/vaultspec_rag/server/_models.py`
- `S07` `M` `src/vaultspec_rag/server/_routes_search.py`
- `S07` `M` `src/vaultspec_rag/cli/_search.py`
- `S07` `M` `src/vaultspec_rag/cli/_render.py`
- `S07` `M` `src/vaultspec_rag/mcp/_tools.py`
- `S07` `M` `docs/automation.md`
- `S07` `M` `docs/indexing.md`
- `S07` `M` `docs/search-and-index.md`
- `S07` `M` `src/vaultspec_rag/tests/_cli_helpers.py`
- `S07` `M` `src/vaultspec_rag/tests/_search_readiness_scenarios.py`
- `S07` `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py`
- `S07` `M` `src/vaultspec_rag/tests/integration/_helpers.py`
- `S07` `M` `src/vaultspec_rag/tests/integration/test_service_metrics.py`
- `S07` `A` `src/vaultspec_rag/tests/integration/test_vault_search_adapter_parity.py`
- `S07` `verify:` `unit and adapter tests (384), resident GPU integration (30), project-wide ty + ruff` -> `pass`
- `S08` `M` `src/vaultspec_rag/indexer/_slicing.py`
- `S08` `M` `src/vaultspec_rag/indexer/_streaming.py`
- `S08` `M` `src/vaultspec_rag/indexer/_reuse.py`
- `S08` `M` `src/vaultspec_rag/tests/test_index_reuse.py`
- `S08` `verify:` `indexer unit tests (116), project-wide ty + ruff` -> `pass`
- `S09` `M` `src/vaultspec_rag/search/_result_shaping.py`
- `S09` `M` `src/vaultspec_rag/search/_searcher.py`
- `S09` `M` `src/vaultspec_rag/tests/test_document_result_shaping.py`
- `S09` `verify:` `vault search 10 results 18 runs median 0.712s vs target 0.570s` -> `fail`
- `S04` `M` `src/vaultspec_rag/_markdown_passages.py`
- `S04` `M` `src/vaultspec_rag/tests/test_markdown_passages.py`
- `S04` `verify:` `setext recognition disabled fails the underline test, restored passes` -> `pass`
- `S05` `M` `src/vaultspec_rag/tests/test_process_probe_source_structure.py`
- `S05` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S05` `verify:` `full no-accelerator lane: 5363 passed, 3 failed, all 3 failing identically at 799b4dc3 before this feature` -> `pass`
- `S06` `M` `src/vaultspec_rag/tests/test_search_unit.py`
- `S06` `verify:` `fallback removed lets the exhausted forward escape the search, restored passes` -> `pass`
- `S07` `M` `src/vaultspec_rag/tests/test_cli_search_safety.py`
- `S07` `M` `src/vaultspec_rag/tests/integration/test_vault_search_adapter_parity.py`
- `S07` `verify:` `snippet check removed renders an edited file's current line, restored renders the snippet` -> `pass`
- `S04` `verify:` `list-item and quote exclusion removed fails both cases, restored passes` -> `pass`
- `S09` `M` `src/vaultspec_rag/tests/test_search_unit.py`
- `S09` `verify:` `evidence, intent, testimonial, GPU integration (42) and CLI/MCP parity` -> `pass`
- `S10` `M` `src/vaultspec_rag/operator_state/_environment_probe.py`
- `S10` `M` `src/vaultspec_rag/operator_state/_hardware.py`
- `S10` `M` `src/vaultspec_rag/operator_state/_compute.py`
- `S10` `M` `src/vaultspec_rag/api.py`
- `S10` `M` `src/vaultspec_rag/cli/_jobs_tui_header.py`
- `S10` `M` `src/vaultspec_rag/cli/_jobs_tui_constants.py`
- `S10` `M` `src/vaultspec_rag/cli/_status.py`
- `S10` `M` `src/vaultspec_rag/serviceclient/_typed_state.py`
- `S10` `M` `src/vaultspec_rag/tests/test_environment_probe.py`
- `S10` `M` `src/vaultspec_rag/tests/test_health_degraded_clears.py`
- `S10` `verify:` `degraded-verdict guard mutation (supersession check removed fails both no-JOB_FAILED assertions; restored passes)` -> `pass`
- `S11` `M` `src/vaultspec_rag/server/_lifespan.py`
- `S11` `M` `src/vaultspec_rag/cli/_status_labels.py`
- `S11` `M` `src/vaultspec_rag/tests/test_cli_service_status.py`
- `S11` `M` `src/vaultspec_rag/tests/test_health_degraded_clears.py`
- `S11` `M` `src/vaultspec_rag/tests/integration/test_service_jobs_resilience.py`
- `S11` `verify:` `service-level rebuild remedy mutation (remedy removed fails the next-action assertion; restored passes)` -> `pass`

## Notes

- `S03` research and ADR speedup figure corrected from the scratch 6.6x to the in-service ~3x; the decision is unchanged
- `S06` test_typesafe_search fixture grown past the 1,200-character passage bound so its snippet-shorter-than-content premise still holds; the assertion is unchanged
- `S05` correction after close: a refused index job's status finding named the job log, not the rebuild the refusal asks for
- `S07` mcp/_tools.py also carries a one-line fix to a pre-existing unnecessary isinstance the type checker flagged; the CLI stub service stopped sending rerank_text, which the real service never sends
- `S08` per the ADR's gate condition the section path does not enter the embedding input; the input stays title plus text, byte-identical to before, and only the single builder and full-input donor verification ship. The concurrency ADR's D8 is amended with this evidence at plan close
- `S09` latency target missed: fp32 baseline 1.140s, final median 0.712s (rerank 0.403s, passage 0.222s). Passage scoring costs about 2.8ms per pair, not the 1-2ms the research estimated; the 48-pair page budget cut it from 0.33s with no measured quality loss. Reaching 0.57s needs a ranking-affecting change to the chunk rerank; raised to the user
- `S04` review correction: sentence and word splitters collapsed into one pattern-taking splitter; setext headings recognised; thematic breaks separate blocks and small passages merge only across whitespace
- `S05` review correction: the indexed-metadata builder's dict shape matches an unrelated serializer and is registered as serialisation, not shared behaviour; the checkpoint test's schema-constant substitution is declared with its reason
- `S06` review correction: passage scoring that runs out of accelerator memory now leaves each result its first passage instead of failing a ranked page
- `S07` review correction: the human view shows a file's lines only while they still hold the snippet; docs keep code hits' line fields; parity test asserts passages never reach the wire
- `S04` plan-close review correction: an underline under a list item or block quote is a thematic break, not a setext heading
- `S09` plan-close review corrections: passage_pairs no longer mutates results (first passages are shown by the selector); the OOM arm binds the accelerator before the try and catches BaseException like the predict loop
