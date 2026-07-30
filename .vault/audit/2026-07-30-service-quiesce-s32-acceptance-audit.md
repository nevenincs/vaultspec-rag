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

Scoped read-only acceptance review of the uncommitted S32 root pytest coordinator and its S29-S30 dependencies against the accepted service-quiesce ADR and repair plan. No live GPU, resident daemon, Qdrant child, or service lifecycle was started.

## Findings

### captured-borrower-anchor | high | Isolated pytest lease cannot satisfy the captured resident service

`pytest_configure` redirects Qdrant storage before the coordinator acquires its borrower lease. The current `run_with_borrowed_gpu(target=...)` still derives that lease from redirected configuration, while the captured resident service verifies the sibling borrower anchor beside its original identity lock. Pause therefore rejects the capability as not held, even though the target identity and bearer checks succeed. The target must carry the absolute original sibling anchor, S29 must provide the narrow captured-anchor acquisition path, and S30 must use that returned lease before revalidation and pause. S32 remains blocked until the cross-namespace path is proven with a CPU-only route harness.

### captured-initial-bearer | high | Status-file-first transport leaks the borrower capability to an unauthenticated first request

The captured target correctly keeps only a token digest after pytest redirects status paths. The ordinary admin transport therefore finds no local status token and sends the pause body before its 401 health refresh. That body contains the borrower capability, violating the accepted first-request authentication rule. S30 needs the minimal explicit typed initial-bearer and pinned-refresh transport option; it must not restore the host status environment, inject raw headers, or open a parallel HTTP path.

## Recommendations

- Do not accept or commit S32 until the recorded S29-S30 anchor and initial-bearer repairs are implemented and their focused CPU tests prove pause, resume, release, contention, target-path mismatch, and authenticated first-request behavior.
- Retain root pytest singleton-path isolation. The captured anchor is the sole narrow exception and must not be implemented by restoring global environment or by accepting arbitrary caller paths.
- Keep the captured target non-secret. Revalidation may hold the raw service token only in its local call stack and pass it directly to the typed transport parameters without serialization or logging.
