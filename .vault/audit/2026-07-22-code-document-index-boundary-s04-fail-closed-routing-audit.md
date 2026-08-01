---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:d51d5b194617c1cfa43cf4d1348b6296c383fa763615c253b88f5425d0452eca'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

# `code-document-index-boundary` audit: `S04 fail-closed routing`

## Scope

Audit `W01.P01.S04` against the accepted fail-closed migration boundary. Review legacy,
unknown-target, and conflicting-owner paths for typed refusal, fallback suppression, stable
job classification, and CPU-only import safety.

## Findings

Status: **PASS**. No critical, high, medium, or low findings remain within S04 scope.

Missing or older schema versions and missing required ownership fields raise
`migration_required`. Unknown values, newer unsupported schemas, invalid extractor versions,
and duplicate patterns with different owners raise `admission_config_invalid`. These errors
escape non-strict loading and therefore cannot turn into an empty policy or expose paths to a
lower-priority/default admission rule.

The typed job-error prefix survives the existing text-classification boundary and carries
operator remediation. Explicit root routes reject the same-pattern ownership conflict.
Focused Ruff, Ty, and real legacy, unknown-target, and conflicting-rule probes pass.

## Recommendations

Proceed to `W01.P01.S05`. Compile explicit root routes, transform targets, ignores, source
profiles, and parser capability through one deterministic classifier.
