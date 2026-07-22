---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
step_id: 'S59'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Repeat every platform-aware release gate from zero at the corrected unique-item ledger

## Scope

- `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md; no carried credit; Windows 2,271 total and unique, 1,834 campaign, 437 excluded; POSIX 2,259 total and unique, 1,835 campaign, 424 excluded; named zero-overlap M/P/J/F proof; complete S56 full-corpus, 600-second, cache, repair, offline, cleanup, and ranking contract; all runtime, static, package, public Core 0.1.45, fresh Claude and Codex, idempotence, selective unenrollment, and uninstall gates`

## Description

- Recollect unique Windows and POSIX displayed-node-ID sets at the clean audit commit.
- Reconcile `M`, `P`, `J`, and `F` by exact membership and cardinality.
- Recount the full audit-commit `.vault` corpus against the S56 implementation
  baseline.
- Start the complete Windows `M` runtime segment with a 600-second model deadline.
- Preserve the bounded worker context and installed-dependency failure evidence.
- Stop every later gate after the first selected setup error.

## Outcome

Failed release readiness. Both platform ledgers and the 1,113-document corpus
reconciled exactly. The Windows runtime segment then terminated with seven passes and
one setup error after 31.38 seconds. The bounded intent-ranking worker reached the full
corpus under `deadline=600.000s` but could not import scikit-learn because two
wheel-recorded package-local runtime DLLs were missing.

## Notes

- Scikit-learn 1.9.0's installed `RECORD` names `vcomp140.dll` and `msvcp140.dll`;
  neither file nor the containing `.libs` directory exists.
- `uv pip check` and `uv lock --check` both pass, so dependency metadata did not expose
  the missing wheel payload.
- No S59 intent-ranking worker remained after the error. The pre-existing client service
  was not modified or credited.
- The incomplete Windows segment and every later runtime, static, package, provider,
  and host-recognition gate receive no credit or waiver.
- No production or test file changed during this audit step.
