---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` audit: `s37 architecture safety`

## Scope

Audited the completed service job-control implementation for ADR conformance,
truthful control acknowledgement, bounded operator views, GPU ownership,
storage safety, shutdown ordering, MCP compatibility scope, and test integrity.

## Findings

### stale-code-discovery | high | resolved per-attempt authority

Code job bindings retained admission-time discovery across queued, paused, and
resumed attempts. Bindings now discard admission discovery and each runnable
attempt validates and discovers current content behind control checkpoints. A
real regression mutates the corpus after paused admission and proves convergence
after resume.

### eager-paused-restore | medium | resolved inert startup binding

Startup restoration validated every restored code root, including paused work.
Restoration now binds durable jobs without scanning and dispatches only queued
jobs whose desired state is running, so paused intent remains inert.

### final-conformance | low | no open findings

Independent re-review confirmed the corrections and found no remaining issues
across acknowledgement truthfulness, bounded views, GPU and storage ownership,
shutdown ordering, MCP scope, or test integrity.

## Recommendations

Accept S37. Preserve the separation between admission validation and fresh
execution authority, and keep restored paused jobs free of model loading,
filesystem discovery, and storage mutation.
