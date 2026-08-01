---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:25be1f96b74763bf6000f3108d89d65e87a0566bcadda5a6f5031ca46fcc439f'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` audit: `s31 cli job control verification`

## Scope

Audited `W04.P14.S31`: real-server human and JSON command coverage, prefix
resolution, exact identifiers, idempotency, stable failures, retry, deletion,
force rejection, isolation, and prohibited-test-double compliance.

## Findings

### s31-cli-job-control-verification | medium | retry lineage was described but not asserted

Resolved. The human CLI scenario now inspects the real manager after retry and
proves exactly one new attempt links to the cancelled parent under a different
job identifier.

Review status: pass.

The assertions cover exit status, exact identifiers, resource states,
structured outcome and error codes, retry lineage, and deletion visibility
through production HTTP behavior.

## Recommendations

Accept S31 and retain these scenarios as the singular CLI control contract.
