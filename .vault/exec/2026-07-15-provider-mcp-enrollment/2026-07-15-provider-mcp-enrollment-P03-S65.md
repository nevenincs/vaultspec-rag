---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
body_hash: 'sha256:87bd18a2bbd4936f751434ca3b76901dc62c98d2f467ef843fcc8fd47eb3ab42'
step_id: 'S65'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Repeat every platform-aware release gate from zero after real index auto-delegation coverage and stop on the first failure

## Scope

- Clean candidate commit `4b097c026bb6a475ce4a6f8207b469a3a6678fbd`.
- Locked Windows and exact-archive POSIX environments.
- Unique Windows and POSIX `M`, `P`, `J`, and `F` collection ledgers.
- Real search and index auto-delegation under both discovery modes.
- Complete S54 job and S56 bounded-model contracts.
- Stop-on-first-failure runtime and release sequence.

## Description

- Verify the clean candidate, exact 1,119-document corpus, complete diff, frozen
  dependencies, and scikit-learn wheel payload.
- Recollect both platform ledgers and execute the real POSIX FIFO test.
- Review and execute the S64 fresh-interpreter search and index probes.
- Start the exact 1,828-item Windows marker-selected segment with the 600-second
  model-worker deadline.
- Preserve the passing full-corpus S56 evidence.
- When the test-owned service for the S54 job misses its 90-second readiness
  deadline, stop.

## Outcome

Failed release readiness. Environment, corpus, collection, FIFO,
auto-delegation, and independent-review preflight gates passed. The Windows
marker-selected segment then stopped during setup for
`test_reindex_vault_records_finished_tool_job`. Its isolated service did not
become healthy on port `51949` within 90 seconds.

The service log showed active Hugging Face reranker metadata requests and model
initialization at the deadline. The failure occurred before the S54 job body
could exercise its 120-second completion poll.

The segment reported 18 passes, one setup error, 443 deselections, and eight
warnings in 300.67 seconds. It receives zero runtime credit. The promoted
Windows items and all later POSIX, static, package, provider, and host gates
were not started and receive no credit or waiver.

## Notes

- All four S56 intent-ranking assertions passed before the failure. Their shared
  real-GPU fixture ran for 192.906884 seconds and enforced the complete
  1,119-document corpus under the 600-second worker boundary.
- The failed fixture terminated its service. No listener remained on port
  `51949`, and no S65 intent worker, test service, or test-owned Qdrant process
  survived.
- The unrelated installed service remained on port `55108` with process
  identifier `84904`, the same start time, and the same command. Its status
  file was absent, so no byte-preservation claim is made.
- Remediation must bound real service model initialization honestly. Either
  prove that a complete warm cache starts without network access within the
  shorter limit, or align service readiness with the model-setup budget.
  Preserve retained output and forced cleanup on expiry.
- No production, test, dependency, or lock file changed during S65.
