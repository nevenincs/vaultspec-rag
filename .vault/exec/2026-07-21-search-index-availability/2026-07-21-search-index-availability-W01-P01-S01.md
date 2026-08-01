---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:201eaf26e924fb94a40565dd6257dfa19084e6d1958a737d9c330c474042becc'
step_id: 'S01'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Add the red real-service regression expecting structured HTTP 503 for an empty search during matching nonterminal index work and record the current HTTP 200 failure using Sol medium

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Description

- Generate 256 well-formed synthetic vault documents with seed 252.
- Submit one real clean vault reindex and poll its exact job until the indexer is running under the project lease.
- Issue an authenticated raw HTTP search whose production filter guarantees no matching document.
- Preserve the HTTP status and normalized response headers while asserting the complete structured-unavailable contract.
- Poll the same job through success and prove the identical empty search becomes an authoritative HTTP 200 response.
- Bound failure evidence from health, jobs, metrics, and the latest response while redacting the live service token.

## Outcome

The real-daemon regression now distinguishes an unavailable index from an authoritative
empty result. The pre-implementation graphics processing unit run reproduced the bug:
the matching search returned HTTP 200 with no rows and `empty.reason: index_missing`
while the exact rebuild job was still running, failing only at the expected HTTP 503
assertion.

## Notes

The recorded red run used the verified managed Qdrant 1.18.2 binary through the supported
environment override because the isolated service fixture could not discover the host
binary after replacing its status directory. Semantic discovery was unavailable with an
HTTP 500 response, so triage used targeted source search and full-file reads. Formatting,
lint, and strict BasedPyright checks passed.
