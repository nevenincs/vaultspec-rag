---
tags:
  - '#audit'
  - '#search-index-availability'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-search-index-availability-adr]]"
  - "[[2026-07-21-search-index-availability-plan]]"
---

# `search-index-availability` audit: `search-index-availability code review`

## Scope

Audit the committed search-availability implementation and tests against the accepted response
contract, service-domain ownership, shared-worktree campaign boundaries, and repository rules
that prohibit test doubles and tautological assertions.

## Findings

### mcp-overlap | high | initialize the real stdio session before rebuild submission

The first six-probe harness initialized its stdio child only after the measured rebuild entered a
running state. A fast job could finish while five probes waited. Sol medium corrected the harness
to initialize and hold the same official client session first, submit the rebuild second, observe
the exact running lease, and only then release all six real requests. Re-review cleared the finding.

### plan-line-endings | medium | close the MCP step and restore canonical line endings

Concurrent hook activity left the Model Context Protocol step open and committed the plan with
carriage-return line endings. A follow-up used the canonical plan command and documentation
formatter to close the step and restore line-feed formatting. Re-review cleared the finding.

### nonempty-authority | high | establish a real baseline before testing result preservation

Local graphics processing unit acceptance proved the original nonempty request had no prior index,
so its unavailable response was correct. Sol medium added a completed clean baseline index before
the second measured rebuild. The corrected real-daemon regression passed twice on immutable main.

### fixed-response-server | high | remove the prohibited response substitute

A parallel consumer-contract commit added a caller-programmed loopback server for malformed
responses. Despite using sockets, it substituted fixed daemon behavior and violated the repository
ban on fakes, mocks, and stubs. Terra xhigh extracted the real production envelope classifier; Sol
medium replaced the harness with direct tests of that production function and a genuine refused
connection. Final review cleared the finding.

### remediation-port | low | host-derived port can be omitted for a custom Host header

The structured remediation command derives its optional port from the request URL. Standard daemon
clients and the real regression provide the port, so this does not affect the supported path. The
review retained this as a non-blocking observation rather than expanding the bug-fix scope.

## Recommendations

- Keep the real graphics processing unit regression as the acceptance gate for changes to search,
  job snapshots, shared transport parsing, or stdio error propagation.
- Preserve canonical job-manager snapshots at the route boundary and fail closed on malformed or
  legacy response envelopes.
- Treat fixed-response network servers as prohibited test substitutes even when they use real
  loopback sockets.

No critical, high, or medium finding remains unresolved.
