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

Scoped read-only acceptance review of the uncommitted S29-S32 GPU pytest borrower path against the accepted service-quiesce ADR and repair plan. The review inspected source and ran focused CPU-only tests; no live GPU, resident daemon, Qdrant child, or service lifecycle was started.

## Findings

### captured-borrower-anchor | high | Isolated pytest lease cannot satisfy the captured resident service

`pytest_configure` redirects Qdrant storage before the coordinator acquires its borrower lease. The current `run_with_borrowed_gpu(target=...)` still derives that lease from redirected configuration, while the captured resident service verifies the sibling borrower anchor beside its original identity lock. Pause therefore rejects the capability as not held, even though the target identity and bearer checks succeed. The target must carry the absolute original sibling anchor, S29 must provide the narrow captured-anchor acquisition path, and S30 must use that returned lease before revalidation and pause. S32 remains blocked until the cross-namespace path is proven with a CPU-only route harness.

### captured-initial-bearer | high | Status-file-first transport leaks the borrower capability to an unauthenticated first request

The captured target correctly keeps only a token digest after pytest redirects status paths. The ordinary admin transport therefore finds no local status token and sends the pause body before its 401 health refresh. That body contains the borrower capability, violating the accepted first-request authentication rule. S30 needs the minimal explicit typed initial-bearer and pinned-refresh transport option; it must not restore the host status environment, inject raw headers, or open a parallel HTTP path.

### arbitrary-captured-anchor | critical | Public raw-path helper bypasses pytest containment

`acquire_gpu_borrow_lease_for_service` currently accepts arbitrary absolute identity and sibling borrower paths and suppresses effect-target containment whenever pytest is active. Its shape check does not bind either path to a target captured before root registration, so any test can lock a caller-selected host sibling. This is the exact general-path escape hatch prohibited by the ADR. Replace it with a one-shot opaque authority minted only after S30 validates the pre-registration machine-pointer target; S29 alone retains the actual sibling path.

### same-token-401-retry | medium | Strict revalidation suppresses the required authenticated retry

The captured transport invokes its refresh callback after a 401 but retries only if the callback returns a different token. Strict revalidation requires the captured token digest to remain unchanged, so the valid token is normally the same string and no retry occurs. Token rotation must remain a target-change refusal; the repair is one same-token authenticated retry after successful pinned revalidation, with no status-file fallback.

## Recommendations

- Do not accept or commit S29, S30, or S32 until the recorded opaque-authority and same-token retry repairs are implemented and focused CPU tests prove mint timing, one-shot consumption, forged and stale authority refusal, exact release, first-request authentication, 401 same-token retry, token-rotation refusal, and the redirected-path pause-work-resume topology.
- Retain root pytest singleton-path isolation. The opaque authority registry is the sole narrow exception and must not be implemented by restoring global environment or by accepting arbitrary caller paths.
- Keep the captured target non-secret. Revalidation may hold the raw service token only in its local call stack and pass it directly to typed transport parameters without serialization or logging.
