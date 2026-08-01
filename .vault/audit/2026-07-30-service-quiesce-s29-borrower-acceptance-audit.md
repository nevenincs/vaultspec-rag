---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:2dbb3c6bd1b7f70cf5d17b8274826f5a92890c533fbe164cb7720f2a2c5e6452'
related:
  - "[[2026-07-24-service-quiesce-adr]]"
  - "[[2026-07-24-service-quiesce-plan]]"
---

# `service-quiesce` audit: `S29 borrower capability architectural acceptance`

## Scope

Architectural acceptance review of S29 commit `cb37d33d` against the accepted borrower-capability contract. The review covered capability secrecy and lease lifetime, separation from the service identity lock, pause binding and matching resume, heartbeat loss recovery, lifecycle-envelope failures, unchanged public quiesce projection, and CPU-only evidence. The focused real-process route suite passed four tests without a daemon lifespan, Qdrant, model, or GPU allocation.

## Findings

### unavailable-lease-verification | high | Heartbeat treats an unavailable lock mechanism as proof the borrower died

`borrower_lease_status` converts an `claim_anchor` fault into `NOT_HELD`. `resume_lost_borrower_lease` treats that same result as proof that the bound lease was released and rebuilds GPU residency. A transient anchor open or lock failure can therefore resume the service while the borrower may still retain the OS lock, violating the fail-closed borrower boundary. The route preflight also reports the condition as ordinary absence rather than an unavailable coordination mechanism. The focused suite proves contention, crash release, matching capabilities, and recovery after real release, but contains no real unavailable-anchor case.

## Recommendations

- For `unavailable-lease-verification`, preserve an unavailable verification result separately from `NOT_HELD`. Borrower pause and post-pause binding must fail closed with the canonical lifecycle envelope, and heartbeat recovery must leave the bound quiescence closed when verification is unavailable. Add a real filesystem permission or unsupported-lock proof that the recovery path does not resume under that condition. The implementation must choose and document whether this condition reuses an existing stable borrower error or introduces a separately named stable error before S29 can be accepted.
