---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-W02-P05-S13]]"
---

# `service-job-control` audit: `s13 code pipeline control`

## Scope

Audited cooperative run control in `CodebaseIndexer`, including scan and hash
producers, serial and spawn-based process-pool chunking, bounded queue
backpressure, the single GPU consumer, shutdown, exception precedence, and the
temporary S13/S14 boundary around destructive replacement spans.

## Findings

### exceptional-pipeline-cleanup | critical | Control could escape while the consumer remained live

The initial implementation joined the consumer in a `finally` block but only
evaluated the bounded shutdown result after a normal producer return. A
producer-side pause or cancel could therefore mask a timed-out consumer and let
orchestration acknowledge control while GPU or store work remained live.
Resolved by capturing producer `BaseException`, always completing bounded
consumer shutdown, and making a live-consumer failure the highest-priority
outcome with the producer signal preserved as its cause.

### consumer-failure-masking | high | Racing control could hide a real consumer failure

The initial producer checkpoints could raise while the consumer had already
recorded an encode or store exception. Resolved by evaluating cleanup on every
path and raising a recorded non-control consumer failure before producer or
consumer control signals.

### broken-pool-failure-masking | high | Consumer control could hide a fatal progressed pool failure

The first remediation still evaluated consumer control before a
`BrokenProcessPool` that occurred after files or chunks had been published.
Resolved by making progressed pool failure outrank control while retaining
control ahead of the safe zero-progress serial fallback.

Final independent review passed with zero Critical and zero High findings.
Backward-compatible no-op defaults, 100 ms bounded polling, pending-future
cancellation, child-process joins, single-consumer ownership, CPU-only spawned
workers, and encode-only GPU locking all passed review.

## Recommendations

No S13 follow-up remains. S14 should replace the temporary inert-control
deferral around destructive clean and replacement paths with explicit
`RunControl.protected()` spans, as assigned by the approved plan.
