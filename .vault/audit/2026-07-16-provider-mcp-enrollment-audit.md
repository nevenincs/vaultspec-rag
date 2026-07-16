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
findings**. This verdict is limited to the corrective surface and does not grant S52
release readiness.

## Recommendations

Run S52 from a clean commit and restart the exact 1,830-test release ledger and every
package, provider, host-recognition, and publication gate from zero. Linux CI or the S52
audit must collect the real FIFO regression; this Windows review cannot grant that node
execution credit.
