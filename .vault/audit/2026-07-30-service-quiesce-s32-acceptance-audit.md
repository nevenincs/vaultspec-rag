---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-31'
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

### unrecoverable-machine-holder | high | Production machine lock leaves a stale owner PID

A real nested route host acquired the production machine lock with PID 7172, but a separate contender observed its lock record still naming PID 43480 and therefore reported holder PID zero. The owner-record write is best-effort today, yet capture requires lock-holder, pointer, and health PID agreement. Do not synthesize a test PID or weaken that correlation: make the production machine-lock record update durable and fail acquisition when it cannot be established, then require a separate real contender to observe the exact positive owner PID before the CPU host signals ready.
### pre-root-original-path-observation | high | Guarded configured-path discovery discards valid host evidence during capture

The durable owner witness repair lets a real pre-ready contender recover the exact host PID, but the S30 child intentionally has pytest containment active with no registered root while it captures the original service. The ordinary configured-path holder reader correctly refuses that state; resolution reports `probe_failed` and loses the otherwise valid machine-pointer evidence. Do not weaken that reader or treat `BOOTSTRAP` as a general containment bypass. Capture needs one private original-path observation that requires existing absolute identity and discovery paths, opens without creation, makes only a momentary nonblocking lock attempt, shares ordinary pointer validation, and never retains a lease or writes the lock, discovery, capability, or authority. Any absence, unreadability, free lock, or PID disagreement must continue to refuse capture.
### raw-witness-mint | critical | Raw lock paths can mint a post-registration borrower authority

A mint API that accepts an absolute identity-lock path still lets any pre-root pytest caller select a host sibling anchor, even when acquisition later receives an opaque authority. That is the same containment escape in a later phase. S29 must mint `CapturedBorrowerLeaseAuthority` only from its registry-backed `CapturedMachineLockWitness`; S30 must retain a typed `PreIsolationMachinePointer` and pass it to typed post-lease revalidation. Neither minting nor revalidation may accept a raw path, and the shared pointer evaluator must remain the only pointer-validation rule.

## Recommendations

- Do not accept or commit S29, S30, or S32 until the recorded durable machine-owner record, opaque-authority, and same-token retry repairs are implemented and focused CPU tests prove real cross-process owner visibility, mint timing, one-shot/forged/stale refusal, exact release, first-request authentication, same-token 401 retry, token-rotation refusal, and the redirected-path pause-work-resume topology.
- Retain root pytest singleton-path isolation. The opaque authority registry, registry-backed machine-lock witness, and typed discovery revalidation are the sole narrow exceptions and must not be implemented by restoring global environment or by accepting arbitrary caller paths.
- Keep the captured target non-secret. Revalidation may hold the raw service token only in its local call stack and pass it directly to typed transport parameters without serialization or logging.
- Keep the normal configured-path machine-lock reader fully contained. Only S30's private, existing-original-path observation may run before root registration; it must neither create nor retain a lock and must share the strict pointer/PID validation that preserves holder_pid == pointer_pid == health_pid.
- Require every captured borrower mint and post-lease revalidation API to take only the typed witness or pointer evidence. `PreIsolationMachineLock` may project paths for frozen-target diagnostics, but S29 must reproject them from its registry on every revalidation; raw target paths are never authority-bearing inputs.
