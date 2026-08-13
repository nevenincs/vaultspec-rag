---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:0eda67a4f7e9d40e45829a7ffc0f2742815d56262bd9313702ef7662e4634633'
step_id: 'S77'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Make a refused quiesce transition name that admission is closed, and give the pause drain a budget longer than one encode slice

## Scope

- `src/vaultspec_rag/server/_routes.py`
- `src/vaultspec_rag/tests/test_service_quiesce_routes.py`

## Description

- Audited the four lifecycle verbs against the running service rather than waiting for a symptom to be reported: start on an already-running service, pause, pause again, resume, resume again.
- Found a pause that refused twice and left the service holding admission closed, with the drain completing on its own about two minutes after the caller had given up.
- Confirmed the consequence directly - a search against the service came back refused with the admission-closed code while the reported status still read as a timed-out pause.
- Made the refusal name that admission is closed and both ways out, and repaired the sentence, which read "left the service is 'pausing'".
- Traced the cause to a five-second drain budget in the route, shorter than one encode slice under load, and raised it to fit between a slice and the caller's admin budget.
- Confirmed the idempotent lifecycle contracts are already covered and green rather than stopping the operator's service to retest them.

## Outcome

Pause, resume, and start on an already-running service all behave to the service-surface contract: one envelope per exit path, an already-satisfied request exiting zero with an already-done status, and a non-zero exit when the requested state is not reached. Resume recovers a service that a failed pause left held, and reports it as an aborted pause.

Three guards added, each proven to fail on its own assertion: the refusal naming the closed admission and both remedies, the refusal staying silent when the service is still serving, and the drain budget held between one slice and the caller's timeout. Eighty-six quiesce and route tests pass.

## Notes

The two faults compounded, which is why neither had been reported as a defect. The short budget made a refused pause the normal outcome on a busy service, and the message made that outcome unreadable: it named the transition that failed and said the failure was retryable, both true, while omitting that the service had stopped answering. An operator following it would have waited rather than retried, and the service would have served nothing for as long as they waited.

The half-state is recoverable and always was - retrying pause completes it once the work drains, and resume releases it - so this is a legibility and sizing fault rather than a wedge. That distinction is why the fix is a budget and a sentence rather than a change to which side owns the transition.

The running service carries the installed build, not this working tree, so the improved message reaches it at the next install. The behaviour was verified against the controller and route directly.
