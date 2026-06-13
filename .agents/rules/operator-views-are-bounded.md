---
name: operator-views-are-bounded
trigger: always_on
---

# Operator Views Are Bounded

## Rule

Always make operator list and tail commands bounded, filterable, and biased toward the
current actionable state rather than unbounded history.

## Why

The `2026-06-11-cli-service-operability-hardening-code-review-audit` and
`2026-06-11-service-jobs-operability-adr` showed that full history tables and unfiltered
log tails hide running or relevant work behind stale noise. Operators need answers to
what is running, failed, stale, or related to a specific job without dumping the whole
service history.

## How

- Good: default `server jobs` to a bounded result set, expose `--running`, `--failed`,
  `--job-id`, and `--since`, and make `server logs --job-id` search a bounded maximum
  log window before returning the requested filtered tail.
- Bad: render every recorded job by default or filter only the last N unfiltered log
  lines so unrelated recent noise can hide the requested job.
