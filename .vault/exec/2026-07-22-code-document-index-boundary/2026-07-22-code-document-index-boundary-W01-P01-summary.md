---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `code-document-index-boundary` `W01.P01` summary

W01.P01 establishes typed, caller-configured content ownership and makes
invalid or unmigrated policy a mutation-free refusal at index and service-job
boundaries.

- Created: `src/vaultspec_rag/indexer/_content_policy.py`
- Created: `src/vaultspec_rag/indexer/_resolved_policy.py`
- Created: `src/vaultspec_rag/indexer/_file_state.py`
- Modified: `src/vaultspec_rag/config.py`
- Modified: `src/vaultspec_rag/_job_errors.py`
- Modified: `src/vaultspec_rag/indexer/_chunking.py`
- Modified: `src/vaultspec_rag/indexer/_ignore_specs.py`
- Modified: `src/vaultspec_rag/indexer/_preprocess_config.py`
- Modified: `src/vaultspec_rag/indexer/_config_epoch.py`
- Modified: `src/vaultspec_rag/indexer/_codebase_indexer.py`
- Modified: `src/vaultspec_rag/jobs.py`
- Created: `src/vaultspec_rag/tests/test_content_policy.py`
- Modified: `src/vaultspec_rag/tests/test_preprocess_config.py`
- Created: `src/vaultspec_rag/tests/integration/test_content_policy_fail_closed.py`

## Description

The phase separates parser capability from admission, defines ordered explicit
routes and versioned source profiles, requires preprocessing ownership and
extractor versions, and rejects conflicting or legacy policy without fallback.
One immutable snapshot carries normalized ignore, routing, preprocessing,
decoder, execution-mode, membership, and content identities through code
execution. Explicit per-file convergence states distinguish successful,
policy-rejected, retryable, terminal, decode-failed, and chunk-failed work.

Public code-index and job gates validate policy before mutation authority, and
real-resource tests preserve existing collection identifiers, metadata,
extraction cache, canonical jobs, and durable job state on refusal. The single
phase-boundary invocation completed with 50 passed tests in 2.77 seconds.
