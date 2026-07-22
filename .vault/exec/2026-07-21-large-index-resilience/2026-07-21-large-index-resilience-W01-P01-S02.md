---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S02'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Define typed no-progress, memory-ceiling, circuit-open, and admission outcomes with shared remediation

## Scope

- `src/vaultspec_rag/_job_errors.py`

## Description

- Define one string-compatible typed vocabulary for legacy and resilience outcomes.
- Add a typed exception that preserves outcome identity through the existing text boundary.
- Recover exact canonical prefixes before applying backward-compatible free-text markers.
- Centralize actionable remediation for timeout, memory, circuit, profile, corpus, disk, and capacity outcomes.
- Keep the taxonomy import surface free of torch, Qdrant, service, and CLI dependencies.

## Outcome

Indexing policy and adapter work can now exchange stable typed safety outcomes without
breaking existing persisted text or string-based consumers. Every actionable refusal or
termination shares one service-domain remediation source.

## Notes

Production probes covered four legacy classifications and eight typed outcomes, remediation
parity, JSON serialization, and import lightness. Seven focused existing tests, Ruff, ty,
BasedPyright, formatting, and diff checks passed. Independent review returned PASS with no
findings.
