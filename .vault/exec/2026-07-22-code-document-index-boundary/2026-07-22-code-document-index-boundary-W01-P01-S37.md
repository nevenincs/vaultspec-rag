---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:207740202740e94c8d6c1d0356136efbd7d1cbd1594c01d74659e44ebf252505'
step_id: 'S37'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Define indexed, policy-rejected, retryable-extraction, terminal-extraction, decode-failed, and chunk-failed file states

## Scope

- `src/vaultspec_rag/indexer/_file_state.py`
- `src/vaultspec_rag/_job_errors.py`

## Description

- Define the closed indexed, policy-rejected, extraction, decode, and chunk states.
- Keep content hashes as evidence without treating failed work as convergence.
- Require every processing failure to retain its content kind, typed error, and detail.
- Mark only indexed and stable policy-rejected outcomes as converged.
- Expose stable reason and retry-obligation projections for service adapters.
- Add operator remediation for each processing-failure error kind.
- Validate every state, invariant, path form, error classification, and remediation.

## Outcome

Per-file outcomes can no longer certify a failed hash as successful metadata. Retryable and
terminal failures remain explicit, kind-owned, structured obligations while policy rejection
stays distinct from processing failure.

## Notes

No incidents or data loss. Worker result wiring and durable ledger persistence are scheduled
for later plan steps; S37 defines the stable state authority those paths will consume.
