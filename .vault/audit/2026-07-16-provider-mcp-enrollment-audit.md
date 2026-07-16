---
tags:
  - '#audit'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# `provider-mcp-enrollment` audit: `S51 correction review`

## Scope

Review the S51 correction for structured project-surface diagnostics, fail-before-
mutation topology safety, Core 0.1.45 filesystem compatibility, real-test integrity,
and the bounded verification claims needed before the independent S52 release audit.

## Findings

### project-surface-probe | high | Raw diagnostic read could block or skip unsafe nodes

The first review found that `Path.exists()` followed by unrestricted `read_text()`
could block on a POSIX FIFO after topology preflight had already refused it. A broken
relative project symlink returned false from `exists()` and therefore retained the S50
report truncation. The correction now classifies with non-following `lstat`, decodes
only verified regular files, and maps every non-regular project node directly into the
shared MCP-extra and requested torch-config inspection-error contract.

Real directory and broken-relative-link cases preserve exact topology and populate both
component error fields plus the generic topology diagnostic. A capability-defined FIFO
case uses a bounded real worker and cleanup unblocking path without a skip marker, mock,
patch, or fake. The final Windows-accessible surfaces pass 58 torch-config tests and 183
install integration tests under Core 0.1.45; Ruff, formatting, Ty, BasedPyright,
complexity, and diff hygiene are green. The finding is resolved in S51.

### linked-project-false-positive | high | Valid live project links were reported as unreadable

The first correction treated every project symlink as an inspection error. A valid
live relative link inside the workspace is supported topology, so an unrelated required
node failure could incorrectly mark MCP-extra and torch-config inspection as failed.
The final implementation opens project content through a nonblocking descriptor,
validates the opened node with `fstat`, prevents link following where the platform
supports it, and resolves only live relative targets that remain inside the workspace.

The matrix regression proves that a valid live relative project link remains readable
when an unrelated workspace node triggers topology refusal: component actions stay
skipped, the generic topology error remains, and link plus target bytes are unchanged.
Broken, directory, and special project nodes continue through the shared component-error
contract. The finding is resolved in S51.

S51 verdict: **PASS — no actionable findings after resolution of both HIGH review
findings**. This verdict is limited to the corrective surface and does not grant
release readiness.

## Recommendations

Run S53 from a clean commit and restart every package, provider, host-recognition, and
publication gate from zero. The Windows ledger is 2,269 total, 1,832 selected, and 437
excluded test items. The POSIX ledger is 2,270 total, 1,833 selected, and 437 excluded
test items; Linux CI must collect and execute the POSIX-only FIFO regression because
this Windows review cannot grant that item execution credit.

## S54 correction review

### completion-deadline-enforcement | medium | The first bounded helper could credit a late terminal response

The first S54 review found that the 120-second deadline was checked only after each
administrative poll and after terminal-state recognition. A slow request could
therefore return `done` after expiry and still pass, while the environment-configurable
per-request timeout could extend the observed wait beyond the declared completion
contract.

The final helper computes the remaining wall-clock budget before each real service
poll, supplies that value as the poll's HTTP timeout, checks expiry again after the
response, and only then accepts an exact-job terminal phase. Timeout failure retains
the final job payload and full service envelope. The existing exact `done` assertions
remain authoritative, so `error` and `failed` responses terminate polling without being
converted into success. The finding is resolved in S54.

S54 verdict: **PASS — no actionable findings after resolution of the MEDIUM
deadline-enforcement finding**. This verdict is limited to the job-completion test
correction and does not grant release readiness or waive the complete platform-aware
release campaign.
