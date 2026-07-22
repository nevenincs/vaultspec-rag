---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
step_id: 'S42'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Perform fresh service-safe release review and complete every gate

## Scope

- `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact 1820-test inventory`

## Description

- Re-read the accepted research, ADR, plan, complete audit history, S41 record, and
  audit template before inspecting the feature diff.
- Review the complete `origin/main...1fe7b99` implementation and independently recheck
  historical ownership, preview, skip, transaction, topology, scratch, attribution,
  service-isolation, timeout, and rendering boundaries.
- Collect the exact current selected inventory and execute the first deterministic
  segment to a terminal result before granting any test credit.
- Reproduce every candidate blocker through real temporary workspaces and CLI calls,
  recording exact provider, dependency, source, context, and filesystem-topology state.
- Stop the remaining release gates without waiver after five HIGH findings invalidate
  the release target.

## Outcome

Failed. Collection found 1,823 selected tests out of 2,177; the first deterministic
553-test segment passed with four deselected. Five independent HIGH findings remain:
a fresh MCP install silently selects no providers, uninstall crosses an MCP skip,
install preview leaks Core's ContextVar, preview follows unrelated filesystem links,
and uninstall reports success when owned dependency-extra reversal fails. No CRITICAL
finding was identified. Merge and publication remain blocked pending remediation and a
new full review.

## Notes

- The remaining 1,270 selected tests and every unstarted install, service, host, static,
  Vaultspec, build, wheel, and public-Core gate are uncredited and unwaived.
- Real probes used temporary workspaces, public production APIs, and subprocess CLIs;
  no mocks, fakes, stubs, patches, monkeypatches, skips, or xfails were introduced.
- No production or test file was modified during S42.
