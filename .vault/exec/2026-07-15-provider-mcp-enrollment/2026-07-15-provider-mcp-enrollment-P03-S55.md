---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
step_id: 'S55'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Repeat every platform-aware release gate from zero, verify S54 deadline behavior, and stop on the first red gate

## Scope

- `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md; no carried credit; Windows 2,269 total, 1,832 selected, 437 excluded; POSIX 2,270 total, 1,833 selected, 437 excluded with actual FIFO execution; full selected tests; static, type, complexity, and diff gates; wheel, sdist, and public Core 0.1.45 smoke; fresh isolated installed-package Claude and Codex configs, idempotence, and selective uninstall`

## Description

- Rebuild the exact Windows and POSIX test-item ledgers without carried credit.
- Execute the POSIX-only FIFO selector against an actual FIFO from an exact-commit
  Linux archive using public Core 0.1.45.
- Re-review the complete branch and S54's bounded real-job completion helper.
- Start the complete Windows marker-selected segment with stop-on-first-red behavior.
- Preserve external model-metadata timing and retry evidence when session-fixture setup
  exceeds the declared test timeout.
- Stop every later release gate and record zero credit after the decisive failure.

## Outcome

Failed release readiness. The exact Windows and POSIX inventories were reproduced, the
real POSIX FIFO selector passed, and review found no unresolved S54 source issue. The
Windows selected segment never reached its first assertion: Hugging Face returned 504
for every observed Qwen metadata request while the session-scoped real embedding model
loaded. SentenceTransformers exhausted seven legacy configuration retry sequences and
continued into adapter metadata retries. Because pytest is configured with
`timeout_func_only = true`, the 300-second timeout did not cover fixture setup.

## Notes

- The process started at 09:55:00. Its final retained 504 response was at 10:24:17,
  exactly 1,757 seconds later; it was still in fixture setup with no stderr or terminal
  pytest summary when the two audit-started pytest processes were terminated.
- The incomplete Windows aggregate receives no selected-test credit.
- The POSIX FIFO selector passed one of one in 0.06 seconds against a real
  `os.mkfifo` node; it does not waive the Windows failure.
- Promoted-overlap, static, packaging, public-Core smoke, installed-package, and real
  Claude and Codex recognition gates were not run and are not waived.
- No production or test file changed during this audit step.
