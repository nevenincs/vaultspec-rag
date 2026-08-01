---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:9d708f92552b7175870dd9e38bfe31d4fc15f9fc1088e60727fcdc7a5dfbc398'
step_id: 'S09'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Prove the shared service client preserves the structured unavailable error without manufacturing results using Sol medium

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Description

- Invoke the production shared HTTP search client for the matching-root guaranteed-empty query.
- Admit the client call through the five-party barrier after the exact running-job handshake.
- Assert the structured failure body, submitted job reference, and absence of a `results` member.

## Outcome

The shared service client now has a real-daemon regression proving that it preserves
`index_unavailable` as failure data. Automated consumers cannot receive a manufactured empty
result from this transport boundary.

## Notes

The assertion uses the production `_try_http_search` path without transport substitution.
Final local graphics processing unit acceptance passed with one selected test and seven
deselected.
