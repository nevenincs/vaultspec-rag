---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
  - "[[2026-07-22-code-document-index-boundary-w03-p05-preprocess-fidelity-audit]]"
---

# `code-document-index-boundary` audit: `W03 P05 Remediation Code Review`

## Scope

Review the W03.P05 remediation against the five findings in the preceding fidelity
audit: admission-time JSON normalization, emitted-cap cache semantics, real extractor
verification, structured CLI policy outcomes, and test integrity. The review covered
the config loader, cache identity, every cache-hit worker path, preprocess CLI, and the
focused unit and integration changes.

## Findings

Status: **PASS**. No critical, high, medium, or low findings remain in the remediation
scope.

TOML temporal scalars now become canonical ISO strings at admission and non-finite
floats are rejected before worker construction. The execution fingerprint includes the
effective emitted-byte cap, while all single and batch cache-hit paths revalidate cached
output against the active cap. List, check, run-one, and status now preserve stable
migration and admission failure kinds without exposing tracebacks or emitting empty JSON.

The new checks use real files, real extractor subprocesses, real cache reads and writes,
and real CLI subprocesses; they add no fake, mock, stub, patch, monkeypatch, skip, or
xfail. They verify canonical option delivery, configured extractor-version invalidation,
source-redirection refusal, bounded metadata retention, path-dependent cache isolation,
cap invalidation, and both stable CLI policy outcomes.

Focused Ruff and Ty checks pass. Ninety-nine preprocess schema, config, runner, cache,
entry-point, and CLI tests pass; seven focused remediation checks pass; and the integration
module collects fourteen tests. The forbidden downstream-identifier sweep is clean.

## Recommendations

Close S32, S33, S36, and S106 after the worker-side companion commit is present. Keep
policy options within the canonical JSON domain and treat every new semantics-bearing
execution limit as both a cache-identity input and a cache-read validation rule.
