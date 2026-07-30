---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
related:
  - "[[2026-07-24-service-quiesce-adr]]"
---
# `service-quiesce` audit: `S32 GPU pytest borrower integration`

## Scope

Scoped read-only acceptance review of the uncommitted S32 root pytest coordinator against the accepted service-quiesce ADR and its S29-S32 repair plan. No live GPU, resident daemon, Qdrant child, or service lifecycle was started.

## Findings

### captured-borrower-anchor | high | Isolated pytest lease cannot satisfy the captured resident service

`pytest_configure` redirects Qdrant storage before the coordinator acquires its borrower lease. The current `run_with_borrowed_gpu(target=...)` still derives that lease from redirected configuration, while the captured resident service verifies the sibling borrower anchor beside its original identity lock. Pause therefore rejects the capability as not held, even though the target identity and bearer checks succeed. The target must carry the absolute original sibling anchor, S29 must provide the narrow captured-anchor acquisition path, and S30 must use that returned lease before revalidation and pause. S32 remains blocked until the cross-namespace path is proven with a CPU-only route harness.

## Recommendations

- Do not accept or commit S32 until the recorded S29-S30 anchor repair is implemented and its focused CPU tests prove pause, resume, release, contention, and target-path mismatch behavior.
- Retain root pytest singleton-path isolation. The captured anchor is the sole narrow exception and must not be implemented by restoring global environment or by accepting arbitrary caller paths.
