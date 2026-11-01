---
tags:
  - '#reference'
  - '#stale-search-hits'
date: '2026-10-26'
modified: '2026-10-26'
body_schema: 'body-v2'
body_hash: 'sha256:67bceaad8e063c6255a9d5eadc07a6656caf152331f7e4e4a753a5b58cbc9164'
related:
  - "[[2026-09-08-search-readiness-contract-reference]]"
---

# `stale-search-hits` reference: `delivered-hit verification and repair seams`

Inspection baseline: commit `2873f8b185c84b3494ee48f141ac56a86b8de9fd`, 2026-10-26. Semantic discovery was unavailable because service startup was blocked by the existing GPU owner; targeted local discovery was used. This is a baseline inventory, not a claim that the proposed behavior has shipped.

## Summary

- Canonical ranked hits are `SearchResult` and `DocumentSearchResult` in `src/vaultspec_rag/search/_models.py:66`. Full candidate content is private `rerank_text`; display snippets and vault passage spans are separate. Verification must run after final reranking and filtering, preserving those values and order.
- The shared searcher owns direct and service retrieval. `src/vaultspec_rag/search/_searcher.py:1090` demonstrates document mapping, reranking, optional classifier ranking and final truncation; code and vault encoded searches have their own finalization points in the same module. Combined search must verify only its final delivered page, with deduplicated file reads.
- `src/vaultspec_rag/_publication_state.py:56` owns the publication snapshot and post-read token validation. Acquisition at `src/vaultspec_rag/_publication_state.py:94` scopes proof to canonical root, backend, source, storage and payload schema. Missing proof and proven incompatible proof are distinct conditions; races cannot become confirmed stale evidence.
- `src/vaultspec_rag/indexer/_run_ledger_publication_reads.py:139` owns bounded path lookup of canonical publication evidence. Query only delivered paths under the existing snapshot; avoid enumerating the manifest or materializing point identities merely to compare a file hash. The in-flight implementation adds `publication_content_for_paths` here as an identity-only bounded read, which avoids the older evidence API's point lists.
- `src/vaultspec_rag/indexer/_vault_fingerprint.py:86` defines the current `v2|raw|body|metadata` identity. Its parser at line 93 extracts the raw digest, and `fingerprint_bytes` at line 104 hashes original bytes with BLAKE2b. Code and document identities use raw content hashes. Vault must reuse `classify`: a raw-byte change can leave both body and indexed metadata unchanged, and a non-indexed modified stamp must not produce stale evidence.
- `src/vaultspec_rag/_index_integrity.py:794` owns exhaustive proof/backend audit, separate from cheap serve-time breadth checks. Its audit contracts inspect schema, identity and membership; disk content verification is a different input and must not confuse unreadable evidence with demonstrated corruption.
- `src/vaultspec_rag/_integrity_remediation.py:99` currently gates breadth-triggered repair on configuration, and its background admission at line 105 calls existing incremental job starters with integrity attribution. Legacy breadth observations remain separate from delivered-file drift evidence. The new drift coordinator must reuse canonical job admission rather than duplicate a JobManager or acquire full-index execution authority.
- `src/vaultspec_rag/server/_search_route_availability.py:211` projects integrity and repair job identity into search responses; `src/vaultspec_rag/server/_routes_search.py:600` holds the route's proof-fenced dispatch. Service-owned classification must supply the same diagnostics to CLI and MCP.

The existing readiness model answers publication availability and absence authority. Per-hit disk freshness answers whether a returned indexed file still agrees with the current file. Neither can substitute for the other. The inherited cross-surface inventory is `2026-09-08-search-readiness-contract-reference`.

## Implementation mapping

The in-flight implementation introduces `src/vaultspec_rag/_search_freshness.py` as the safe bounded file-evidence owner and `SearchDriftAuditor` in `src/vaultspec_rag/_search_drift.py` as the runtime-owned bounded queue and observation owner. The latter reuses the existing exact projection audit and ordinary incremental job starters. Existing admission gains an explicit runtime registry parameter so the HTTP request, admitted repair job and response projection share the same canonical JobManager and publication authority. These planned paths refine the baseline map above; they are not a second completeness registry.
