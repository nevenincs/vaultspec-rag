---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S01'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Add explicit queue, no-progress, retry-circuit, RSS, CUDA, and support-profile configuration with environment mappings

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Expose bounded store timeout and write-retry settings through unique environment mappings.
- Define chunk and byte limits for one file segment and the weighted producer queue.
- Add durable no-progress, watcher retry, jitter, and circuit-breaker policy settings.
- Add RSS, CUDA, allocator-headroom, and named support-profile settings.
- Validate numeric domains, normalized profiles, and queue/retry cross-field ordering.

## Outcome

The service configuration now provides one typed, environment-addressable contract for the
large-index safety policy. Defaults preserve current operation retry behavior while bounding
queue lifetime, workflow liveness, watcher retry, memory admission, and support-profile
selection for later production Steps.

## Notes

The final contract contains seventeen settings. Review confirmed the 120-second store timeout,
five attempts, 0.5/8-second write-retry ladder, and managed-service default preserve current
behavior; the default retry ladder fits within the 900-second no-progress deadline. All
environment coercion, bool and non-finite rejection, range boundaries, equality cases, JSON
exposure, and managed-log compatibility checks passed.

Independent review found no issues at any severity. Fifty-four existing configuration tests,
direct production probes, Ruff, formatting, ty, BasedPyright, import-light inspection, and
diff checks passed.
