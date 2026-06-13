---
name: cli-operability-needs-persona-tests
trigger: always_on
---

# CLI Operability Needs Persona Tests

## Rule

Always finish CLI operability changes with a manual persona test that exercises the real
command surface in human and JSON modes where both are user-facing.

## Why

The `2026-06-11-cli-service-operability-hardening-code-review-audit` found failures that
ordinary automated assertions did not expose: invalid remediation commands, stale
service status behavior, logs that filtered the wrong window, and jobs output that was
not actionable. The epic plan made manual persona testing a required phase because the
CLI is the product surface for operators and agents.

## How

- Good: after changing `server status`, run `uv run vaultspec-rag server status`, `uv run vaultspec-rag server status --json`, and the related recovery command as the named
  operator persona, then record observed confusion or acceptance in the wave note.
- Bad: mark a CLI surface complete because unit tests passed while never running the
  actual command the operator will type.
