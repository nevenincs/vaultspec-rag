---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
step_id: 'S53'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Repeat every release-review gate from zero and credit the POSIX-only FIFO item on Linux CI

## Scope

- `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md; Windows test items: 2,269 total, 1,832 selected, 437 excluded; POSIX test items: 2,270 total, 1,833 selected, 437 excluded`

## Description

- Confirm the corrected Windows and POSIX platform-aware collection arithmetic.
- Execute the real POSIX FIFO regression from an isolated Linux archive against public
  Core 0.1.45.
- Start the complete Windows marker-selected segment with no prior audit credit.
- Stop at the first selected failure and reproduce the red selector independently.
- Preserve service timing evidence and leave every later release gate uncredited.

## Outcome

Failed release readiness. The Windows and POSIX inventories match the corrected S53
mandate, and the real POSIX FIFO selector passes. The Windows selected segment is red:
both job-registry reindex completion tests failed in the aggregate, and the vault
selector independently observed a real job still running after its fixed five-second
polling window. The service completed successfully roughly 7.2 seconds after
submission, proving the selected test deadline is shorter than supported real behavior.

## Notes

- The incomplete aggregate receives no credit because it was stopped without a
  terminal pytest summary after the first selected failures.
- The independently reproduced selector failed one of one in 54.35 seconds; its
  fixture spent 44.37 seconds starting the real service and its call failed after
  5.64 seconds of polling.
- The POSIX FIFO selector passed one of one against an actual FIFO; it does not waive
  the red Windows campaign.
- Promoted overlap, static, packaging, public-Core smoke, and fresh host-recognition
  gates were not run and are not waived.
- No production or test file changed during this audit step.
