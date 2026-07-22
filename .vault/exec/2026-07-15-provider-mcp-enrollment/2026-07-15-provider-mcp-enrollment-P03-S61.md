---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
step_id: 'S61'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Repeat every platform-aware release gate from zero after the verified environment repair and stop on the first failure

## Scope

- Clean audit commit `c9cf20697dd647096c2f070b51ff72d152031c7c`.
- Locked Windows environment and scikit-learn wheel payload.
- Unique Windows and POSIX `M`, `P`, `J`, and `F` collection ledgers.
- Complete 1,115-document audit-commit corpus.
- Windows 1,834-item campaign, followed only on success by the complete POSIX,
  static, package, provider, and host-recognition release sequence.

## Description

- Verify the clean tree, complete diff, locked dependencies, direct scikit-learn
  import, and package-local runtime hashes.
- Recollect both platform inventories and prove exact named-set cardinality,
  uniqueness, capability delta, and zero overlap.
- Inspect the S56 and S54 implementation and test surfaces independently.
- Start the exact 1,828-item Windows marker-selected segment with a 600-second
  model deadline.
- Stop the campaign at the first failed assertion and preserve its process,
  service, and test evidence.

## Outcome

Failed release readiness. Environment, corpus, collection, set-reconciliation,
and real FIFO preflight gates passed. The Windows marker-selected segment then
stopped at its first failure after 505 passes:
`TestAutoDelegation::test_search_auto_delegates_when_service_running` expected
the injected port `8766`, but automatic discovery selected the live
machine-global service on port `55108`.

The failed segment reported one failure, 505 passes, 443 deselections, and 284
warnings in 1,599.80 seconds. It receives zero runtime credit. The promoted
Windows items and every later POSIX, static, package, provider, and host gate
were not started and receive no credit or waiver.

## Notes

- The live service on port `55108` started before the S61 campaign and remained
  untouched. Its machine-global status was authoritative before the patched
  per-status-directory fallback used by the failing test.
- No S61 Python, Qdrant, listener, or graphics processing unit owner survived
  the failed campaign. The remaining empty console host was removed.
- The failure identifies a deterministic test-isolation gap, not a successful
  release result. Automatic-delegation coverage must isolate or explicitly
  control machine-global service resolution before the complete campaign is
  restarted from zero.
- No production, test, dependency, or lock file changed during S61.
- Pull request approval, merge, tag, publication, and release remain blocked.
