---
tags:
  - '#audit'
  - '#gpu-less-install-footprint'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v2'
body_hash: 'sha256:83bfda169b787dc0617bcdfc9da25b859757dc4a9638884f8d77df3e847f89cb'
related:
  - "[[2026-09-01-gpu-less-install-footprint-plan]]"
---

# `gpu-less-install-footprint` audit: `implementation-review`

## Scope

Reviewed the published metadata boundary, CUDA-only runtime gates, generated launcher specifications, installer remediation, documentation, and regression tests against the accepted ADR and implementation plan.

## Findings

### linux-resolver-output | medium | The published-wheel CUDA resolution assertion inspected the wrong output stream

`test_published_base_wheel_has_no_linux_cuda_resolution` captured both streams from `uv pip install --dry-run` but searched only standard output for `nvidia-`. uv writes resolver progress and the planned package set to standard error, so the assertion could not detect a future CUDA transitive dependency. The built-metadata assertion still caught the current direct torch, sentence-transformers, and transformers requirements, but it did not provide the required Linux resolver guard for indirect CUDA pulls.

### linux-resolver-output | resolved | The Linux resolver guard now scans complete command output

The assertion now evaluates the concatenated standard-output and standard-error text. Its failure proof inverted the CUDA assertion, and the focused test failed at that exact assertion before the guard was restored and passed.

## Recommendations

No follow-up recommendation remains.
